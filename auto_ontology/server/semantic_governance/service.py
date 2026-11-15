# SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
# SPDX-License-Identifier: Apache-2.0

"""Validation and orchestration for semantic proposal review."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import TypeAdapter

from auto_ontology.dal import semantic_governance as governance_dal
from auto_ontology.semantic.contract import (
    EvidenceReference,
    KnowledgeProvenance,
    KnowledgeStatus,
    SemanticModelDocument,
    SemanticObject,
    SemanticRelation,
    SemanticAttribute,
    SemanticConcept,
)
from auto_ontology.server.model_interchange.schemas import ExportRequest
from auto_ontology.server.model_interchange import service as model_service

_OBJECT_ADAPTER = TypeAdapter(SemanticObject)
_CONTRACT_ADAPTER = TypeAdapter(SemanticModelDocument)


class UnknownSemanticObject(LookupError):
    """The requested semantic object is not in this database's model."""


def _bindings(obj: SemanticObject) -> tuple[dict[str, Any], ...]:
    if isinstance(obj, (SemanticConcept, SemanticAttribute)):
        bindings = obj.bindings
    elif isinstance(obj, SemanticRelation):
        bindings = obj.join_bindings
    else:
        bindings = ()
    return tuple(binding.model_dump(mode="json") for binding in bindings)


def _submitted_bindings(obj: dict[str, Any]) -> tuple[dict[str, Any], ...]:
    kind = obj.get("kind")
    key = "join_bindings" if kind == "relation" else "bindings"
    return tuple(obj.get(key) or ())


def _same_bindings(
    current: tuple[dict[str, Any], ...], submitted: tuple[dict[str, Any], ...]
) -> bool:
    def canonical(values: tuple[dict[str, Any], ...]) -> list[str]:
        return sorted(
            json.dumps(value, sort_keys=True, separators=(",", ":")) for value in values
        )

    return canonical(current) == canonical(submitted)


def _validate_model(
    current: SemanticModelDocument,
    candidate: SemanticObject,
) -> SemanticModelDocument:
    objects = list(current.objects)
    for index, existing in enumerate(objects):
        if existing.id == candidate.id:
            objects[index] = candidate
            break
    else:
        objects.append(candidate)
    return _CONTRACT_ADAPTER.validate_python(
        {"model_id": current.model_id, "objects": objects}
    )


def create_proposal(
    *,
    database_id: str,
    object_document: dict[str, Any],
    evidence: tuple[EvidenceReference, ...],
    comment: str,
    actor_id: str,
) -> dict[str, Any]:
    """Validate and persist a full-object proposal for human review.

    Existing physical bindings are immutable through this endpoint. New
    semantic objects can be proposed without physical bindings; mapping
    changes need a separately governed catalog operation.
    """
    request = ExportRequest(databases=[database_id])
    current = model_service.export_semantic_contract(request)
    baseline = model_service.export_semantic_contract_base(request)
    object_id = str(object_document.get("id") or "")
    kind = str(object_document.get("kind") or "")
    current_by_id = {obj.id: obj for obj in current.objects}
    baseline_by_id = {obj.id: obj for obj in baseline.objects}
    existing = current_by_id.get(object_id)
    baseline_object = baseline_by_id.get(object_id)

    if existing is not None and existing.kind.value != kind:
        raise ValueError("A semantic object's kind cannot be changed")

    payload = dict(object_document)
    payload.pop("status", None)
    payload.pop("provenance", None)
    if existing is not None:
        payload["legacy_certification"] = existing.legacy_certification
    else:
        if _submitted_bindings(payload):
            raise ValueError("New semantic objects must not invent catalog bindings")
        payload["legacy_certification"] = None

    scope = payload.get("scope")
    if not isinstance(scope, dict) or scope.get("kind") != "database":
        raise ValueError("Governed objects must have database scope")
    if scope.get("database_id") != database_id:
        raise ValueError("Object scope must match the selected database")

    provenance = KnowledgeProvenance(
        actor_type="user",
        actor_id=actor_id,
        activity="semantic_proposal",
        asserted_at=datetime.now(UTC),
        evidence=evidence,
    )
    payload["status"] = KnowledgeStatus.IN_REVIEW.value
    payload["provenance"] = provenance.model_dump(mode="json")
    candidate = _OBJECT_ADAPTER.validate_python(payload)
    if existing is not None and not _same_bindings(
        _bindings(existing), _bindings(candidate)
    ):
        raise ValueError(
            "Catalog bindings cannot be changed through semantic proposals"
        )
    _validate_model(current, candidate)

    fingerprint = (
        model_service.semantic_object_fingerprint(baseline_object)
        if baseline_object is not None
        else "new"
    )
    return governance_dal.create_proposal(
        model_id=current.model_id,
        object_id=candidate.id,
        object_kind=candidate.kind.value,
        document=candidate.model_dump(mode="json"),
        base_fingerprint=fingerprint,
        proposed_by=actor_id,
        comment=comment,
        evidence=[item.model_dump(mode="json") for item in evidence],
    )


