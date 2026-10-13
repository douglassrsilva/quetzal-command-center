#!/usr/bin/env python3
"""Build the reproducible OntoBricks OBX artifact for Quetzal Telecom.

The source of truth for business semantics is the versioned Turtle file.  This
builder keeps the OntoBricks registry document deterministic and fails if the
classes/properties described here drift from the Turtle contract.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ONTOLOGY_PATH = ROOT / "ontology" / "quetzal-telecom-v1.ttl"
OUTPUT_PATH = ROOT / "ontology" / "quetzal-telecom-v1.obx"

BASE = "https://quetzal.demo/ontology/"
LEGACY_BASE = "https://quetzal.demo/ontology#"
RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
RDFS_LABEL = "http://www.w3.org/2000/01/rdf-schema#label"
TABLE = "classic_stable_douglas_s_catalog.quetzal_telecom.gold_quetzal_knowledge_graph_triples"
ONTOBRICKS_VERSION = "0.8.1"


CLASS_SPECS = [
    ("Customer", "Cliente", "Suscriptor con identidad enmascarada.", "👤"),
    ("QualifiedContact", "Contacto calificado", "Relación observada, calificada y auditable.", "🔗"),
    ("RelationshipGroup", "Grupo de relaciones", "Agrupación algorítmica de clientes conectados.", "🕸️"),
    ("Country", "País", "País de operación del cliente.", "🌎"),
    ("Plan", "Plan", "Plan de telecomunicaciones contratado.", "📱"),
    ("Product", "Producto", "Producto elegible para recomendación.", "📦"),
    ("Ticket", "Ticket de atención", "Caso de atención abierto.", "🎧"),
    ("SLA", "Compromiso de SLA", "Política de nivel de servicio aplicable.", "⏱️"),
    ("Recommendation", "Recomendación", "Acción o producto sugerido para el cliente.", "💡"),
]

DATATYPE_SPECS = [
    ("baselineChurnProbability", "probabilidad individual de churn", "Customer", "double"),
    ("retentionPriorityScore", "prioridad de retención", "Customer", "double"),
    ("networkReachScore", "alcance en la red", "Customer", "double"),
    ("networkExposureScore", "exposición relacional", "Customer", "double"),
    ("callCount", "cantidad de llamadas", "QualifiedContact", "long"),
    ("contactMinutes", "minutos de contacto", "QualifiedContact", "double"),
    ("relationshipWeight", "peso de la relación", "QualifiedContact", "double"),
    ("isReciprocal", "es recíproca", "QualifiedContact", "boolean"),
    ("qualificationReason", "motivo de calificación", "QualifiedContact", "string"),
]

RELATIONSHIP_SPECS = [
    ("qualifiedContact", "tiene contacto calificado", "Customer", "Customer"),
    ("contactSource", "cliente de origen", "QualifiedContact", "Customer"),
    ("contactTarget", "cliente de destino", "QualifiedContact", "Customer"),
    ("locatedIn", "se encuentra en", "Customer", "Country"),
    ("memberOfRelationshipGroup", "pertenece al grupo de relaciones", "Customer", "RelationshipGroup"),
    ("subscribedTo", "suscrito al plan", "Customer", "Plan"),
    ("openedBy", "abierto por", "Ticket", "Customer"),
    ("governedBySLA", "regido por SLA", "Customer", "SLA"),
    ("proposedFor", "propuesta para", "Recommendation", "Customer"),
    ("recommendsProduct", "recomienda producto", "Recommendation", "Product"),
    ("recommendedProduct", "producto recomendado", "Customer", "Product"),
]


def _data_property(name: str, label: str) -> dict:
    return {"name": name, "localName": name, "label": label, "uri": f"{BASE}{name}"}


def _classes() -> list[dict]:
    by_domain: dict[str, list[dict]] = {}
    for name, label, domain, _datatype in DATATYPE_SPECS:
        by_domain.setdefault(domain, []).append(_data_property(name, label))
    return [
        {
            "uri": f"{BASE}{name}",
            "name": name,
            "label": label,
            "comment": comment,
            "emoji": emoji,
            "parent": "",
            "group": "",
            "dashboard": "",
            "dashboardParams": {},
            "bridges": [],
            "dataset": None,
            "actions": [],
            "virtualAttributes": [],
            "dataProperties": by_domain.get(name, []),
        }
        for name, label, comment, emoji in CLASS_SPECS
    ]


def _properties() -> list[dict]:
    object_properties = [
        {
            "uri": f"{BASE}{name}",
            "name": name,
            "label": label,
            "comment": "",
            "type": "ObjectProperty",
            "domain": source,
            "range": target,
        }
        for name, label, source, target in RELATIONSHIP_SPECS
    ]
    datatype_properties = [
        {
            "uri": f"{BASE}{name}",
            "name": name,
            "label": label,
            "comment": "",
            "type": "DatatypeProperty",
            "domain": domain,
            "range": f"xsd:{datatype}",
        }
        for name, label, domain, datatype in DATATYPE_SPECS
    ]
    return object_properties + datatype_properties


def _entity_query(class_name: str, attributes: list[tuple[str, str, str]]) -> str:
    projections = []
    for predicate, column, sql_type in attributes:
        projections.append(
            "TRY_CAST(MAX(CASE WHEN predicate IN "
            f"('{BASE}{predicate}', '{LEGACY_BASE}{predicate}') THEN object END) "
            f"AS {sql_type}) AS {column}"
        )
    extra = ",\n       " + ",\n       ".join(projections) if projections else ""
    return (
        "SELECT regexp_extract(subject, '.*/([^/]+)$', 1) AS ID,\n"
        "       COALESCE(MAX(CASE WHEN predicate = "
        f"'{RDFS_LABEL}' THEN object END), regexp_extract(subject, '.*/([^/]+)$', 1)) AS Label"
        f"{extra}\n"
        f"FROM {TABLE}\n"
        "GROUP BY subject\n"
        "HAVING MAX(CASE WHEN predicate = "
        f"'{RDF_TYPE}' AND object IN ('{BASE}{class_name}', '{LEGACY_BASE}{class_name}') "
        "THEN 1 ELSE 0 END) = 1"
    )


def _entity_mappings() -> list[dict]:
    attributes = {
        "Customer": [
            ("baselineChurnProbability", "baseline_churn_probability", "DOUBLE"),
            ("retentionPriorityScore", "retention_priority_score", "DOUBLE"),
            ("networkReachScore", "network_reach_score", "DOUBLE"),
            ("networkExposureScore", "network_exposure_score", "DOUBLE"),
        ],
        "QualifiedContact": [
            ("callCount", "call_count", "BIGINT"),
            ("contactMinutes", "contact_minutes", "DOUBLE"),
            ("relationshipWeight", "relationship_weight", "DOUBLE"),
            ("isReciprocal", "is_reciprocal", "BOOLEAN"),
            ("qualificationReason", "qualification_reason", "STRING"),
        ],
    }
    attribute_columns = {
        "Customer": {
            "baselineChurnProbability": "baseline_churn_probability",
            "retentionPriorityScore": "retention_priority_score",
            "networkReachScore": "network_reach_score",
            "networkExposureScore": "network_exposure_score",
        },
        "QualifiedContact": {
            "callCount": "call_count",
            "contactMinutes": "contact_minutes",
            "relationshipWeight": "relationship_weight",
            "isReciprocal": "is_reciprocal",
            "qualificationReason": "qualification_reason",
        },
    }
    mappings = []
    for name, label, _comment, _emoji in CLASS_SPECS:
        mappings.append(
            {
                "ontology_class": f"{BASE}{name}",
                "ontology_class_label": name,
                "sql_query": _entity_query(name, attributes.get(name, [])),
                "id_column": "ID",
                "label_column": "Label",
                "catalog": "classic_stable_douglas_s_catalog",
                "schema": "quetzal_telecom",
                "table": "gold_quetzal_knowledge_graph_triples",
                "attribute_mappings": attribute_columns.get(name, {}),
                "excluded_attributes": [],
                "description": label,
            }
        )
    return mappings


def _relationship_mappings() -> list[dict]:
    mappings = []
    for name, label, source, target in RELATIONSHIP_SPECS:
        query = (
            "SELECT regexp_extract(subject, '.*/([^/]+)$', 1) AS source_id,\n"
            "       regexp_extract(object, '.*/([^/]+)$', 1) AS target_id\n"
            f"FROM {TABLE}\n"
            f"WHERE predicate IN ('{BASE}{name}', '{LEGACY_BASE}{name}') "
            "AND object_is_iri = true"
        )
        mappings.append(
            {
                "property": f"{BASE}{name}",
                "property_label": label,
                "sql_query": query,
                "source_class": f"{BASE}{source}",
                "source_class_label": source,
                "target_class": f"{BASE}{target}",
                "target_class_label": target,
                "source_id_column": "source_id",
                "target_id_column": "target_id",
                "direction": "forward",
                "attribute_mappings": {},
            }
        )
    return mappings


def _verify_turtle_contract() -> None:
    text = ONTOLOGY_PATH.read_text(encoding="utf-8")
    declared_classes = set(re.findall(r"qz:([A-Za-z0-9_]+)\s+a\s+owl:Class", text))
    declared_objects = set(
        re.findall(r"qz:([A-Za-z0-9_]+)\s+a\s+owl:ObjectProperty", text)
    )
    declared_datatypes = set(
        re.findall(r"qz:([A-Za-z0-9_]+)\s+a\s+owl:DatatypeProperty", text)
    )
    expected_classes = {row[0] for row in CLASS_SPECS}
    expected_objects = {row[0] for row in RELATIONSHIP_SPECS}
    expected_datatypes = {row[0] for row in DATATYPE_SPECS}
    differences = {
        "classes": (declared_classes, expected_classes),
        "object properties": (declared_objects, expected_objects),
        "datatype properties": (declared_datatypes, expected_datatypes),
    }
    errors = [
        f"{kind}: Turtle={sorted(actual)} builder={sorted(expected)}"
        for kind, (actual, expected) in differences.items()
        if actual != expected
    ]
    if errors:
        raise SystemExit("Ontology/OBX contract drift:\n" + "\n".join(errors))


def build_envelope() -> dict:
    _verify_turtle_contract()
    info = {
        "name": "Quetzal Telecom",
        "description": "Grafo semántico gobernado para inteligencia de clientes y retención en telecomunicaciones.",
        "author": "Quetzal",
        "llm_endpoint": "",
        "mcp_enabled": True,
        "status": "DRAFT",
        "review_quorum": 1,
        "mcp_policy": {},
        "graph_backend": "databricks",
        "neo4j_connection": "",
        "lakehouse_materialization": "table",
        "last_update": "",
        "last_build": "",
    }
    ontology = {
        "name": "Quetzal Telecom",
        "base_uri": BASE,
        "base_uri_auto": False,
        "description": info["description"],
        "classes": _classes(),
        "properties": _properties(),
        "constraints": [{"type": "symmetric", "property": "qualifiedContact", "propertyUri": f"{BASE}qualifiedContact"}],
        "shacl_shapes": [],
        "swrl_rules": [],
        "decision_tables": [],
        "sparql_rules": [],
        "aggregate_rules": [],
        "cohort_rules": [],
        "axioms": [],
        "expressions": [],
        "groups": [],
    }
    version_payload = {
        "info": info,
        "versions": {
            "1": {
                "ontology": ontology,
                "assignment": {
                    "entities": _entity_mappings(),
                    "relationships": _relationship_mappings(),
                },
                "design_layout": {"current_view": "default", "views": {}, "map": {}},
            }
        },
    }
    return {
        "format_version": 1,
        "ontobricks_version": ONTOBRICKS_VERSION,
        "min_ontobricks_version": ONTOBRICKS_VERSION,
        "exported_at": "2026-10-11T00:00:00Z",
        "exported_by": "quetzal-dab",
        "domains": [
            {
                "name": "quetzal_telecom",
                "info": info,
                "versions": {"1": version_payload},
            }
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    parser.add_argument("--check", action="store_true", help="Fail if the generated artifact differs from disk.")
    args = parser.parse_args()
    rendered = json.dumps(build_envelope(), ensure_ascii=False, indent=2) + "\n"
    if args.check:
        existing = args.output.read_text(encoding="utf-8") if args.output.exists() else ""
        if existing != rendered:
            raise SystemExit(f"{args.output} is stale; run scripts/build_ontobricks_obx.py")
        print(f"OK: {args.output}")
        return
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8")
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
