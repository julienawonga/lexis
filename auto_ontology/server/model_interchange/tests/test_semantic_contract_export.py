# SPDX-FileCopyrightText: Copyright (c) 2026, Julien Awonga.
# SPDX-License-Identifier: Apache-2.0

"""Tests for projecting existing Lexis models into the semantic contract."""

from __future__ import annotations

from unittest.mock import patch

from auto_ontology.semantic.contract import (
    EvidenceReference,
    KnowledgeKind,
    KnowledgeProvenance,
    KnowledgeStatus,
    SemanticConcept,
    SemanticRelation,
    SemanticSqlAttribute,
)
from auto_ontology.server.model_interchange import service
from auto_ontology.server.model_interchange.schemas import (
    ExportRequest,
    AutoOntologyModelDocument,
    ModelColumn,
    ModelColumnAttribute,
    ModelDatabase,
    ModelDataLayer,
    ModelSchema,
    ModelSemanticFk,
    ModelSemanticLayer,
    ModelSqlAttribute,
    ModelSqlAttributesBySource,
    ModelTable,
    ModelTerm,
)


def _legacy_model() -> AutoOntologyModelDocument:
    return AutoOntologyModelDocument(
        data_layer=ModelDataLayer(
            databases=[
                ModelDatabase(
                    id="db-1",
                    dialect="postgresql",
                    ontology_language="fr",
                    schemas=[
                        ModelSchema(
                            id="schema-1",
                            name="public",
                            database_name="retail",
                            tables=[
                                ModelTable(
                                    id="table-orders",
                                    name="orders",
                                    columns=[
                                        ModelColumn(
                                            id="col-customer-id", name="customer_id"
                                        ),
                                        ModelColumn(id="col-total", name="total"),
                                    ],
                                ),
                                ModelTable(
                                    id="table-customers",
                                    name="customers",
                                    columns=[ModelColumn(id="col-id", name="id")],
                                ),
                            ],
                        ),
                    ],
                ),
            ],
        ),
        semantic_layer=ModelSemanticLayer(
            terms=[
                ModelTerm(
                    id="term-orders",
                    name="Commande",
                    description="A customer order",
                    synonyms=["Achat"],
                    name_certified=True,
                    represents=["table-orders"],
                    columns_attributes=[
                        ModelColumnAttribute(
                            id="attr-total",
                            name="Total",
                            column_id="col-total",
                            certified=True,
                        ),
                    ],
                ),
                ModelTerm(
                    id="term-customers",
                    name="Client",
                    represents=["table-customers"],
                    columns_attributes=[
                        ModelColumnAttribute(
                            id="attr-customer-id",
                            name="Identifiant",
                            column_id="col-id",
                        ),
                    ],
                ),
            ],
            semantic_fks=[
                ModelSemanticFk(
                    column_id="col-customer-id",
                    column_attribute_id="attr-customer-id",
                ),
            ],
            sql_attributes=ModelSqlAttributesBySource(
                manual=[
                    ModelSqlAttribute(
                        id="sql-total",
                        name="Total net",
                        sql="SUM(total)",
                        term_id="term-orders",
                        source="manual",
                        certified=True,
                    ),
                ],
            ),
        ),
    )


