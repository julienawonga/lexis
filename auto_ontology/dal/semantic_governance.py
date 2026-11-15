# SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
# SPDX-License-Identifier: Apache-2.0

"""Persistence for reviewed semantic-object proposals and their history."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, insert, select, update
from sqlalchemy.exc import IntegrityError

from auto_ontology.dal import schema as s
from auto_ontology.dal.session import store, write_transaction


class ProposalConflict(ValueError):
    """The proposal is stale or is no longer awaiting review."""


def latest_approved_version(model_id: str, object_id: str) -> int:
    """Return the current approved version, or zero when the object is new."""
    version = store().query_read(
        select(
            func.coalesce(func.max(s.semantic_proposal.c.approved_version), 0).label(
                "version"
            )
        ).where(
            s.semantic_proposal.c.model_id == model_id,
            s.semantic_proposal.c.object_id == object_id,
            s.semantic_proposal.c.state == "approved",
        )
    )
    return int(version[0]["version"]) if version else 0


def _write_event(
    *,
    proposal_id: str,
    event_type: str,
    actor_id: str,
    from_state: str | None,
    to_state: str,
    document: dict[str, Any],
    evidence: list[dict[str, Any]],
    comment: str | None,
) -> None:
    store().query_write(
        insert(s.semantic_governance_event).values(
            proposal_id=proposal_id,
            event_type=event_type,
            actor_id=actor_id,
            from_state=from_state,
            to_state=to_state,
            document_snapshot=document,
            evidence=evidence,
            comment=comment,
        )
    )


def create_proposal(
    *,
    model_id: str,
    object_id: str,
    object_kind: str,
    document: dict[str, Any],
    base_fingerprint: str,
    proposed_by: str,
    comment: str,
    evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    """Persist a proposal and its first immutable event atomically."""
    try:
        with write_transaction():
            open_proposals = store().query_read(
                select(s.semantic_proposal.c.id).where(
                    s.semantic_proposal.c.model_id == model_id,
                    s.semantic_proposal.c.object_id == object_id,
                    s.semantic_proposal.c.state == "in_review",
                )
            )
            if open_proposals:
                raise ProposalConflict(
                    "An object already has a proposal awaiting review"
                )

            base_version = latest_approved_version(model_id, object_id)
            rows = store().query_write(
                insert(s.semantic_proposal)
                .values(
                    model_id=model_id,
                    object_id=object_id,
                    object_kind=object_kind,
                    proposed_document=document,
                    state="in_review",
                    base_version=base_version,
                    base_fingerprint=base_fingerprint,
                    proposed_by=proposed_by,
                    review_evidence=[],
                    created_by=proposed_by,
                    modified_by=proposed_by,
                )
                .returning(s.semantic_proposal)
            )
            proposal = dict(rows[0])
            _write_event(
                proposal_id=proposal["id"],
                event_type="proposed",
                actor_id=proposed_by,
                from_state=None,
                to_state="in_review",
                document=document,
                evidence=evidence,
                comment=comment,
            )
    except IntegrityError as exc:
        raise ProposalConflict(
            "An object already has a proposal awaiting review"
        ) from exc
    return proposal


def fetch_proposal(proposal_id: str, model_id: str) -> dict[str, Any] | None:
    rows = store().query_read(
        select(s.semantic_proposal).where(
            s.semantic_proposal.c.id == proposal_id,
            s.semantic_proposal.c.model_id == model_id,
        )
    )
    if not rows:
        return None
    proposal = dict(rows[0])
    proposal["events"] = store().query_read(
        select(s.semantic_governance_event)
        .where(s.semantic_governance_event.c.proposal_id == proposal_id)
        .order_by(
            s.semantic_governance_event.c.created,
            s.semantic_governance_event.c.id,
        )
    )
    return proposal


def list_proposals(
    model_id: str,
    *,
    state: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    statement = select(s.semantic_proposal).where(
        s.semantic_proposal.c.model_id == model_id
    )
    if state is not None:
        statement = statement.where(s.semantic_proposal.c.state == state)
    rows = store().query_read(
        statement.order_by(s.semantic_proposal.c.created.desc()).limit(limit)
    )
    return [dict(row) for row in rows]


def current_approved_objects(model_id: str) -> list[dict[str, Any]]:
    """Return the highest approved version of each object in this model."""
    proposal = s.semantic_proposal
    ranked = (
        select(
            *proposal.c,
            func.row_number()
            .over(
                partition_by=(proposal.c.model_id, proposal.c.object_id),
                order_by=proposal.c.approved_version.desc(),
            )
            .label("version_rank"),
        )
        .where(proposal.c.model_id == model_id, proposal.c.state == "approved")
        .subquery()
    )
    return [
        dict(row)
        for row in store().query_read(select(ranked).where(ranked.c.version_rank == 1))
    ]


def review_proposal(
    *,
    proposal_id: str,
    model_id: str,
    decision: str,
    reviewed_by: str,
    document: dict[str, Any],
    evidence: list[dict[str, Any]],
    comment: str,
) -> dict[str, Any] | None:
    """Record a review decision with optimistic version checking."""
    with write_transaction():
        rows = store().query_read(
            select(s.semantic_proposal)
            .where(
                s.semantic_proposal.c.id == proposal_id,
                s.semantic_proposal.c.model_id == model_id,
            )
            .with_for_update()
        )
        if not rows:
            return None
        proposal = dict(rows[0])
        if proposal["state"] != "in_review":
            raise ProposalConflict("Proposal is no longer awaiting review")

        current_version = latest_approved_version(model_id, proposal["object_id"])
        if current_version != proposal["base_version"]:
            raise ProposalConflict(
                "The semantic object changed after this proposal was submitted; "
                "submit a new proposal against the latest version"
            )
        if decision == "approve" and reviewed_by == proposal["proposed_by"]:
            raise ProposalConflict("A proposal must be approved by a different user")

        next_version = current_version + 1 if decision == "approve" else None
        next_state = "approved" if decision == "approve" else "rejected"
        updated = store().query_write(
            update(s.semantic_proposal)
            .where(s.semantic_proposal.c.id == proposal_id)
            .values(
                state=next_state,
                proposed_document=document,
                reviewed_by=reviewed_by,
                review_comment=comment,
                review_evidence=evidence,
                approved_version=next_version,
                modified_by=reviewed_by,
                modified=func.now(),
            )
            .returning(s.semantic_proposal)
        )
        _write_event(
            proposal_id=proposal_id,
            event_type=next_state,
            actor_id=reviewed_by,
            from_state="in_review",
            to_state=next_state,
            document=document,
            evidence=evidence,
            comment=comment,
        )
    return dict(updated[0])


__all__ = [
    "ProposalConflict",
    "create_proposal",
    "current_approved_objects",
    "fetch_proposal",
    "latest_approved_version",
    "list_proposals",
    "review_proposal",
]
