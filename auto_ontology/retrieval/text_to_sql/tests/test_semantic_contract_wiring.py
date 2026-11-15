# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Wiring tests: the certified semantic-contract block reaches the evidence."""

from __future__ import annotations

import logging

import pytest
from pydantic import BaseModel, ValidationError

from auto_ontology.retrieval.text_to_sql.agents import candidates_retrieval
from auto_ontology.retrieval.text_to_sql.agents.candidates_retrieval import (
    CandidateRetrievalAgent,
)
from auto_ontology.retrieval.text_to_sql import semantic_contract as sc
from auto_ontology.semantic.contract import (
    KnowledgeKind,
    KnowledgeProvenance,
    KnowledgeScope,
    KnowledgeStatus,
    EvidenceReference,
    SemanticConcept,
    SemanticLabel,
    SemanticModelDocument,
)

TERM_BLOCK_HEADER = "Business definitions"


def _agent() -> CandidateRetrievalAgent:
    agent = object.__new__(CandidateRetrievalAgent)
    agent.logger = logging.getLogger("test-semantic-contract")
    return agent


def _document() -> SemanticModelDocument:
    concept = SemanticConcept(
        id="c1",
        kind=KnowledgeKind.CONCEPT,
        labels=(SemanticLabel(text="Customer Order", language="en"),),
        definition="A customer order submitted at checkout.",
        status=KnowledgeStatus.CERTIFIED,
        scope=KnowledgeScope(kind="database", database_id="db-1"),
        provenance=KnowledgeProvenance(
            actor_type="user",
            actor_id="reviewer-1",
            activity="semantic_review",
            evidence=(EvidenceReference(kind="human_review", reference="r1"),),
        ),
    )
    return SemanticModelDocument(model_id="db-1", objects=(concept,))


@pytest.fixture
def enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SEMANTIC_CONTRACT_BLOCK", "1")


def _loader(document: SemanticModelDocument):
    return lambda database_name: document


def test_flag_off_leaves_the_evidence_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SEMANTIC_CONTRACT_BLOCK", raising=False)
    agent = _agent()
    assert agent._with_semantic_contract("evidence", "chinook") is None


def test_enabled_block_merges_after_the_evidence(
    monkeypatch: pytest.MonkeyPatch, enabled: None
) -> None:
    document = _document()
    block, _ = sc.render_block(sc.eligible_objects(document), 2000)
    monkeypatch.setattr(
        candidates_retrieval,
        "build_semantic_contract_block",
        lambda db, settings: sc.SemanticContractBlock(
            block, sc.eligible_objects(document), len(block)
        ),
    )
    agent = _agent()
    path_state: dict = {}
    merged = agent._with_semantic_contract(
        "evidence text", "chinook", path_state=path_state
    )
    assert merged is not None
    assert merged.startswith("evidence text\n\n" + sc.BLOCK_MARKER)
    assert path_state["offered_semantic_objects"] == [
        {"id": "c1", "kind": "concept", "status": "certified"}
    ]


def test_block_already_present_is_not_duplicated(
    monkeypatch: pytest.MonkeyPatch, enabled: None
) -> None:
    document = _document()
    block, rendered = sc.render_block(sc.eligible_objects(document), 2000)
    monkeypatch.setattr(
        candidates_retrieval,
        "build_semantic_contract_block",
        lambda db, settings: sc.SemanticContractBlock(block, rendered, len(block)),
    )
    agent = _agent()
    # Evidence carries a block that really came out of render_block above.
    evidence = "evidence\n\n" + block
    assert agent._with_semantic_contract(evidence, "chinook") is None


def test_node_logs_a_warning_when_the_block_build_raises(
    monkeypatch: pytest.MonkeyPatch, enabled: None, caplog: pytest.LogCaptureFixture
) -> None:
    class _TinyModel(BaseModel):
        count: int

    try:
        _TinyModel(count="not-an-int")  # type: ignore[arg-type]
    except ValidationError as exc:
        validation_error = exc
    else:
        raise AssertionError("expected a ValidationError")

    def broken(database_name, settings):
        raise validation_error

    monkeypatch.setattr(candidates_retrieval, "build_semantic_contract_block", broken)
    agent = _agent()
    with caplog.at_level(logging.WARNING, logger="test-semantic-contract"):
        merged = agent._with_semantic_contract("evidence", "chinook")
    assert merged is None
    assert any(r.exc_info for r in caplog.records)


def test_loader_failure_leaves_the_evidence_alone(
    monkeypatch: pytest.MonkeyPatch, enabled: None
) -> None:
    def broken(database_name, settings):
        raise RuntimeError("database down")

    monkeypatch.setattr(candidates_retrieval, "build_semantic_contract_block", broken)
    agent = _agent()
    assert agent._with_semantic_contract("evidence", "chinook") is None


def test_nothing_certified_yields_none(
    monkeypatch: pytest.MonkeyPatch, enabled: None
) -> None:
    monkeypatch.setattr(
        candidates_retrieval,
        "build_semantic_contract_block",
        lambda db, settings: None,
    )
    agent = _agent()
    assert agent._with_semantic_contract("evidence", "chinook") is None
