# SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
# SPDX-License-Identifier: Apache-2.0

"""Validation tests for the portable semantic knowledge contract."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from auto_ontology.semantic.contract import (
    EvidenceReference,
    KnowledgeProvenance,
    KnowledgeScope,
    KnowledgeStatus,
    SemanticAttribute,
    SemanticConcept,
    SemanticLabel,
    SemanticModelDocument,
    SemanticVerifiedQuery,
)


def _provenance(
    *, actor_type: str = "agent", evidence: tuple = ()
) -> KnowledgeProvenance:
    return KnowledgeProvenance(
        actor_type=actor_type,
        actor_id="agent-1",
        activity="modeling",
        evidence=evidence,
    )


def _concept(**overrides: object) -> SemanticConcept:
    values: dict[str, object] = {
        "id": "concept:order",
        "labels": (SemanticLabel(text="Order", language="en"),),
        "definition": "A customer order.",
        "status": KnowledgeStatus.DRAFT,
        "scope": KnowledgeScope(kind="database", database_id="db-1"),
        "provenance": _provenance(),
    }
    values.update(overrides)
    return SemanticConcept(**values)


def test_document_accepts_valid_concept_attribute_graph() -> None:
    concept = _concept()
    attribute = SemanticAttribute(
        id="attribute:order-id",
        concept_id=concept.id,
        labels=(SemanticLabel(text="Order ID", language="en"),),
        definition="Unique identifier of an order.",
        status=KnowledgeStatus.DRAFT,
        scope=concept.scope,
        provenance=_provenance(),
    )

    document = SemanticModelDocument(
        model_id="retail",
        objects=(concept, attribute),
    )

    assert document.objects == (concept, attribute)


def test_document_rejects_dangling_or_wrong_kind_references() -> None:
    attribute = SemanticAttribute(
        id="attribute:order-id",
        concept_id="missing-concept",
        labels=(SemanticLabel(text="Order ID", language="en"),),
        definition="Unique identifier of an order.",
        status=KnowledgeStatus.DRAFT,
        scope=KnowledgeScope(kind="database", database_id="db-1"),
        provenance=_provenance(),
    )

    with pytest.raises(ValidationError, match="must reference an included concept"):
        SemanticModelDocument(model_id="retail", objects=(attribute,))


def test_document_rejects_duplicate_ids() -> None:
    concept = _concept()
    duplicate = concept.model_copy(update={"definition": "Another definition."})

    with pytest.raises(ValidationError, match="ids must be unique"):
        SemanticModelDocument(model_id="retail", objects=(concept, duplicate))


def test_certified_knowledge_requires_a_human_and_evidence() -> None:
    with pytest.raises(ValidationError, match="requires a human actor"):
        _concept(status=KnowledgeStatus.CERTIFIED)

    human_provenance = KnowledgeProvenance(
        actor_type="user",
        actor_id="user-1",
        activity="reviewed",
    )
    with pytest.raises(ValidationError, match="requires human-review evidence"):
        _concept(status=KnowledgeStatus.CERTIFIED, provenance=human_provenance)


def test_scope_requires_its_scope_identifier() -> None:
    with pytest.raises(ValidationError, match="requires database_id"):
        KnowledgeScope(kind="database")


def test_language_tag_rejects_underscore_locale_notation() -> None:
    with pytest.raises(ValidationError, match="valid BCP 47 language tag"):
        SemanticLabel(text="Order", language="en_US")


def test_verified_query_requires_certification_and_execution_evidence() -> None:
    provenance = KnowledgeProvenance(
        actor_type="user",
        actor_id="reviewer-1",
        activity="verified_query",
        evidence=(
            EvidenceReference(kind="execution", reference="run-1"),
            EvidenceReference(kind="human_review", reference="review-1"),
        ),
    )
    values: dict[str, object] = {
        "id": "query:orders",
        "labels": (SemanticLabel(text="Orders", language="en"),),
        "definition": "A validated query for orders.",
        "status": KnowledgeStatus.CERTIFIED,
        "scope": KnowledgeScope(kind="database", database_id="db-1"),
        "provenance": provenance,
        "question": "How many orders are there?",
        "sql": "SELECT COUNT(*) FROM orders",
    }

    assert SemanticVerifiedQuery(**values).status is KnowledgeStatus.CERTIFIED

    without_execution = provenance.model_copy(
        update={
            "evidence": (EvidenceReference(kind="human_review", reference="review-1"),),
        },
    )
    with pytest.raises(ValidationError, match="require execution evidence"):
        SemanticVerifiedQuery(**{**values, "provenance": without_execution})

    with pytest.raises(ValidationError, match="must be in review"):
        SemanticVerifiedQuery(**{**values, "status": KnowledgeStatus.DRAFT})


def test_validity_interval_must_be_positive() -> None:
    start = datetime(2026, 1, 2, tzinfo=UTC)

    with pytest.raises(ValidationError, match="valid_to must be later"):
        _concept(valid_from=start, valid_to=start - timedelta(seconds=1))


def test_contract_objects_are_frozen_and_reject_unknown_fields() -> None:
    concept = _concept()

    with pytest.raises(ValidationError):
        concept.definition = "Changed"
    with pytest.raises(ValidationError, match="extra_forbidden"):
        _concept(unreviewed_assumption=True)
