# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Wiring tests: the certified semantic-contract block reaches the evidence."""

from __future__ import annotations

import logging

import pytest

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
    monkeypatch.setattr(
        candidates_retrieval,
        "build_semantic_contract_block",
        lambda db, settings: sc.SemanticContractBlock(
            sc.BLOCK_HEADER + " (human-reviewed; ids in parentheses):\n- concept c1",
            sc.eligible_objects(document),
            80,
        ),
    )
    agent = _agent()
    path_state: dict = {}
    merged = agent._with_semantic_contract(
        "evidence text", "chinook", path_state=path_state
    )
    assert merged is not None
    assert merged.startswith("evidence text\n\n" + sc.BLOCK_HEADER)
    assert path_state["offered_semantic_objects"] == [
        {"id": "c1", "kind": "concept", "status": "certified"}
    ]


def test_block_already_present_is_not_duplicated(
    monkeypatch: pytest.MonkeyPatch, enabled: None
) -> None:
    monkeypatch.setattr(
        candidates_retrieval,
        "build_semantic_contract_block",
        lambda db, settings: sc.SemanticContractBlock("x", (), 1),
    )
    agent = _agent()
    evidence = "evidence\n\n" + sc.BLOCK_HEADER + ":\n- concept c1"
    assert agent._with_semantic_contract(evidence, "chinook") is None


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
