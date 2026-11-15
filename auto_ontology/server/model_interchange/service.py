# SPDX-FileCopyrightText: Copyright (c) 2024-2026, NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Orchestration for native Lexis and Apache Ossie model YAML export/import."""

from __future__ import annotations

import hashlib
import io
import json
import logging
import zipfile
from collections import Counter
from collections.abc import Mapping
from typing import Any

import yaml
from ossie_nvidia_auto_ontology import (
    AutoOntologyConversionError,
    convert_auto_ontology_to_ossie,
    convert_auto_ontology_to_ossie_ontology,
    convert_ossie_to_auto_ontology,
)
from pydantic import TypeAdapter, ValidationError

from auto_ontology.connectors import get_connectors
from auto_ontology.dal import model_interchange as dal
from auto_ontology.dal import semantic_governance as governance_dal
from auto_ontology.dal.connections import list_connections
from auto_ontology.server.model_interchange.embed import (
    ImportEmbedBuffer,
    flush_import_embeddings,
)
from auto_ontology.server.model_interchange.schemas import (
    ExportRequest,
    AutoOntologyModelDocument,
    ModelFormat,
)
from auto_ontology.semantic.contract import (
    CatalogBinding,
    KnowledgeProvenance,
    KnowledgeScope,
    KnowledgeStatus,
    SemanticAttribute,
    SemanticConcept,
    SemanticLabel,
    SemanticModelDocument,
    SemanticObject,
    SemanticRelation,
    SemanticSqlAttribute,
)

logger = logging.getLogger(__name__)

_AUTO_ONTOLOGY_ROOT_KEYS = frozenset(AutoOntologyModelDocument.model_fields)
# The files of an Ossie export with its ontology. The mapping references the
# other two by these names, relative to itself.
OSSIE_EXPORT_FILES = ("semantic_model.yaml", "ontology.yaml", "mapping.yaml")


def _dialect_by_database_name(*, resolve_live: bool = True) -> dict[str, str]:
    """Resolve SQL dialect strings keyed by catalog database name.

    Live connectors give the most precise dialect, but building them connects
    to every database, and one that cannot be reached would otherwise fail the
    whole export. The dialect is informational in an export, so when that
    happens the saved connection settings are used for every database instead.
    """
    dialects: dict[str, str] = {}
    connectors = []
    if resolve_live:
        try:
            connectors = get_connectors()
        except Exception as exc:
            logger.warning(
                "Could not connect to every configured database (%s); exporting "
                "dialects from the saved connection settings instead",
                exc,
            )
    for connector in connectors:
        database_name = getattr(connector, "database_name", None)
        dialect = getattr(connector, "dialect", None)
        if database_name and dialect:
            dialects[str(database_name)] = str(dialect)

    for connection in list_connections():
        database_name = str(
            connection.get("database")
            or connection.get("database_name")
            or connection.get("name")
            or "",
        )
        if not database_name or database_name in dialects:
            continue
        dialect = connection.get("dialect") or connection.get("type") or ""
        dialects[database_name] = str(dialect)
    return dialects


def detect_model_format(payload: Mapping[str, Any]) -> ModelFormat:
    """Tell an Apache Ossie document apart from a native Lexis one.

    Only a root holding Lexis's own keys is read as native. Anything
    else goes to the Ossie converter, which rejects what it cannot read; read
    as native, it would validate as an empty document, and an import with
    ``replace`` would then wipe the catalog.
    """
    if _AUTO_ONTOLOGY_ROOT_KEYS.intersection(payload):
        return ModelFormat.AUTO_ONTOLOGY
    return ModelFormat.OSSIE


def _table_id_by_column_id(document: AutoOntologyModelDocument) -> dict[str, str]:
    """Map every catalog column id to the id of the table that owns it."""
    return {
        column.id: table.id
        for database in document.data_layer.databases
        for schema in database.schemas
        for table in schema.tables
        for column in table.columns
    }


