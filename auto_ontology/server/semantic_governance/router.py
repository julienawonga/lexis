# SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
# SPDX-License-Identifier: Apache-2.0

"""Authenticated REST routes for semantic proposal and review workflows."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from auto_ontology.dal import model_interchange as model_dal
from auto_ontology.dal import semantic_governance as governance_dal
from auto_ontology.dal.owners import CATALOG_EDIT
from auto_ontology.semantic.contract import EvidenceReference
from auto_ontology.server.identity import resolve_internal_user
from auto_ontology.server.owners import enforce_permission
from auto_ontology.server.semantic_governance import service

router = APIRouter()


class SemanticProposalCreate(BaseModel):
    database_name: str = Field(min_length=1)
    object: dict[str, Any]
    evidence: tuple[EvidenceReference, ...] = ()
    comment: str = Field(min_length=1, max_length=4000)


class SemanticProposalReview(BaseModel):
    database_name: str = Field(min_length=1)
    decision: Literal["approve", "reject"]
    evidence: tuple[EvidenceReference, ...] = ()
    comment: str = Field(min_length=1, max_length=4000)


def _database_id(database_name: str) -> str:
    database_id = model_dal.fetch_database_id_by_name(database_name)
    if database_id is None:
        raise HTTPException(
            status_code=404,
            detail=f"Catalog database {database_name!r} was not found",
        )
    return database_id


def _editor_id(request: Request) -> str:
    user_id = resolve_internal_user(request, required=True)
    enforce_permission(request, CATALOG_EDIT)
    assert user_id is not None
    return user_id


@router.get("/semantic-model/proposals")
def list_semantic_proposals(
    database_name: str = Query(min_length=1),
    state: Literal["in_review", "approved", "rejected"] | None = None,
    limit: int = Query(default=100, ge=1, le=500),
) -> dict[str, list[dict[str, Any]]]:
    """List proposal metadata for one database; details include event history."""
    rows = service.list_proposals(_database_id(database_name), state=state, limit=limit)
    return {"data": rows}


@router.post("/semantic-model/proposals", status_code=201)
def create_semantic_proposal(
    request: Request,
    body: SemanticProposalCreate,
) -> dict[str, dict[str, Any]]:
    """Submit an existing or new database-scoped object for human review."""
    actor_id = _editor_id(request)
    database_id = _database_id(body.database_name)
    try:
        proposal = service.create_proposal(
            database_id=database_id,
            object_document=body.object,
            evidence=body.evidence,
            comment=body.comment.strip(),
            actor_id=actor_id,
        )
    except governance_dal.ProposalConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"data": proposal}


@router.get("/semantic-model/proposals/{proposal_id}")
def get_semantic_proposal(
    proposal_id: str,
    database_name: str = Query(min_length=1),
) -> dict[str, dict[str, Any]]:
    """Read one proposal with its immutable decision history."""
    proposal = service.get_proposal(proposal_id, _database_id(database_name))
    if proposal is None:
        raise HTTPException(status_code=404, detail="Semantic proposal not found")
    return {"data": proposal}


@router.post("/semantic-model/proposals/{proposal_id}/review")
def review_semantic_proposal(
    request: Request,
    proposal_id: str,
    body: SemanticProposalReview,
) -> dict[str, dict[str, Any]]:
    """Approve or reject a proposal and persist the reviewer and evidence."""
    reviewer_id = _editor_id(request)
    database_id = _database_id(body.database_name)
    try:
        result = service.review_proposal(
            proposal_id=proposal_id,
            database_id=database_id,
            decision=body.decision,
            evidence=body.evidence,
            comment=body.comment.strip(),
            reviewer_id=reviewer_id,
        )
    except governance_dal.ProposalConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if result is None:
        raise HTTPException(status_code=404, detail="Semantic proposal not found")
    proposal = service.get_proposal(proposal_id, database_id)
    return {"data": proposal or result}


__all__ = ["router"]
