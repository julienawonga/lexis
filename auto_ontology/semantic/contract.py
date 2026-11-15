# SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
# SPDX-License-Identifier: Apache-2.0

"""Versioned, agent-neutral interchange contract for semantic knowledge.

These models describe the intended public meaning of a semantic model. They are
not the persistence schema: existing Lexis rows are not implicitly upgraded or
certified by serialising them through this contract.
"""

from __future__ import annotations

import re
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ContractModel(BaseModel):
    """Strict JSON-compatible base for all contract objects."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class KnowledgeStatus(StrEnum):
    """Epistemic or governance state; similarity rank never changes this."""

    OBSERVED = "observed"
    INFERRED = "inferred"
    DRAFT = "draft"
    IN_REVIEW = "in_review"
    CERTIFIED = "certified"
    NEEDS_REVALIDATION = "needs_revalidation"
    CONFLICTED = "conflicted"
    DEPRECATED = "deprecated"
    UNVERIFIED_LEGACY = "unverified_legacy"


class KnowledgeKind(StrEnum):
    CONCEPT = "concept"
    ATTRIBUTE = "attribute"
    RELATION = "relation"
    SQL_ATTRIBUTE = "sql_attribute"
    METRIC = "metric"
    DIMENSION = "dimension"
    VERIFIED_QUERY = "verified_query"


class SemanticLabel(ContractModel):
    """A language-tagged preferred or alternate name."""

    text: str = Field(min_length=1)
    language: str = Field(min_length=2, description="BCP 47 language tag.")
    kind: Literal["preferred", "alternate", "hidden"] = "preferred"

    @field_validator("language")
    @classmethod
    def _validate_language_tag(cls, value: str) -> str:
        if not re.fullmatch(r"[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*", value):
            raise ValueError("language must be a valid BCP 47 language tag")
        return value


class KnowledgeScope(ContractModel):
    """Where an item is visible and authoritative."""

    kind: Literal["personal", "team", "domain", "database", "shared"]
    owner_id: str | None = None
    domain_id: str | None = None
    database_id: str | None = None

    @model_validator(mode="after")
    def _require_scope_owner(self) -> KnowledgeScope:
        if self.kind in {"personal", "team"} and not self.owner_id:
            raise ValueError(f"{self.kind} scope requires owner_id")
        if self.kind == "domain" and not self.domain_id:
            raise ValueError("domain scope requires domain_id")
        if self.kind == "database" and not self.database_id:
            raise ValueError("database scope requires database_id")
        return self


class EvidenceReference(ContractModel):
    """Pointer to evidence; excerpts are intentionally not embedded by default."""

    kind: Literal[
        "schema", "document", "query", "execution", "conversation", "human_review"
    ]
    reference: str = Field(min_length=1)
    captured_at: datetime | None = None


class KnowledgeProvenance(ContractModel):
    """Who or what asserted an item and the evidence available for it."""

    actor_type: Literal["user", "agent", "system", "job"]
    actor_id: str = Field(min_length=1)
    activity: str = Field(min_length=1)
    asserted_at: datetime | None = None
    evidence: tuple[EvidenceReference, ...] = ()
    model_id: str | None = None
    prompt_version: str | None = None


class CatalogBinding(ContractModel):
    """A stable reference from a semantic object to a physical data object."""

    catalog_id: str = Field(min_length=1)
    role: str = Field(min_length=1, description="Meaning of this binding in context.")
    object_kind: Literal["database", "schema", "table", "column"] | None = None
    qualified_name: str | None = None


class SemanticObjectBase(ContractModel):
    """Shared identity and governance envelope for a semantic object."""

    id: str = Field(min_length=1, description="Stable, opaque identifier.")
    kind: KnowledgeKind
    labels: tuple[SemanticLabel, ...] = Field(min_length=1)
    definition: str = Field(min_length=1)
    status: KnowledgeStatus
    scope: KnowledgeScope
    provenance: KnowledgeProvenance
    legacy_certification: dict[str, bool] | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    supersedes: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _check_validity_and_certification(self) -> SemanticObjectBase:
        if self.valid_from and self.valid_to and self.valid_to <= self.valid_from:
            raise ValueError("valid_to must be later than valid_from")
        if self.status == KnowledgeStatus.CERTIFIED:
            if self.provenance.actor_type != "user":
                raise ValueError("certified knowledge requires a human actor")
            if not any(
                evidence.kind == "human_review" for evidence in self.provenance.evidence
            ):
                raise ValueError("certified knowledge requires human-review evidence")
        return self


class SemanticConcept(SemanticObjectBase):
    kind: Literal[KnowledgeKind.CONCEPT] = KnowledgeKind.CONCEPT
    bindings: tuple[CatalogBinding, ...] = ()


class SemanticAttribute(SemanticObjectBase):
    kind: Literal[KnowledgeKind.ATTRIBUTE] = KnowledgeKind.ATTRIBUTE
    concept_id: str = Field(min_length=1)
    bindings: tuple[CatalogBinding, ...] = ()
    datatype: str | None = None
    unit: str | None = None


class SemanticRelation(SemanticObjectBase):
    kind: Literal[KnowledgeKind.RELATION] = KnowledgeKind.RELATION
    subject_id: str = Field(min_length=1)
    predicate: str = Field(min_length=1)
    object_id: str = Field(min_length=1)
    cardinality: (
        Literal["one_to_one", "one_to_many", "many_to_one", "many_to_many"] | None
    ) = None
    join_bindings: tuple[CatalogBinding, ...] = ()


class SemanticMetric(SemanticObjectBase):
    kind: Literal[KnowledgeKind.METRIC] = KnowledgeKind.METRIC
    concept_id: str = Field(min_length=1)
    expression: str = Field(min_length=1)
    expression_language: Literal["sql"] = "sql"
    dialect: str | None = None
    grain: tuple[str, ...] = ()
    unit: str | None = None
    filters: tuple[str, ...] = ()
    dependencies: tuple[str, ...] = ()


class SemanticSqlAttribute(SemanticObjectBase):
    kind: Literal[KnowledgeKind.SQL_ATTRIBUTE] = KnowledgeKind.SQL_ATTRIBUTE
    concept_id: str = Field(min_length=1)
    expression: str | None = None
    expression_language: Literal["sql"] = "sql"
    dialect: str | None = None
    source: str | None = None


class SemanticDimension(SemanticObjectBase):
    kind: Literal[KnowledgeKind.DIMENSION] = KnowledgeKind.DIMENSION
    attribute_ids: tuple[str, ...] = Field(min_length=1)


class SemanticVerifiedQuery(SemanticObjectBase):
    kind: Literal[KnowledgeKind.VERIFIED_QUERY] = KnowledgeKind.VERIFIED_QUERY
    question: str = Field(min_length=1)
    sql: str = Field(min_length=1)
    dialect: str | None = None
    parameters: tuple[str, ...] = ()
    dependencies: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _require_execution_evidence(self) -> SemanticVerifiedQuery:
        if self.status not in {
            KnowledgeStatus.IN_REVIEW,
            KnowledgeStatus.CERTIFIED,
            KnowledgeStatus.NEEDS_REVALIDATION,
        }:
            raise ValueError(
                "verified queries must be in review, certified or marked for revalidation"
            )
        if not any(item.kind == "execution" for item in self.provenance.evidence):
            raise ValueError("verified queries require execution evidence")
        return self


SemanticObject = Annotated[
    SemanticConcept
    | SemanticAttribute
    | SemanticRelation
    | SemanticSqlAttribute
    | SemanticMetric
    | SemanticDimension
    | SemanticVerifiedQuery,
    Field(discriminator="kind"),
]


class SemanticModelDocument(ContractModel):
    """Portable semantic model document, independent of agent protocol."""

    contract_version: Literal["0.1"] = "0.1"
    model_id: str = Field(min_length=1)
    objects: tuple[SemanticObject, ...] = ()

    @model_validator(mode="after")
    def _unique_ids(self) -> SemanticModelDocument:
        ids = [obj.id for obj in self.objects]
        if len(ids) != len(set(ids)):
            raise ValueError("semantic object ids must be unique within a document")
        objects_by_id = {obj.id: obj for obj in self.objects}
        for obj in self.objects:
            if isinstance(obj, SemanticAttribute):
                self._require_kind(objects_by_id, obj.concept_id, KnowledgeKind.CONCEPT)
            elif isinstance(obj, SemanticMetric):
                self._require_kind(objects_by_id, obj.concept_id, KnowledgeKind.CONCEPT)
                self._require_references(objects_by_id, obj.dependencies)
            elif isinstance(obj, SemanticSqlAttribute):
                self._require_kind(objects_by_id, obj.concept_id, KnowledgeKind.CONCEPT)
            elif isinstance(obj, SemanticRelation):
                self._require_kind(objects_by_id, obj.subject_id, KnowledgeKind.CONCEPT)
                self._require_kind(objects_by_id, obj.object_id, KnowledgeKind.CONCEPT)
            elif isinstance(obj, SemanticDimension):
                for attribute_id in obj.attribute_ids:
                    self._require_kind(
                        objects_by_id, attribute_id, KnowledgeKind.ATTRIBUTE
                    )
            elif isinstance(obj, SemanticVerifiedQuery):
                self._require_references(objects_by_id, obj.dependencies)
        return self

    @staticmethod
    def _require_kind(
        objects_by_id: dict[str, SemanticObject],
        reference_id: str,
        expected_kind: KnowledgeKind,
    ) -> None:
        referenced = objects_by_id.get(reference_id)
        if referenced is None or referenced.kind != expected_kind:
            raise ValueError(
                f"{reference_id!r} must reference an included {expected_kind.value}"
            )

    @staticmethod
    def _require_references(
        objects_by_id: dict[str, SemanticObject], reference_ids: tuple[str, ...]
    ) -> None:
        missing = [
            reference_id
            for reference_id in reference_ids
            if reference_id not in objects_by_id
        ]
        if missing:
            raise ValueError(f"dependencies must reference included objects: {missing}")


__all__ = [
    "CatalogBinding",
    "EvidenceReference",
    "KnowledgeKind",
    "KnowledgeProvenance",
    "KnowledgeScope",
    "KnowledgeStatus",
    "SemanticAttribute",
    "SemanticConcept",
    "SemanticDimension",
    "SemanticLabel",
    "SemanticMetric",
    "SemanticModelDocument",
    "SemanticObject",
    "SemanticRelation",
    "SemanticSqlAttribute",
    "SemanticVerifiedQuery",
]