def _project_terms_onto_one_table(
    document: AutoOntologyModelDocument,
) -> AutoOntologyModelDocument:
    """Narrow every term down to a single represented table.

    An Ossie dataset is backed by exactly one table, while a Lexis term may
    represent several. Until the converter can split such a term into one
    dataset per table, the export keeps the table carrying most of the term's
    column attributes and drops the attributes belonging to the others, so
    that no field ends up referencing a column the dataset does not have.
    """
    table_of_column = _table_id_by_column_id(document)
    projected = document.model_copy(deep=True)
    for term in projected.semantic_layer.terms:
        if len(term.represents) <= 1:
            continue
        attributes_per_table = Counter(
            table_of_column.get(attribute.column_id, "")
            for attribute in term.columns_attributes
        )
        kept_table_id = max(term.represents, key=lambda t: attributes_per_table[t])
        dropped = [t for t in term.represents if t != kept_table_id]
        term.represents = [kept_table_id]
        term.columns_attributes = [
            attribute
            for attribute in term.columns_attributes
            if table_of_column.get(attribute.column_id) == kept_table_id
        ]
        logger.warning(
            "Term %r represents %d tables; exporting only table %s to Ossie "
            "and dropping %s",
            term.name,
            len(dropped) + 1,
            kept_table_id,
            ", ".join(dropped),
        )

    kept_attribute_ids = {
        attribute.id
        for term in projected.semantic_layer.terms
        for attribute in term.columns_attributes
    }
    projected.semantic_layer.semantic_fks = [
        semantic_fk
        for semantic_fk in projected.semantic_layer.semantic_fks
        if semantic_fk.column_attribute_id in kept_attribute_ids
    ]
    return projected


def _dump_yaml(document: AutoOntologyModelDocument) -> str:
    return yaml.safe_dump(
        document.model_dump(mode="python"),
        sort_keys=False,
        default_flow_style=False,
    )


def _validate_ossie_metric_names(document: AutoOntologyModelDocument) -> None:
    """Reject custom analyses that Ossie's global metric namespace cannot hold."""
    counts = Counter(
        analysis.name for analysis in document.semantic_layer.custom_analyses
    )
    duplicates = [
        f"{name!r} ({count})" for name, count in counts.items() if name and count > 1
    ]
    if duplicates:
        raise AutoOntologyConversionError(
            "Cannot export custom analyses with duplicate names as Apache Ossie "
            f"metrics: {', '.join(duplicates)}"
        )


def _export_document(
    request: ExportRequest,
    *,
    resolve_live_dialects: bool = True,
) -> AutoOntologyModelDocument:
    """Assemble the native model document for the databases *request* scopes."""
    database_ids = request.databases
    dal.validate_database_ids(database_ids)
    rows = dal.fetch_export_rows(database_ids)
    return dal.assemble_export_document(
        rows,
        dialect_by_db_name=_dialect_by_database_name(
            resolve_live=resolve_live_dialects
        ),
        sql_column_resolver=dal.make_cached_sql_column_resolver(),
    )


