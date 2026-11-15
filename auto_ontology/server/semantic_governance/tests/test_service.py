# SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
# SPDX-License-Identifier: Apache-2.0

"""Tests for proposal validation and independent human review."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from auto_ontology.semantic.contract import (
    CatalogBinding,
    EvidenceReference,
    KnowledgeProvenance,
    KnowledgeScope,
    KnowledgeStatus,
    SemanticConcept,
    SemanticLabel,
    SemanticModelDocument,
)
from auto_ontology.server.semantic_governance import service


def _concept(
    *, status: KnowledgeStatus = KnowledgeStatus.UNVERIFIED_LEGACY
) -> SemanticConcept:
    evidence = (
        (EvidenceReference(kind="human_review", reference="review-1"),)
        if status is KnowledgeStatus.CERTIFIED
        else ()
    )
    return SemanticConcept(
        id="concept:orders",
        labels=(SemanticLabel(text="Orders", language="en"),),
        definition="Orders submitted by customers.",
        status=status,
        scope=KnowledgeScope(kind="database", database_id="db-1"),
        provenance=KnowledgeProvenance(
            actor_type="system"
            if status is KnowledgeStatus.UNVERIFIED_LEGACY
            else "user",
            actor_id="legacy"
            if status is KnowledgeStatus.UNVERIFIED_LEGACY
            else "reviewer",
            activity="legacy_export"
            if status is KnowledgeStatus.UNVERIFIED_LEGACY
            else "semantic_review",
            evidence=evidence,
        ),
    )


def test_create_proposal_overwrites_client_authorship_and_status() -> None:
    legacy = _concept()
    current = SemanticModelDocument(model_id="lexis:db-1", objects=(legacy,))
    client_object = legacy.model_dump(mode="json")
    client_object["definition"] = "Orders accepted by the business."
    saved = {"id": "proposal-1", "state": "in_review"}

    with (
        patch.object(
            service.model_service, "export_semantic_contract", return_value=current
        ),
        patch.object(
            service.model_service,
            "export_semantic_contract_base",
            return_value=current,
        ),
        patch.object(
            service.governance_dal, "create_proposal", return_value=saved
        ) as create,
    ):
        result = service.create_proposal(
            database_id="db-1",
            object_document=client_object,
            evidence=(),
            comment="Clarified the business definition.",
            actor_id="submitter-1",
        )

    assert result == saved
    document = create.call_args.kwargs["document"]
    assert document["status"] == KnowledgeStatus.IN_REVIEW.value
    assert document["provenance"]["actor_id"] == "submitter-1"
    assert document["provenance"]["activity"] == "semantic_proposal"
    assert document["definition"] == "Orders accepted by the business."


def test_proposal_cannot_change_an_existing_catalog_binding() -> None:
    legacy = _concept().model_copy(
        update={
            "bindings": (
                CatalogBinding(
                    catalog_id="column-1",
                    role="maps_to",
                    object_kind="column",
                ),
            ),
        }
    )
    current = SemanticModelDocument(model_id="lexis:db-1", objects=(legacy,))
    client_object = legacy.model_dump(mode="json")
    client_object["bindings"][0]["catalog_id"] = "column-2"

    with (
        patch.object(
            service.model_service, "export_semantic_contract", return_value=current
        ),
        patch.object(
            service.model_service,
            "export_semantic_contract_base",
            return_value=current,
        ),
        pytest.raises(ValueError, match="Catalog bindings cannot be changed"),
    ):
        service.create_proposal(
            database_id="db-1",
            object_document=client_object,
            evidence=(),
            comment="Try to rebind this concept.",
            actor_id="submitter-1",
        )


def test_approval_records_reviewer_and_requires_human_review_evidence() -> None:
    legacy = _concept()
    current = SemanticModelDocument(model_id="lexis:db-1", objects=(legacy,))
    proposed = legacy.model_dump(mode="json")
    proposed.update(
        status=KnowledgeStatus.IN_REVIEW.value,
        provenance=KnowledgeProvenance(
            actor_type="user",
            actor_id="submitter-1",
            activity="semantic_proposal",
        ).model_dump(mode="json"),
    )
    proposal = {
        "id": "proposal-1",
        "object_id": legacy.id,
        "proposed_by": "submitter-1",
        "state": "in_review",
        "base_fingerprint": service.model_service.semantic_object_fingerprint(legacy),
        "proposed_document": proposed,
    }
    evidence = (EvidenceReference(kind="human_review", reference="review-1"),)

    with (
        patch.object(service.governance_dal, "fetch_proposal", return_value=proposal),
        patch.object(
            service.model_service,
            "export_semantic_contract_base",
            return_value=current,
        ),
        patch.object(
            service.model_service, "export_semantic_contract", return_value=current
        ),
        patch.object(
            service.governance_dal,
            "review_proposal",
            return_value={"id": "proposal-1"},
        ) as review,
    ):
        result = service.review_proposal(
            proposal_id="proposal-1",
            database_id="db-1",
            decision="approve",
            evidence=evidence,
            comment="Reviewed against the domain definition.",
            reviewer_id="reviewer-2",
        )

    assert result == {"id": "proposal-1"}
    final = review.call_args.kwargs["document"]
    assert final["status"] == KnowledgeStatus.CERTIFIED.value
    assert final["provenance"]["actor_id"] == "reviewer-2"
    assert final["provenance"]["evidence"][0]["kind"] == "human_review"


def test_approval_rejects_missing_human_review_reference() -> None:
    proposal = {"id": "proposal-1", "state": "in_review"}
    with (
        patch.object(service.governance_dal, "fetch_proposal", return_value=proposal),
        pytest.raises(ValueError, match="requires a human_review"),
    ):
        service.review_proposal(
            proposal_id="proposal-1",
            database_id="db-1",
            decision="approve",
            evidence=(),
            comment="Reviewed.",
            reviewer_id="reviewer-2",
        )
