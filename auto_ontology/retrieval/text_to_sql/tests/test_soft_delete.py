# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Soft-delete detection and annotation, with fake catalog data and no model."""

from __future__ import annotations

import pytest

from auto_ontology.retrieval.text_to_sql import soft_delete
from auto_ontology.retrieval.text_to_sql.formatters_util import (
    format_tables_for_prompt,
    format_used_schema_for_prompt,
)
from auto_ontology.retrieval.text_to_sql.prompts import (
    create_intent_validation_prompt,
)
from auto_ontology.retrieval.text_to_sql.soft_delete import (
    VALIDATOR_CARVE_OUT,
    annotate_soft_deletes,
    is_soft_delete_column,
    soft_delete_columns_applied,
    soft_delete_note,
)

TS = "timestamp without time zone"


def _col(name: str, data_type: str = TS, nullable: bool | None = True) -> dict:
    return {"name": name, "data_type": data_type, "is_nullable": nullable}


@pytest.mark.parametrize(
    "name,data_type",
    [
        ("deleted_at", TS),
        ("deleted_at", "timestamp with time zone"),
        ("deleted_at", "timestamptz"),
        ("deleted_at", "DATETIME"),
        ("deleted_at", "datetime2"),
        ("deleted_on", "date"),
        ("deletedAt", TS),
        ("DeletedAt", TS),
        ("deleted-at", TS),
        ("removed_at", TS),
        ("archived_at", TS),
        ("archived_on", "date"),
        ("voided_at", TS),
        ("trashed_at", TS),
        ("discarded_at", TS),
        ("deleted_ts", TS),
        ("deleted_dt", TS),
        ("date_deleted", "date"),
        ("deleted_timestamp", TS),
        ("deleted", TS),
        ("archived", "date"),
    ],
)
def test_markers_are_detected(name: str, data_type: str) -> None:
    assert is_soft_delete_column(_col(name, data_type))


@pytest.mark.parametrize(
    "name,data_type,nullable",
    [
        # Business states, not deletion.
        ("retired_on", "date", True),
        ("closed_on", "date", True),
        ("cancelled_at", TS, True),
        ("canceled_at", TS, True),
        ("expires_at", TS, True),
        ("expired_at", TS, True),
        ("ended_at", TS, True),
        ("inactive_since", TS, True),
        ("terminated_at", TS, True),
        # Not a date or timestamp.
        ("is_deleted", "boolean", True),
        ("deleted", "boolean", True),
        ("deleted_at", "text", True),
        ("deleted_at", "bigint", True),
        ("deleted_at", "time without time zone", True),
        ("deleted_at", "interval", True),
        ("status", "text", True),
        # Not nullable or unknown nullability: cannot mean "live while NULL".
        ("deleted_at", TS, False),
        ("deleted_at", TS, None),
        # Deletion word without a time word.
        ("deleted_by", TS, True),
        ("deleted_reason", TS, True),
        # Unrelated names.
        ("created_at", TS, True),
        ("updated_at", TS, True),
        ("undeleted_at", TS, True),
        ("deleted_count", TS, True),
    ],
)
def test_look_alikes_are_not_detected(
    name: str, data_type: str, nullable: bool | None
) -> None:
    assert not is_soft_delete_column(_col(name, data_type, nullable))


def test_missing_fields_are_not_detected() -> None:
    assert not is_soft_delete_column({"name": "deleted_at"})
    assert not is_soft_delete_column({"data_type": TS, "is_nullable": True})
    assert not is_soft_delete_column("deleted_at")


def test_word_list_excludes_business_states() -> None:
    forbidden = {
        "cancelled",
        "canceled",
        "retired",
        "closed",
        "expired",
        "ended",
        "inactive",
        "active",
    }
    assert not forbidden & soft_delete.DELETION_WORDS


def _customer() -> dict:
    return {
        "name": "customer",
        "schema_name": "public",
        "database_name": "shop",
        "pk": "cust_id",
        "columns": [
            _col("cust_id", "integer", False),
            _col("deleted_at"),
        ],
    }


