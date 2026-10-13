import importlib.util
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def _builder_module():
    path = ROOT / "scripts" / "build_ontobricks_obx.py"
    spec = importlib.util.spec_from_file_location("build_ontobricks_obx", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_obx_is_reproducible_and_has_official_envelope_shape():
    expected = _builder_module().build_envelope()
    artifact = json.loads((ROOT / "ontology" / "quetzal-telecom-v1.obx").read_text())
    assert artifact == expected
    assert artifact["format_version"] == 1
    assert artifact["ontobricks_version"] == "0.8.1"
    domain = artifact["domains"][0]
    assert domain["name"] == "quetzal_telecom"
    version_document = domain["versions"]["1"]
    design = version_document["versions"]["1"]
    assert version_document["info"]["graph_backend"] == "databricks"
    assert version_document["info"]["lakehouse_materialization"] == "table"
    assert design["ontology"]["base_uri"] == "https://quetzal.demo/ontology/"
    assert len(design["ontology"]["classes"]) == 9
    assert len(design["assignment"]["entities"]) == 9
    assert len(design["assignment"]["relationships"]) == 11


def test_every_mapping_reads_only_the_governed_triple_table():
    artifact = json.loads((ROOT / "ontology" / "quetzal-telecom-v1.obx").read_text())
    assignment = artifact["domains"][0]["versions"]["1"]["versions"]["1"]["assignment"]
    mappings = assignment["entities"] + assignment["relationships"]
    expected_table = (
        "classic_stable_douglas_s_catalog.quetzal_telecom."
        "gold_quetzal_knowledge_graph_triples"
    )
    assert mappings
    assert all(expected_table in mapping["sql_query"] for mapping in mappings)
    assert all("LIMIT " not in mapping["sql_query"].upper() for mapping in mappings)


def test_entity_mapping_shape_is_visible_to_ontobricks_column_parser():
    artifact = json.loads((ROOT / "ontology" / "quetzal-telecom-v1.obx").read_text())
    entities = artifact["domains"][0]["versions"]["1"]["versions"]["1"]["assignment"]["entities"]
    customer = next(item for item in entities if item["ontology_class"].endswith("/Customer"))
    sql = customer["sql_query"]
    assert sql.startswith("SELECT ")
    assert "WITH typed" not in sql
    assert "AS baseline_churn_probability" in sql
    assert "AS retention_priority_score" in sql
    assert "HAVING MAX(CASE" in sql
    assert "https://quetzal.demo/ontology/Customer" in sql
    assert "https://quetzal.demo/ontology#Customer" in sql


def test_ontology_has_no_unmaterialized_campaign_semantics():
    turtle = (ROOT / "ontology" / "quetzal-telecom-v1.ttl").read_text()
    assert "qz:Campaign" not in turtle
    assert "qz:targetsCustomer" not in turtle
    assert "qz:includesProduct" not in turtle
    assert 'rdfs:label "Grafo de conocimiento Quetzal Telecom"@es' in turtle
    assert "@prefix qz: <https://quetzal.demo/ontology/>" in turtle


def test_jobs_are_manual_only():
    bundle = yaml.safe_load((ROOT / "resources" / "operations.yml").read_text())
    jobs = bundle["resources"]["jobs"]
    assert jobs
    for job in jobs.values():
        assert "schedule" not in job
        assert "trigger" not in job
        assert "continuous" not in job
    graph_job = jobs["quetzal_graph_intelligence"]
    params = graph_job["tasks"][0]["notebook_task"]["base_parameters"]
    assert params["workflow_run_id"] == "{{job.run_id}}"


def test_triple_ctes_publish_named_contract_columns():
    notebook = (ROOT / "notebooks" / "03_graph_intelligence.py").read_text()
    for marker in (
        ") , relationship_triples AS (",
        ") , business_triples AS (",
    ):
        # Ignore whitespace between ')' and ',' to keep the assertion readable.
        normalized = notebook.replace("), relationship_triples", ") , relationship_triples")
        normalized = normalized.replace("), business_triples", ") , business_triples")
        section = normalized.split(marker, 1)[1]
        first_select = section.split("UNION ALL", 1)[0]
        assert " AS subject" in first_select
        assert " AS predicate" in first_select
        assert " AS object" in first_select
        assert " AS object_is_iri" in first_select
        assert " AS datatype" in first_select
        assert " AS source_table" in first_select