def export_semantic_contract_base(request: ExportRequest) -> SemanticModelDocument:
    """Project legacy catalog rows before applying governed assertions.

    Existing interchange rows do not retain enough provenance to prove their
    authorship, evidence, or certification. The projection therefore labels
    them ``unverified_legacy`` and leaves assertion time/evidence empty.
    """
    # This endpoint reads the stored catalog only. In particular, it must not
    # open connections to every external database just to recover a dialect.
    document = _export_document(request, resolve_live_dialects=False)
    tables: dict[str, tuple[str, str, str]] = {}
    table_of_column: dict[str, str] = {}
    columns: dict[str, str] = {}
    for database in document.data_layer.databases:
        for schema in database.schemas:
            for table in schema.tables:
                qualified_table = ".".join(
                    part
                    for part in (schema.database_name, schema.name, table.name)
                    if part
                )
                tables[table.id] = (
                    database.id,
                    database.dialect,
                    qualified_table,
                )
                table_of_column.update(
                    {column.id: table.id for column in table.columns}
                )
                columns.update(
                    {
                        column.id: ".".join(
                            part for part in (qualified_table, column.name) if part
                        )
                        for column in table.columns
                    }
                )

    term_databases: dict[str, set[str]] = {}
    database_languages = {
        database.id: database.ontology_language or "und"
        for database in document.data_layer.databases
    }
    term_languages: dict[str, str] = {}
    table_terms: dict[str, set[str]] = {}
    for term in document.semantic_layer.terms:
        term_databases[term.id] = {
            tables[table_id][0] for table_id in term.represents if table_id in tables
        }
        languages = {
            database_languages[database_id]
            for database_id in term_databases[term.id]
            if database_languages.get(database_id)
        }
        term_languages[term.id] = (
            next(iter(languages)) if len(languages) == 1 else "und"
        )
        for table_id in term.represents:
            table_terms.setdefault(table_id, set()).add(term.id)

    def _scope(database_ids: set[str]) -> KnowledgeScope:
        if len(database_ids) == 1:
            return KnowledgeScope(kind="database", database_id=next(iter(database_ids)))
        return KnowledgeScope(kind="shared")

    def _legacy_provenance() -> KnowledgeProvenance:
        return KnowledgeProvenance(
            actor_type="system",
            actor_id="lexis",
            activity="legacy_export",
        )

    objects: list[SemanticObject] = []
    term_by_id = {term.id: term for term in document.semantic_layer.terms}
    attribute_term: dict[str, str] = {}
    attribute_column: dict[str, str] = {}

    for term in document.semantic_layer.terms:
        language = term_languages[term.id]
        synonyms = tuple(
            synonym.strip()
            for synonym in term.synonyms
            if synonym.strip() and synonym.strip().casefold() != term.name.casefold()
        )
        objects.append(
            SemanticConcept(
                id=term.id,
                labels=(
                    SemanticLabel(text=term.name or term.id, language=language),
                    *(
                        SemanticLabel(text=synonym, language=language, kind="alternate")
                        for synonym in synonyms
                    ),
                ),
                definition=term.description or "Legacy term; no definition recorded.",
                status=KnowledgeStatus.UNVERIFIED_LEGACY,
                scope=_scope(term_databases[term.id]),
                provenance=_legacy_provenance(),
                legacy_certification={
                    "name_certified": term.name_certified,
                    "description_certified": term.description_certified,
                },
                bindings=tuple(
                    CatalogBinding(
                        catalog_id=table_id,
                        role="represents",
                        object_kind="table",
                        qualified_name=tables[table_id][2]
                        if table_id in tables
                        else None,
                    )
                    for table_id in term.represents
                ),
            )
        )
        for attribute in term.columns_attributes:
            attribute_term[attribute.id] = term.id
            attribute_column[attribute.id] = attribute.column_id
            database_ids = {
                tables[table_id][0]
                for table_id in term.represents
                if table_id in tables
            }
            objects.append(
                SemanticAttribute(
                    id=attribute.id,
                    concept_id=term.id,
                    labels=(
                        SemanticLabel(
                            text=attribute.name or attribute.id, language=language
                        ),
                    ),
                    definition=(
                        attribute.description
                        or "Legacy attribute; no definition recorded."
                    ),
                    status=KnowledgeStatus.UNVERIFIED_LEGACY,
                    scope=_scope(database_ids),
                    provenance=_legacy_provenance(),
                    legacy_certification={"certified": attribute.certified},
                    bindings=(
                        CatalogBinding(
                            catalog_id=attribute.column_id,
                            role="maps_to",
                            object_kind="column",
                            qualified_name=columns.get(attribute.column_id),
                        ),
                    )
                    if attribute.column_id
                    else (),
                )
            )

    for semantic_fk in document.semantic_layer.semantic_fks:
        target_term_id = attribute_term.get(semantic_fk.column_attribute_id)
        if not target_term_id:
            continue
        source_table_id = table_of_column.get(semantic_fk.column_id)
        source_terms = table_terms.get(source_table_id or "", set())
        # A physical source table may represent multiple concepts. Do not guess
        # which one the relationship belongs to in the portable projection.
        if len(source_terms) != 1:
            continue
        source_term_id = next(iter(source_terms))
        source_database_ids = term_databases.get(source_term_id, set())
        target_database_ids = term_databases.get(target_term_id, set())
        objects.append(
            SemanticRelation(
                id=f"semantic-fk:{semantic_fk.column_id}:{semantic_fk.column_attribute_id}",
                subject_id=source_term_id,
                predicate="references",
                object_id=target_term_id,
                labels=(
                    SemanticLabel(text="references", language="und", kind="hidden"),
                ),
                definition="Legacy semantic foreign-key relationship; unverified.",
                status=KnowledgeStatus.UNVERIFIED_LEGACY,
                scope=_scope(source_database_ids | target_database_ids),
                provenance=_legacy_provenance(),
                join_bindings=(
                    CatalogBinding(
                        catalog_id=semantic_fk.column_id,
                        role="source_column",
                        object_kind="column",
                        qualified_name=columns.get(semantic_fk.column_id),
                    ),
                    CatalogBinding(
                        catalog_id=attribute_column.get(
                            semantic_fk.column_attribute_id, ""
                        ),
                        role="target_column",
                        object_kind="column",
                        qualified_name=columns.get(
                            attribute_column.get(semantic_fk.column_attribute_id, "")
                        ),
                    ),
                )
                if attribute_column.get(semantic_fk.column_attribute_id)
                else (),
            )
        )

    for source_group in (
        document.semantic_layer.sql_attributes.manual,
        document.semantic_layer.sql_attributes.table,
        document.semantic_layer.sql_attributes.sql,
        document.semantic_layer.sql_attributes.bridge_table,
    ):
        for attribute in source_group:
            term = term_by_id.get(attribute.term_id)
            if term is None:
                continue
            database_ids = term_databases.get(term.id, set())
            dialects = {
                dialect
                for table_id in term.represents
                if table_id in tables
                if (dialect := tables[table_id][1])
            }
            objects.append(
                SemanticSqlAttribute(
                    id=attribute.id,
                    concept_id=term.id,
                    labels=(
                        SemanticLabel(
                            text=attribute.name or attribute.id,
                            language=term_languages.get(term.id, "und"),
                        ),
                    ),
                    definition=(
                        attribute.description
                        or "Legacy SQL attribute; no definition recorded."
                    ),
                    expression=attribute.sql or None,
                    dialect=next(iter(dialects)) if len(dialects) == 1 else None,
                    source=attribute.source,
                    status=KnowledgeStatus.UNVERIFIED_LEGACY,
                    scope=_scope(database_ids),
                    provenance=_legacy_provenance(),
                    legacy_certification={"certified": attribute.certified},
                )
            )

    return SemanticModelDocument(
        model_id=(
            f"lexis:{request.databases[0]}" if len(request.databases) == 1 else "lexis"
        ),
        objects=tuple(objects),
    )