def _order() -> dict:
    return {
        "name": "orders",
        "schema_name": "public",
        "database_name": "shop",
        "pk": "order_id",
        "columns": [
            _col("order_id", "integer", False),
            _col("archived_at", "date"),
            _col("cancelled_at"),
        ],
    }


def _invoice() -> dict:
    return {
        "name": "invoice",
        "schema_name": "public",
        "database_name": "shop",
        "pk": "id",
        "columns": [_col("id", "integer", False), _col("closed_on", "date")],
    }


def test_annotation_marks_only_tables_with_a_marker() -> None:
    tables = [_customer(), _invoice()]
    annotated = annotate_soft_deletes(tables)
    assert annotated[0]["soft_delete_columns"] == ["deleted_at"]
    assert "soft_delete_columns" not in annotated[1]
    assert annotated[1] is tables[1]
    # The input is not mutated.
    assert "soft_delete_columns" not in tables[0]


def test_prompt_has_note_only_for_annotated_tables() -> None:
    rendered = format_tables_for_prompt(
        annotate_soft_deletes([_customer(), _invoice()])
    )
    assert rendered.count("Soft delete:") == 1
    customer_block, invoice_block = rendered.split("\n\n")
    assert "`deleted_at IS NULL`" in customer_block
    assert "Soft delete:" not in invoice_block


def test_note_says_how_to_exclude_and_when_not_to() -> None:
    note = soft_delete_note(["deleted_at"])
    assert "`deleted_at IS NULL`" in note
    assert "also when the table is joined" in note
    assert (
        "unless the question explicitly asks about deleted, removed or archived" in note
    )
    assert "all history" in note


def test_two_joined_tables_each_get_their_own_note() -> None:
    tables = annotate_soft_deletes([_customer(), _order()])
    rendered = format_tables_for_prompt(tables)
    assert rendered.count("Soft delete:") == 2
    assert "`deleted_at IS NULL`" in rendered
    assert "`archived_at IS NULL`" in rendered
    # cancelled_at on the same table is a business state, not a marker.
    assert "`cancelled_at IS NULL`" not in rendered
    assert soft_delete_columns_applied(tables) == [
        "customer.deleted_at",
        "orders.archived_at",
    ]


def test_table_with_two_markers_lists_both() -> None:
    table = _customer()
    table["columns"].append(_col("archived_at", "date"))
    note = soft_delete_note(annotate_soft_deletes([table])[0]["soft_delete_columns"])
    assert "`deleted_at IS NULL` and `archived_at IS NULL`" in note


def test_used_schema_context_carries_the_note() -> None:
    tables = annotate_soft_deletes([_customer()])
    context = format_used_schema_for_prompt(
        tables, ["public.customer"], ["public.customer.deleted_at"]
    )
    assert "Soft delete:" in context


# Rendered by the formatters before this feature existed (taken from main).
_GOLDEN_TABLES = (
    "table | primary key\nshop.public.customer | cust_id\n"
    "column | type | is_nullable\ncust_id | integer | false\n"
    "deleted_at | timestamp without time zone | true"
)
_GOLDEN_USED = (
    "TABLES USED IN SQL:\n- shop.public.customer | primary key: cust_id\n\n"
    "COLUMNS USED IN SQL:\n- shop.public.customer.deleted_at "
    "(timestamp without time zone) | is_nullable: true"
)


def test_unannotated_rendering_is_byte_identical_to_before() -> None:
    tables = [_customer()]
    assert format_tables_for_prompt(tables) == _GOLDEN_TABLES
    assert (
        format_used_schema_for_prompt(
            tables, ["public.customer"], ["public.customer.deleted_at"]
        )
        == _GOLDEN_USED
    )


