# Quetzal + OntoBricks

El contrato de integración es la tabla Unity Catalog
`gold_quetzal_knowledge_graph_triples`. `subject`, `predicate` y `object`
forman el contrato RDF; las demás columnas preservan tipo, linaje, ejecución y
fecha de generación.

Archivos:

- `quetzal-telecom-v1.ttl`: ontología gobernada en español.
- `quetzal-telecom-v1.shacl.ttl`: reglas de calidad y cardinalidad.
- `quetzal-telecom-v1.obx`: dominio y mappings reproducibles para OntoBricks
  0.8.1.

El OBX se regenera con `python3 scripts/build_ontobricks_obx.py`. El snapshot de
datos se genera únicamente con el job manual DAB
`quetzal_graph_intelligence`. OntoBricks aporta semántica, navegación,
validación, GraphQL y MCP; no sustituye PageRank ponderado, Personalized
PageRank ni las reglas de negocio de Quetzal.

La guía completa de operación, volumen, seguridad, rollback y troubleshooting
está en [`docs/ontobricks.md`](../docs/ontobricks.md).