def get_proposal(proposal_id: str, database_id: str) -> dict[str, Any] | None:
    return governance_dal.fetch_proposal(
        proposal_id,
        f"lexis:{database_id}",
    )


def list_proposals(
    database_id: str,
    *,
    state: Literal["in_review", "approved", "rejected"] | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    return governance_dal.list_proposals(
        f"lexis:{database_id}", state=state, limit=limit
    )


def review_proposal(
    *,
    proposal_id: str,
    database_id: str,
    decision: Literal["approve", "reject"],
    evidence: tuple[EvidenceReference, ...],
    comment: str,
    reviewer_id: str,
) -> dict[str, Any] | None:
    """Certify or reject a proposal, checking its source has not drifted."""
    model_id = f"lexis:{database_id}"
    proposal = governance_dal.fetch_proposal(proposal_id, model_id)
    if proposal is None:
        return None
    if proposal["state"] != "in_review":
        raise governance_dal.ProposalConflict("Proposal is no longer awaiting review")
    if decision == "approve" and not any(
        item.kind == "human_review" for item in evidence
    ):
        raise ValueError("Approval requires a human_review evidence reference")

    proposal_object = _OBJECT_ADAPTER.validate_python(proposal["proposed_document"])
    if decision == "approve":
        request = ExportRequest(databases=[database_id])
        baseline = model_service.export_semantic_contract_base(request)
        baseline_object = next(
            (obj for obj in baseline.objects if obj.id == proposal["object_id"]),
            None,
        )
        fingerprint = (
            model_service.semantic_object_fingerprint(baseline_object)
            if baseline_object is not None
            else "new"
        )
        if fingerprint != proposal["base_fingerprint"]:
            raise governance_dal.ProposalConflict(
                "The catalog meaning changed while this proposal was under review; "
                "submit a new proposal against the latest model"
            )

        existing_evidence = proposal_object.provenance.evidence
        provenance = KnowledgeProvenance(
            actor_type="user",
            actor_id=reviewer_id,
            activity="semantic_review",
            asserted_at=datetime.now(UTC),
            evidence=tuple(dict.fromkeys((*existing_evidence, *evidence))),
        )
        payload = proposal_object.model_dump(mode="json")
        payload["status"] = KnowledgeStatus.CERTIFIED.value
        payload["provenance"] = provenance.model_dump(mode="json")
        approved_object = _OBJECT_ADAPTER.validate_python(payload)
        current = model_service.export_semantic_contract(request)
        _validate_model(current, approved_object)
        document = approved_object.model_dump(mode="json")
        state_evidence = evidence
    else:
        document = proposal_object.model_dump(mode="json")
        state_evidence = evidence

    return governance_dal.review_proposal(
        proposal_id=proposal_id,
        model_id=model_id,
        decision=decision,
        reviewed_by=reviewer_id,
        document=document,
        evidence=[item.model_dump(mode="json") for item in state_evidence],
        comment=comment,
    )


__all__ = [
    "UnknownSemanticObject",
    "create_proposal",
    "get_proposal",
    "list_proposals",
    "review_proposal",
]