def semantic_object_fingerprint(obj: SemanticObject) -> str:
    """Hash a canonical contract object for stale-proposal detection."""
    payload = json.dumps(
        obj.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def export_semantic_contract(request: ExportRequest) -> SemanticModelDocument:
    """Project catalog meaning, then overlay the latest reviewed assertions.

    Governed objects retain their exact reviewed snapshot. If the legacy
    catalog row used as their source changes afterward, the object remains
    visible but its status drops to ``needs_revalidation``.
    """
    base = export_semantic_contract_base(request)
    legacy_by_id = {obj.id: obj for obj in base.objects}
    current = list(base.objects)
    adapter = TypeAdapter(SemanticObject)
    pending: list[tuple[dict[str, Any], SemanticObject]] = []

    for row in governance_dal.current_approved_objects(base.model_id):
        try:
            obj = adapter.validate_python(row["proposed_document"])
        except (ValidationError, TypeError):
            logger.warning(
                "Skipping invalid approved semantic object %s", row.get("object_id")
            )
            continue
        legacy = legacy_by_id.get(obj.id)
        expected_fingerprint = (
            semantic_object_fingerprint(legacy) if legacy is not None else "new"
        )
        if row["base_fingerprint"] != expected_fingerprint:
            payload = obj.model_dump(mode="json")
            payload["status"] = KnowledgeStatus.NEEDS_REVALIDATION.value
            try:
                obj = adapter.validate_python(payload)
            except ValidationError:
                logger.warning(
                    "Could not mark stale semantic object %s for revalidation",
                    obj.id,
                    exc_info=True,
                )
                continue
        pending.append((row, obj))

    # New objects can depend on other approved objects. Resolve in repeated
    # passes, so row order never decides whether a valid model can be exported.
    while pending:
        deferred: list[tuple[dict[str, Any], SemanticObject]] = []
        progressed = False
        for row, obj in pending:
            replaced = False
            candidate = list(current)
            for index, existing in enumerate(candidate):
                if existing.id == obj.id:
                    candidate[index] = obj
                    replaced = True
                    break
            if not replaced:
                candidate.append(obj)
            try:
                SemanticModelDocument(model_id=base.model_id, objects=tuple(candidate))
            except ValidationError:
                deferred.append((row, obj))
                continue
            current = candidate
            progressed = True
        if not progressed:
            for row, obj in deferred:
                logger.warning(
                    "Skipping approved semantic object %s because its references "
                    "are not present in model %s",
                    obj.id,
                    base.model_id,
                )
            break
        pending = deferred

    return SemanticModelDocument(model_id=base.model_id, objects=tuple(current))


def _ossie_source(document: AutoOntologyModelDocument) -> str:
    """Return the native YAML the Ossie converter reads for *document*."""
    _validate_ossie_metric_names(document)
    return _dump_yaml(_project_terms_onto_one_table(document))


def export_model(request: ExportRequest) -> str:
    """Export the scoped model document as a YAML string in *request.format*."""
    document = _export_document(request)
    if request.format is ModelFormat.OSSIE:
        return convert_auto_ontology_to_ossie(_ossie_source(document))
    return _dump_yaml(document)


def export_ossie_documents(request: ExportRequest) -> bytes:
    """Export the scoped model as a zip of three Apache Ossie documents.

    The semantic model is the one ``export_model`` returns in the Ossie format.
    The ontology holds the terms as concepts, and the mapping populates it from
    the semantic model, referencing both by their names in the zip.
    """
    source = _ossie_source(_export_document(request))
    semantic_model_file, ontology_file, mapping_file = OSSIE_EXPORT_FILES
    ontology, mapping = convert_auto_ontology_to_ossie_ontology(
        source,
        semantic_model_iri=f"./{semantic_model_file}",
        ontology_iri=f"./{ontology_file}",
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(semantic_model_file, convert_auto_ontology_to_ossie(source))
        archive.writestr(ontology_file, ontology)
        archive.writestr(mapping_file, mapping)
    return buffer.getvalue()


def import_model(
    yaml_text: str,
    *,
    replace: bool = True,
    embed: bool = True,
) -> dict[str, Any]:
    """Validate and apply a YAML model document in either supported format."""
    payload = yaml.safe_load(yaml_text)
    if not isinstance(payload, dict):
        raise ValueError("YAML document must deserialize to a mapping")
    source_format = detect_model_format(payload)
    if source_format is ModelFormat.OSSIE:
        payload = yaml.safe_load(convert_ossie_to_auto_ontology(yaml_text))
    document = AutoOntologyModelDocument.model_validate(payload)
    embed_buffer = ImportEmbedBuffer() if embed else None
    summary = dal.apply_import_model(
        document,
        replace=replace,
        embed_buffer=embed_buffer,
    )
    summary["format"] = source_format.value
    if embed and embed_buffer is not None:
        summary["embeddings"] = flush_import_embeddings(embed_buffer)
    return summary
