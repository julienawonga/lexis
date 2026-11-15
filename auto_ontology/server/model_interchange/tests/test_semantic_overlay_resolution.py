# SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
# SPDX-License-Identifier: Apache-2.0

"""The approved-overlay resolution: one validation in the common case."""

from __future__ import annotations

from typing import ClassVar
from unittest.mock import patch

from auto_ontology.semantic.contract import (
    EvidenceReference,
    KnowledgeProvenance,
    KnowledgeScope,
    KnowledgeStatus,
    SemanticConcept,
    SemanticLabel,
    SemanticModelDocument,
    SemanticRelation,
)
from auto_ontology.server.model_interchange import service
from auto_ontology.server.model_interchange.schemas import ExportRequest

_DB = "db-1"
_APPROVED_ROWS = (
    "auto_ontology.server.model_interchange.service.governance_dal."
    "current_approved_objects"
)


def _provenance() -> KnowledgeProvenance:
    return KnowledgeProvenance(
        actor_type="user",
        actor_id="reviewer-2",
        activity="semantic_review",
        evidence=(EvidenceReference(kind="human_review", reference="review-1"),),
    )


def _concept(object_id: str) -> SemanticConcept:
    return SemanticConcept(
        id=object_id,
        labels=(SemanticLabel(text=object_id, language="en"),),
        definition=f"Definition of {object_id}.",
        status=KnowledgeStatus.CERTIFIED,
        scope=KnowledgeScope(kind="database", database_id=_DB),
        provenance=_provenance(),
    )


def _relation(object_id: str, subject: str, target: str) -> SemanticRelation:
    return SemanticRelation(
        id=object_id,
        labels=(SemanticLabel(text=object_id, language="en"),),
        definition=f"{subject} relates to {target}.",
        status=KnowledgeStatus.CERTIFIED,
        scope=KnowledgeScope(kind="database", database_id=_DB),
        provenance=_provenance(),
        subject_id=subject,
        predicate="relates_to",
        object_id=target,
    )


def _row(obj: SemanticConcept | SemanticRelation) -> dict[str, object]:
    return {
        "object_id": obj.id,
        "base_fingerprint": "new",
        "proposed_document": obj.model_dump(mode="json"),
    }


def _empty_base() -> SemanticModelDocument:
    return SemanticModelDocument(model_id=f"lexis:{_DB}", objects=())


class _CountingDocument(SemanticModelDocument):
    """Counts how many times the whole model is validated."""

    built: ClassVar[int] = 0

    def __init__(self, **data: object) -> None:
        type(self).built += 1
        super().__init__(**data)


def test_a_supplied_base_is_not_projected_again() -> None:
    base = _empty_base()
    with (
        patch.object(service, "export_semantic_contract_base") as project,
        patch(_APPROVED_ROWS, return_value=[]),
    ):
        service.export_semantic_contract(ExportRequest(databases=[_DB]), base=base)

    project.assert_not_called()


def test_valid_overlay_validates_the_whole_model_once() -> None:
    concepts = [_concept(f"concept:{index}") for index in range(8)]
    _CountingDocument.built = 0
    with (
        patch.object(service, "SemanticModelDocument", _CountingDocument),
        patch(_APPROVED_ROWS, return_value=[_row(obj) for obj in concepts]),
    ):
        exported = service.export_semantic_contract(
            ExportRequest(databases=[_DB]), base=_empty_base()
        )

    assert [obj.id for obj in exported.objects] == [obj.id for obj in concepts]
    assert _CountingDocument.built == 1


def test_overlay_does_not_depend_on_row_order() -> None:
    concept = _concept("concept:a")
    other = _concept("concept:b")
    relation = _relation("relation:a-b", "concept:a", "concept:b")
    with patch(
        _APPROVED_ROWS, return_value=[_row(relation), _row(concept), _row(other)]
    ):
        exported = service.export_semantic_contract(
            ExportRequest(databases=[_DB]), base=_empty_base()
        )

    assert {obj.id for obj in exported.objects} == {
        "concept:a",
        "concept:b",
        "relation:a-b",
    }


def test_an_unplaceable_object_is_dropped_and_the_others_survive() -> None:
    good = _concept("concept:a")
    dangling = _relation("relation:bad", "concept:a", "concept:missing")
    with patch(_APPROVED_ROWS, return_value=[_row(dangling), _row(good)]):
        exported = service.export_semantic_contract(
            ExportRequest(databases=[_DB]), base=_empty_base()
        )

    assert [obj.id for obj in exported.objects] == ["concept:a"]
