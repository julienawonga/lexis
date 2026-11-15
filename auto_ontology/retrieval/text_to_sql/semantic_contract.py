# SPDX-FileCopyrightText: Copyright (c) 2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Certified semantic-contract context for the planner, or nothing.

Loads the semantic-model document for one database, keeps only the objects the
governance flow currently marks ``certified`` (the projection itself demotes
stale sources to ``needs_revalidation`` on read, so filtering on status is the
whole eligibility contract), and renders a compact prompt block. The block
carries ids, preferred names, definitions, binding qualified names and relation
directions so the planner can cite why each item applies. It never infers
metric grain or units: only concepts, attributes and relations are rendered.

Off by default; ``SEMANTIC_CONTRACT_BLOCK=1`` turns it on. The caller treats a
failure as "no block", exactly like the Terms-definitions lookup.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

from auto_ontology.semantic.contract import (
    KnowledgeKind,
    KnowledgeStatus,
    SemanticAttribute,
    SemanticConcept,
    SemanticObject,
    SemanticRelation,
    SemanticModelDocument,
)

BLOCK_HEADER = "Certified semantic definitions"
# Single marker shared by render_block and the "already present" guard so the
# two can never drift apart.
BLOCK_MARKER = f"{BLOCK_HEADER} (human-reviewed; ids in parentheses):"

_BUDGET_CHARS_ENV = "SEMANTIC_CONTRACT_BUDGET_CHARS"
_DEFAULT_BUDGET_CHARS = 2000

logger = logging.getLogger(__name__)


class UnknownDatabaseError(ValueError):
    """The catalog has no database under the requested name."""


@dataclass(frozen=True)
class SemanticContractSettings:
    """Switches and budget, read from the environment like the Terms ones."""

    enabled: bool
    budget_chars: int

    @classmethod
    def from_env(cls) -> "SemanticContractSettings":
        raw = os.environ.get(_BUDGET_CHARS_ENV)
        budget = _DEFAULT_BUDGET_CHARS
        if raw:
            try:
                parsed = int(raw)
            except ValueError:
                logger.warning(
                    "%s=%r is not an integer; using the default of %d",
                    _BUDGET_CHARS_ENV,
                    raw,
                    _DEFAULT_BUDGET_CHARS,
                )
            else:
                if parsed <= 0:
                    logger.warning(
                        "%s=%r is not a positive integer; using the default of %d",
                        _BUDGET_CHARS_ENV,
                        raw,
                        _DEFAULT_BUDGET_CHARS,
                    )
                else:
                    budget = parsed
        return cls(
            enabled=os.environ.get("SEMANTIC_CONTRACT_BLOCK", "").strip()
            in {"1", "true", "yes", "on"},
            budget_chars=budget,
        )


@dataclass(frozen=True)
class SemanticContractBlock:
    """Rendered block plus the objects behind it, for the knowledge trace."""

    block: str
    objects: tuple[SemanticObject, ...]
    chars: int


def _preferred_text(obj: SemanticObject) -> str:
    for label in obj.labels:
        if label.kind == "preferred":
            return label.text
    return obj.labels[0].text


def _qualified_names(obj: SemanticObject) -> list[str]:
    bindings: tuple[Any, ...] = ()
    if isinstance(obj, SemanticConcept | SemanticAttribute):
        bindings = obj.bindings
    elif isinstance(obj, SemanticRelation):
        bindings = obj.join_bindings
    names = [
        binding.qualified_name
        for binding in bindings
        if binding.qualified_name is not None
    ]
    return names


def _render_line(obj: SemanticObject) -> str:
    name = _preferred_text(obj)
    definition = " ".join(obj.definition.split())
    targets = ", ".join(_qualified_names(obj))
    where = f" [at {targets}]" if targets else ""
    if isinstance(obj, SemanticConcept):
        return f"- concept {obj.id} {name!r}: {definition}{where}"
    if isinstance(obj, SemanticAttribute):
        return f"- attribute {obj.id} of {obj.concept_id} {name!r}: {definition}{where}"
    if isinstance(obj, SemanticRelation):
        cardinality = f" ({obj.cardinality})" if obj.cardinality else ""
        return (
            f"- relation {obj.id}: {obj.subject_id} -{obj.predicate}-> "
            f"{obj.object_id}: {definition}{where}{cardinality}"
        )
    raise ValueError(f"kind {obj.kind} is not rendered into the planner block")


def eligible_objects(document: SemanticModelDocument) -> tuple[SemanticObject, ...]:
    """Certified, currently-true objects, in stable id order."""
    return tuple(
        obj
        for obj in sorted(document.objects, key=lambda o: o.id)
        if obj.status is KnowledgeStatus.CERTIFIED
        and obj.kind
        in {KnowledgeKind.CONCEPT, KnowledgeKind.ATTRIBUTE, KnowledgeKind.RELATION}
    )


def render_block(
    objects: tuple[SemanticObject, ...], budget_chars: int
) -> tuple[str, tuple[SemanticObject, ...]]:
    """Render lines until the budget; returns the block and what fit."""
    header = BLOCK_MARKER
    lines: list[str] = []
    rendered: list[SemanticObject] = []
    used = len(header) + 1
    for obj in objects:
        try:
            line = _render_line(obj)
        except ValueError:
            continue
        if used + len(line) + 1 > budget_chars:
            # Skip lines that do not fit; a later, shorter one still can.
            continue
        lines.append(line)
        rendered.append(obj)
        used += len(line) + 1
    if not lines:
        return "", ()
    block = header + "\n" + "\n".join(lines)
    return block, tuple(rendered)


def _default_load_document(database_name: str) -> SemanticModelDocument:
    from auto_ontology.dal import model_interchange as model_dal
    from auto_ontology.server.model_interchange import service
    from auto_ontology.server.model_interchange.schemas import ExportRequest

    database_id = model_dal.fetch_database_id_by_name(database_name)
    if database_id is None:
        raise UnknownDatabaseError(f"Catalog database {database_name!r} was not found")
    return service.export_semantic_contract(ExportRequest(databases=[database_id]))


def build_semantic_contract_block(
    database_name: str | None,
    settings: SemanticContractSettings | None = None,
    *,
    load_document: Any = None,
) -> SemanticContractBlock | None:
    """The certified block for one database, or None when nothing applies.

    ``load_document`` is injectable for tests; the default goes through the
    same projection and approved-overlay read path as ``GET /api/semantic-model``.
    """
    settings = settings or SemanticContractSettings.from_env()
    if not settings.enabled or not (database_name and database_name.strip()):
        return None
    load = load_document or _default_load_document
    try:
        document = load(database_name)
    except UnknownDatabaseError:
        # Unknown database: no block, not an error — same contract as Terms.
        return None
    objects = eligible_objects(document)
    block, rendered = render_block(objects, settings.budget_chars)
    if not block:
        return None
    return SemanticContractBlock(block, rendered, len(block))
