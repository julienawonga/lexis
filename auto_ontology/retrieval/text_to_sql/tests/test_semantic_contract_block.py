# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Focused tests for the planner's certified semantic-contract block."""

from __future__ import annotations

from auto_ontology.retrieval.text_to_sql import semantic_contract as sc
from auto_ontology.semantic.contract import (
    EvidenceReference,
    KnowledgeKind,
    KnowledgeProvenance,
    KnowledgeScope,
    KnowledgeStatus,
    SemanticAttribute,
    SemanticConcept,
    SemanticLabel,
    SemanticMetric,
    SemanticModelDocument,
    SemanticRelation,
)

USER_PROVENANCE = KnowledgeProvenance(
    actor_type="user",
    actor_id="reviewer-1",
    activity="semantic_review",
    evidence=(EvidenceReference(kind="human_review", reference="review-1"),),
)


def _concept(
    object_id: str,
    *,
    status: KnowledgeStatus = KnowledgeStatus.CERTIFIED,
    definition: str = "A customer order.",
) -> SemanticConcept:
    return SemanticConcept(
        id=object_id,
        kind=KnowledgeKind.CONCEPT,
        labels=(SemanticLabel(text=f"Concept {object_id}", language="en"),),
        definition=definition,
        status=status,
        scope=KnowledgeScope(kind="database", database_id="db-1"),
        provenance=USER_PROVENANCE,
    )


def _document(*objects: SemanticConcept) -> SemanticModelDocument:
    return SemanticModelDocument(model_id="db-1", objects=objects)


def test_only_certified_concepts_attributes_relations_are_eligible() -> None:
    document = _document(
        _concept("c1"),
        _concept("c2", status=KnowledgeStatus.NEEDS_REVALIDATION),
        _concept("c3", status=KnowledgeStatus.UNVERIFIED_LEGACY),
    )
    eligible = sc.eligible_objects(document)
    assert [o.id for o in eligible] == ["c1"]


def test_a_certified_metric_or_query_is_not_rendered() -> None:
    metric = SemanticMetric(
        id="m1",
        kind=KnowledgeKind.METRIC,
        labels=(SemanticLabel(text="Revenue", language="en"),),
        definition="Sum of totals.",
        status=KnowledgeStatus.CERTIFIED,
        scope=KnowledgeScope(kind="database", database_id="db-1"),
        provenance=USER_PROVENANCE,
        concept_id="c1",
        expression="SUM(total)",
        expression_language="sql",
    )
    assert sc.eligible_objects(_document(metric, _concept("c1")))[0].id == "c1"
    block, rendered = sc.render_block(
        sc.eligible_objects(_document(metric, _concept("c1"))), 2000
    )
    assert "SUM(total)" not in block
    assert [o.id for o in rendered] == ["c1"]


def test_eligible_objects_of_an_empty_document_is_empty() -> None:
    assert sc.eligible_objects(_document()) == ()


def test_render_block_carries_ids_names_bindings_and_direction() -> None:
    attribute = SemanticAttribute(
        id="a1",
        kind=KnowledgeKind.ATTRIBUTE,
        labels=(SemanticLabel(text="Email", language="en"),),
        definition=" The customer's\n primary email. ",
        status=KnowledgeStatus.CERTIFIED,
        scope=KnowledgeScope(kind="database", database_id="db-1"),
        provenance=USER_PROVENANCE,
        concept_id="c1",
    )
    relation = SemanticRelation(
        id="r1",
        kind=KnowledgeKind.RELATION,
        labels=(SemanticLabel(text="Contains", language="en"),),
        definition="An order contains lines.",
        status=KnowledgeStatus.CERTIFIED,
        scope=KnowledgeScope(kind="database", database_id="db-1"),
        provenance=USER_PROVENANCE,
        subject_id="c1",
        predicate="contains",
        object_id="c2",
        cardinality="one_to_many",
    )
    block, rendered = sc.render_block(
        sc.eligible_objects(
            _document(_concept("c1"), _concept("c2"), attribute, relation)
        ),
        4000,
    )
    assert "concept c1 'Concept c1': A customer order." in block
    assert "attribute a1 of c1 'Email': The customer's primary email." in block
    assert "relation r1: c1 -contains-> c2" in block
    assert "(one_to_many)" in block
    assert [o.id for o in rendered] == ["a1", "c1", "c2", "r1"]


def test_render_block_stops_at_the_budget() -> None:
    objects = sc.eligible_objects(_document(_concept("c1"), _concept("c2")))
    one_line = len(sc.render_block(objects[:1], 2000)[0])
    block, rendered = sc.render_block(objects, one_line + 5)
    assert block
    assert len(block) <= one_line + 5
    assert len(rendered) == 1 < len(objects)


def test_render_block_with_nothing_that_fits_is_empty() -> None:
    block, rendered = sc.render_block(
        sc.eligible_objects(_document(_concept("c1"))), 10
    )
    assert block == ""
    assert rendered == ()


def test_render_block_is_deterministic() -> None:
    objects = sc.eligible_objects(_document(_concept("c1"), _concept("c2")))
    assert sc.render_block(objects, 2000)[0] == sc.render_block(objects, 2000)[0]


def _settings(enabled: bool = True) -> sc.SemanticContractSettings:
    return sc.SemanticContractSettings(enabled=enabled, budget_chars=2000)


def test_disabled_flag_or_blank_database_yields_none() -> None:
    assert sc.build_semantic_contract_block("db", _settings(False)) is None
    assert sc.build_semantic_contract_block("  ", _settings(True)) is None
    assert sc.build_semantic_contract_block(None, _settings(True)) is None


def test_unknown_database_yields_none() -> None:
    def unknown(database_name: str) -> SemanticModelDocument:
        raise ValueError("Catalog database 'nope' was not found")

    assert (
        sc.build_semantic_contract_block("nope", _settings(True), load_document=unknown)
        is None
    )


def test_block_builds_from_the_document_loader() -> None:
    document = _document(_concept("c1"))

    def loader(database_name: str) -> SemanticModelDocument:
        assert database_name == "chinook"
        return document

    result = sc.build_semantic_contract_block(
        "chinook", _settings(True), load_document=loader
    )
    assert result is not None
    assert result.block.startswith(sc.BLOCK_HEADER)
    assert [o.id for o in result.objects] == ["c1"]
    assert result.chars == len(result.block)


def test_an_empty_certified_set_yields_none() -> None:
    document = _document(_concept("c1", status=KnowledgeStatus.NEEDS_REVALIDATION))
    result = sc.build_semantic_contract_block(
        "chinook", _settings(True), load_document=lambda name: document
    )
    assert result is None