def _prompt(used_schema_context: str) -> str:
    return create_intent_validation_prompt(
        "How many customers do we have?",
        "How many customers do we have?",
        "How many customers do we have?",
        "SELECT COUNT(cust_id) FROM customer WHERE deleted_at IS NULL",
        used_schema_context=used_schema_context,
    )


def test_validator_carve_out_only_when_a_note_is_shown() -> None:
    tables = [_customer()]
    args = (["public.customer"], ["public.customer.deleted_at"])
    plain = _prompt(format_used_schema_for_prompt(tables, *args))
    noted = _prompt(format_used_schema_for_prompt(annotate_soft_deletes(tables), *args))
    assert VALIDATOR_CARVE_OUT not in plain
    assert "'Soft delete:' note" not in plain
    assert VALIDATOR_CARVE_OUT in noted
    assert "do not flag it as a filter the question did not request" in noted


def test_flag_helper_defaults_to_off(monkeypatch: pytest.MonkeyPatch) -> None:
    from auto_ontology.infra import feature_flags

    seen: dict = {}

    def fake_read(key: str, *, default: bool) -> bool:
        seen["key"], seen["default"] = key, default
        return default

    monkeypatch.setattr(feature_flags, "read_configuration_flag", fake_read)
    assert feature_flags.is_soft_delete_hint_enabled() is False
    assert seen == {"key": "soft_delete_hint_enabled", "default": False}


def _run_preparation(monkeypatch: pytest.MonkeyPatch, enabled: bool) -> dict:
    from typing import cast

    from auto_ontology.retrieval.text_to_sql.agents import candidates_preparation
    from auto_ontology.retrieval.text_to_sql.agents.candidates_preparation import (
        CandidatePreparationAgent,
    )
    from auto_ontology.retrieval.text_to_sql.state import AgentState

    customer = {**_customer(), "id": "customer"}
    monkeypatch.setattr(
        candidates_preparation, "is_soft_delete_hint_enabled", lambda: enabled
    )
    monkeypatch.setattr(
        CandidatePreparationAgent,
        "_retrieve_additional_tables",
        lambda self, retriever, question, entities, target_db: [],
    )
    monkeypatch.setattr(
        CandidatePreparationAgent,
        "_filter_tables_by_relevance",
        lambda self, state, question, tables, custom_analyses=None, attribute_join_paths=None: (
            tables,
            "",
        ),
    )
    monkeypatch.setattr(
        candidates_preparation, "fetch_custom_analyses_with_sql", lambda ids: []
    )
    monkeypatch.setattr(
        candidates_preparation, "fetch_tables_from_custom_analyses", lambda ids: []
    )
    monkeypatch.setattr(
        candidates_preparation,
        "get_relevant_tables_from_candidates",
        lambda candidates: [customer],
    )
    monkeypatch.setattr(candidates_preparation, "fetch_tables_by_ids", lambda ids: [])
    monkeypatch.setattr(
        candidates_preparation,
        "find_connected_junction_tables",
        lambda ids: ([], []),
    )
    state = cast(
        AgentState,
        {
            "initial_question": "How many customers do we have?",
            "data_retriever": object(),
            "path_state": {
                "target_db": "shop",
                "retrieved_custom_analyses": [{"id": "analysis"}],
            },
        },
    )
    return candidates_preparation.CandidatePreparationAgent().execute(state)[
        "path_state"
    ]


def test_preparation_flag_on_annotates_and_records_trace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _run_preparation(monkeypatch, enabled=True)
    assert result["relevant_tables"][0]["soft_delete_columns"] == ["deleted_at"]
    assert result["soft_delete_columns_applied"] == ["customer.deleted_at"]
    assert "Soft delete:" in format_tables_for_prompt(result["relevant_tables"])


def test_preparation_flag_off_changes_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _run_preparation(monkeypatch, enabled=False)
    assert "soft_delete_columns" not in result["relevant_tables"][0]
    assert "soft_delete_columns_applied" not in result
    assert "Soft delete:" not in format_tables_for_prompt(result["relevant_tables"])
