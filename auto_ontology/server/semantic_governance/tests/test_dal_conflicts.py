# SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
# SPDX-License-Identifier: Apache-2.0

"""Only the one-open-proposal index is reported as a review conflict."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest
from sqlalchemy.exc import IntegrityError

from auto_ontology.dal import semantic_governance as dal


def _integrity_error(message: str, *, constraint: str | None = None) -> IntegrityError:
    orig = Exception(message)
    if constraint is not None:
        orig.diag = SimpleNamespace(constraint_name=constraint)  # type: ignore[attr-defined]
    return IntegrityError("INSERT ...", {}, orig)


def _failing_transaction(error: IntegrityError) -> Any:
    @contextmanager
    def transaction() -> Iterator[None]:
        raise error
        yield  # pragma: no cover

    return transaction


def _create() -> dict[str, Any]:
    return dal.create_proposal(
        model_id="lexis:db-1",
        object_id="concept:orders",
        object_kind="concept",
        document={},
        base_fingerprint="new",
        proposed_by="submitter-1",
        comment="",
        evidence=[],
    )


def test_open_proposal_index_violation_is_a_conflict() -> None:
    error = _integrity_error("duplicate key", constraint=dal._IN_REVIEW_INDEX)
    with (
        patch.object(dal, "write_transaction", _failing_transaction(error)),
        pytest.raises(dal.ProposalConflict, match="awaiting review"),
    ):
        _create()


def test_index_name_in_the_message_is_a_conflict_without_diagnostics() -> None:
    error = _integrity_error(f'violates unique index "{dal._IN_REVIEW_INDEX}"')
    with (
        patch.object(dal, "write_transaction", _failing_transaction(error)),
        pytest.raises(dal.ProposalConflict),
    ):
        _create()


def test_a_check_constraint_failure_is_not_reported_as_a_conflict() -> None:
    error = _integrity_error(
        "check failed", constraint="ck_semantic_proposal_object_kind"
    )
    with (
        patch.object(dal, "write_transaction", _failing_transaction(error)),
        pytest.raises(IntegrityError),
    ):
        _create()


def test_review_runs_verify_after_locking_and_can_refuse() -> None:
    """The caller's check runs on the locked row and aborts the decision."""
    calls: list[str] = []
    locked = {"id": "proposal-1", "state": "in_review", "object_id": "o"}

    @contextmanager
    def transaction() -> Iterator[None]:
        calls.append("begin")
        yield

    def refuse(proposal: dict[str, Any]) -> None:
        calls.append("verify")
        assert proposal["id"] == "proposal-1"
        raise dal.ProposalConflict("source drifted")

    class _Store:
        def query_read(self, *_: object, **__: object) -> list[dict[str, Any]]:
            calls.append("read")
            return [locked]

        def query_write(self, *_: object, **__: object) -> list[dict[str, Any]]:
            calls.append("write")
            return [locked]

    with (
        patch.object(dal, "write_transaction", transaction),
        patch.object(dal, "store", lambda: _Store()),
        pytest.raises(dal.ProposalConflict, match="source drifted"),
    ):
        dal.review_proposal(
            proposal_id="proposal-1",
            model_id="lexis:db-1",
            decision="approve",
            reviewed_by="reviewer-2",
            document={},
            evidence=[],
            comment="",
            verify=refuse,
        )

    assert calls == ["begin", "read", "verify"]