def test_projection_preserves_legacy_fields_without_claiming_certification() -> None:
    with (
        patch.object(service, "_export_document", return_value=_legacy_model()),
        patch(
            "auto_ontology.server.model_interchange.service.governance_dal.current_approved_objects",
            return_value=[],
        ),
    ):
        exported = service.export_semantic_contract(ExportRequest(databases=["db-1"]))

    objects = {obj.id: obj for obj in exported.objects}
    order = objects["term-orders"]
    relation = objects["semantic-fk:col-customer-id:attr-customer-id"]
    sql_attribute = objects["sql-total"]

    assert isinstance(order, SemanticConcept)
    assert order.status is KnowledgeStatus.UNVERIFIED_LEGACY
    assert order.labels[0].language == "fr"
    assert order.labels[1].text == "Achat"
    assert order.legacy_certification == {
        "name_certified": True,
        "description_certified": False,
    }
    assert order.bindings[0].qualified_name == "retail.public.orders"
    assert isinstance(relation, SemanticRelation)
    assert relation.kind is KnowledgeKind.RELATION
    assert relation.subject_id == "term-orders"
    assert relation.object_id == "term-customers"
    assert isinstance(sql_attribute, SemanticSqlAttribute)
    assert sql_attribute.expression == "SUM(total)"
    assert sql_attribute.source == "manual"
    assert sql_attribute.legacy_certification == {"certified": True}
    assert all(
        obj.status is KnowledgeStatus.UNVERIFIED_LEGACY for obj in objects.values()
    )


def test_approved_assertion_overlays_legacy_projection() -> None:
    request = ExportRequest(databases=["db-1"])
    with patch.object(service, "_export_document", return_value=_legacy_model()):
        baseline = service.export_semantic_contract_base(request)
    legacy = next(obj for obj in baseline.objects if obj.id == "term-orders")
    approved = SemanticConcept(
        **{
            **legacy.model_dump(mode="python"),
            "definition": "Orders accepted by the business.",
            "status": KnowledgeStatus.CERTIFIED,
            "provenance": KnowledgeProvenance(
                actor_type="user",
                actor_id="reviewer-2",
                activity="semantic_review",
                evidence=(
                    EvidenceReference(kind="human_review", reference="review-1"),
                ),
            ),
        }
    )
    row = {
        "object_id": approved.id,
        "base_fingerprint": service.semantic_object_fingerprint(legacy),
        "proposed_document": approved.model_dump(mode="json"),
    }

    with (
        patch.object(service, "export_semantic_contract_base", return_value=baseline),
        patch(
            "auto_ontology.server.model_interchange.service.governance_dal.current_approved_objects",
            return_value=[row],
        ),
    ):
        exported = service.export_semantic_contract(request)

    projected = next(obj for obj in exported.objects if obj.id == approved.id)
    assert projected.status is KnowledgeStatus.CERTIFIED
    assert projected.definition == "Orders accepted by the business."


def test_catalog_drift_demotes_approved_assertion_for_revalidation() -> None:
    request = ExportRequest(databases=["db-1"])
    with patch.object(service, "_export_document", return_value=_legacy_model()):
        baseline = service.export_semantic_contract_base(request)
    legacy = next(obj for obj in baseline.objects if obj.id == "term-orders")
    approved = SemanticConcept(
        **{
            **legacy.model_dump(mode="python"),
            "status": KnowledgeStatus.CERTIFIED,
            "provenance": KnowledgeProvenance(
                actor_type="user",
                actor_id="reviewer-2",
                activity="semantic_review",
                evidence=(
                    EvidenceReference(kind="human_review", reference="review-1"),
                ),
            ),
        }
    )
    changed_legacy = legacy.model_copy(update={"definition": "Catalog changed."})
    changed_baseline = baseline.model_copy(
        update={
            "objects": tuple(
                changed_legacy if obj.id == legacy.id else obj
                for obj in baseline.objects
            ),
        }
    )
    row = {
        "object_id": approved.id,
        "base_fingerprint": service.semantic_object_fingerprint(legacy),
        "proposed_document": approved.model_dump(mode="json"),
    }

    with (
        patch.object(
            service,
            "export_semantic_contract_base",
            return_value=changed_baseline,
        ),
        patch(
            "auto_ontology.server.model_interchange.service.governance_dal.current_approved_objects",
            return_value=[row],
        ),
    ):
        exported = service.export_semantic_contract(request)

    projected = next(obj for obj in exported.objects if obj.id == approved.id)
    assert projected.status is KnowledgeStatus.NEEDS_REVALIDATION
