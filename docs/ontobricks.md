# OntoBricks en Quetzal

Esta integración publica el snapshot de Graph Intelligence como un dominio
semántico navegable, consultable por GraphQL y disponible como herramientas
MCP. OntoBricks no vuelve a calcular churn ni sustituye los algoritmos
ponderados de Quetzal.

## Estado validado

La integración fue reconstruida y validada el 12 de octubre de 2026 sobre el
snapshot `04c290e225184d98a8b041c4f2e14316`, sin volver a ejecutar Graph
Intelligence:

| Contrato | Resultado publicado |
|---|---:|
| Dominio | `quetzal_telecom` v1 `PUBLISHED` |
| Workflow Graph Intelligence | `635974993711924` `SUCCEEDED`, sin agenda |
| Triplas de la proyección fuente | 1.571.631 |
| Build OntoBricks | `915fa736` `COMPLETED` |
| Triplas materializadas | 1.637.100 |
| Sujetos distintos | 211.985 |
| Predicados distintos | 22 |
| Clases / relaciones / atributos | 9 / 11 / 9 |
| Clientes | 60.000 |
| Contactos calificados | 72.273 |
| Grupos de relaciones | 36.303 |
| Registry | `has_graph=true` |
| GraphQL | cliente real enmascarado y cuatro señales analíticas no nulas |
| MCP | 13 herramientas, selección de dominio y `query_graphql` con datos |

El volumen materializado no tiene que ser idéntico al de la tabla fuente. El
build genera un `rdfs:label` de respaldo para toda entidad, elimina duplicados
por `SELECT DISTINCT` y materializa los nueve atributos. La aceptación se basa
en el contrato de clases, predicados y valores, no en igualdad de conteos.

## Arquitectura y responsabilidades

```text
gold_churn_predictions
silver_clientes + suscripciones + tickets + SLA + recomendaciones
CDR sintético determinístico
                         │
                         ▼
job manual quetzal_graph_intelligence
  ├─ relaciones calificadas y ponderadas
  ├─ PageRank / Personalized PageRank / Label Propagation
  ├─ features, prioridad y grupos de relación
  └─ gold_quetzal_knowledge_graph_triples
                         │
                         ▼
OBX quetzal_telecom v1 ──► OntoBricks 0.8.1
                            ├─ Delta triple store
                            ├─ UI de navegación
                            ├─ GraphQL
                            └─ MCP
```

Quetzal es responsable de la semántica de negocio y de los cálculos
ponderados. OntoBricks es responsable del registro versionado de la ontología,
la materialización semántica y las superficies de consulta. El analytics
genérico de OntoBricks permanece deshabilitado para este dominio porque una
proyección no dirigida y sin pesos perdería frecuencia, duración, recencia y
reciprocidad.

## Significado de las señales

| Señal | Algoritmo | Escala | Interpretación correcta |
|---|---|---:|---|
| Churn individual | modelo ML gobernado | 0–1 | única probabilidad de churn |
| Alcance | PageRank ponderado | 0–100 | centralidad y capacidad de alcance |
| Difusión de exposición | Personalized PageRank ponderado | 0–100 | proximidad estructural a semillas de alto riesgo |
| Exposición directa | promedio ponderado del riesgo de contactos | 0–100 | contexto de primer salto |
| Grupo de relaciones | Label Propagation ponderado | categoría | agrupación operacional, no comunidad social declarada |
| Prioridad de retención | score compuesto explicable | 0–100 | orden de trabajo, no probabilidad |

Una relación entra al grafo si cumple al menos una condición: tres llamadas,
diez minutos acumulados o reciprocidad. Además, su última actividad debe estar
dentro de 60 días. La relación indica asociación observada; no demuestra
causalidad, contagio de churn ni vínculo familiar, social o profesional.

## Artefactos versionados

- `ontology/quetzal-telecom-v1.ttl`: ontología OWL/RDFS con nueve clases,
  once relaciones y nueve atributos.
- `ontology/quetzal-telecom-v1.shacl.ttl`: límites de scores y cardinalidades
  de contacto/recomendación.
- `scripts/build_ontobricks_obx.py`: builder determinístico que verifica que el
  Turtle y el registro no diverjan.
- `ontology/quetzal-telecom-v1.obx`: paquete importable oficial, formato 1,
  compatible con OntoBricks 0.8.1.
- `scripts/ontobricks_admin.py`: importación, build, publicación y pruebas
  remotas.
- `notebooks/03_graph_intelligence.py`: productor de la tabla de triplas y del
  run log vinculado al `job.run_id`.

El OBX no contiene tokens, contraseñas ni PII. Todos sus mappings leen
exclusivamente
`classic_stable_douglas_s_catalog.quetzal_telecom.gold_quetzal_knowledge_graph_triples`.

La base URI canónica es `https://quetzal.demo/ontology/`. Los mappings aceptan
tanto esa forma como la variante histórica terminada en `#`, lo que permite
reconstruir el dominio sobre el snapshot ya publicado y mantiene compatibles
los próximos refreshes. Los SQL de entidades comienzan directamente con
`SELECT`; esto es requerido por el extractor de columnas de OntoBricks 0.8.1
para conservar `attribute_mappings` durante el build.

Para reconstruir el artefacto:

```bash
python3 scripts/build_ontobricks_obx.py
python3 scripts/build_ontobricks_obx.py --check
```

## Operación manual

No existe `schedule`, `trigger` recurrente ni job continuo para Graph
Intelligence. El flujo completo es:

1. Desplegar el DAB del Quetzal.
2. Ejecutar manualmente `[demo] Quetzal | Graph Intelligence manual`, desde el
   botón del App o con `databricks bundle run`.
3. Confirmar un snapshot `SUCCEEDED`, modelo
   `graph-intelligence-v3-ontobricks`, `triple_count > 0`, `published_at` y el
   mismo `workflow_run_id` del Workflow.
4. Importar el OBX en modo `overwrite`.
5. Cargar `quetzal_telecom` v1, ejecutar el build Databricks y esperar la tarea.
6. Persistir el dominio DRAFT para escribir `last_build` en el registry.
7. Promover `DRAFT -> IN-REVIEW -> PUBLISHED`.
8. Validar REST, estadísticas, GraphQL y MCP con datos reales.

El paso 4 al 8 está automatizado:

```bash
DATABRICKS_AUTH_STORAGE=plaintext \
python3 scripts/ontobricks_admin.py sync --profile vibe-coding

# Validación read-only posterior
DATABRICKS_AUTH_STORAGE=plaintext \
python3 scripts/ontobricks_admin.py validate --profile vibe-coding
```

La automatización usa OAuth del perfil Databricks, conserva la cookie de
sesión, cumple el doble token CSRF y no persiste credenciales. Después del
build llama `POST /domain/save-to-uc`: en OntoBricks 0.8.1 el pipeline Delta
actualiza `last_build` en la sesión, pero no lo escribe por sí solo en
`domain_versions`. Sin ese paso el grafo tendría datos y aun así aparecería
como `has_graph=false`. Un fallo de build o de persistencia interrumpe la
promoción; una versión sin datos nunca se publica.

## Endpoints de aceptación

- `GET /api/v1/health`: runtime OntoBricks saludable.
- `GET /api/v1/domains`: `quetzal_telecom` publicado y `has_graph=true`.
- `GET /api/v1/domain/versions?domain_name=quetzal_telecom`: v1 `PUBLISHED`.
- `GET /api/v1/digitaltwin/status?domain_name=quetzal_telecom`: grafo con datos.
- `GET /api/v1/digitaltwin/stats?domain_name=quetzal_telecom`: triplas,
  sujetos, predicados y tipos.
- `GET /api/v1/graphql/quetzal_telecom/schema`: SDL listo.
- `POST /api/v1/graphql/quetzal_telecom`: `customers(limit: 1)` devuelve ID,
  URI, etiqueta, churn individual, prioridad, alcance y exposición no nulos.
- MCP `/mcp`: `initialize`, `tools/list`, `select_domain(quetzal_telecom)` y
  `query_graphql` sobre el mismo cliente.
- Quetzal `GET /api/demo/preflight`: contrato Delta y runtime publicados.
- Quetzal `GET /api/graph/semantic`: clases y relaciones agregadas para el
  explorador embebido.
- Quetzal `GET /api/graph/semantic/entities`: entidades reales paginadas,
  contexto de Cliente 360, plan, SLA y oferta, con filtro territorial y
  procedencia por snapshot/predicado.
- Quetzal IQ `ontobricks_semantic_query`: herramienta MCP read-only con siete
  intenciones permitidas. El modelo nunca escribe GraphQL; el backend elige la
  consulta, limita filas e incorpora el alcance autenticado.

## Operación embebida en Quetzal

El explorador ya no termina en el diagrama de clases. Al seleccionar una clase
o una relación, Quetzal abre una lista paginada de entidades conectadas a datos
operacionales reales. Para clientes autorizados, la jornada continúa a Cliente
360, plan vigente, política SLA, recomendación/oferta y un borrador de campaña.
La campaña no se envía y siempre conserva aprobación humana.

Cada respuesta incluye dominio y versión OntoBricks, tabla de origen, run y
fecha del snapshot, algoritmo, predicados consultados y alcance territorial.
Las consultas semánticas del IQ usan el endpoint configurado por
`QUETZAL_ONTOBRICKS_MCP_URL`; en DAB corresponde a
`${var.ontobricks_mcp_url}`. Esta configuración no crea schedules ni ejecuta el
job de grafo.

## Volumen y costo

El snapshot de demo usa hasta 60.000 clientes y 300.000 eventos de llamada. La
tabla final conserva únicamente relaciones calificadas y entidades de negocio,
con una expectativa de aproximadamente 1,0–1,7 millones de triplas o 60–180 MB
comprimidos en Delta. El OBX tiene solamente metadatos y mappings, no duplica
los datos. El build OntoBricks crea una tabla Delta materializada adicional;
por eso tanto el refresh Quetzal como el build OntoBricks son manuales.

## Evidencia E2E publicada — 2026-10-12

El bundle `demo` fue desplegado después de `97` pruebas, Ruff, build de
producción del frontend y `databricks bundle validate`. El deployment
`01f1c6555d321f96b8b51e5c4475210b` quedó `SUCCEEDED`, con App `RUNNING` y
compute `ACTIVE`. El deploy no ejecutó jobs, pipelines ni un nuevo build de
OntoBricks.

- preflight remoto `READY`, incluido `graph_snapshot=READY` y
  `ontobricks=READY`;
- dominio `quetzal_telecom` v1 publicado, GraphQL disponible y `1.637.100`
  triplas materializadas;
- grafo semántico con `9` clases, `11` relaciones y `22` predicados;
- filtro BR `recommendedProduct`: `7.066` clientes; filtro `subscribedTo`:
  `9.940` clientes;
- entidad seleccionada `CLI-77976A2D002F` resuelta para el mismo Cliente 360,
  sin desvío hacia otro cliente relacionado;
- borrador de campaña abierto con `CROSS_SELL / BR / EMAIL`, sin envío ni
  creación de audiencia;
- Quetzal IQ respondió `verified` usando exclusivamente MCP OntoBricks para
  `CUSTOMER_RELATIONSHIPS`, `PLAN_ELIGIBILITY`, `SLA_CONTEXT`,
  `RECOMMENDATION_CONTEXT` y `CUSTOMER_CONTEXT`, sin búsqueda web;
- desktop y mobile `390 px` sin overflow, consola limpia, menú accesible y la
  mesa operativa preservada al pasar de grupo a red.

El snapshot continúa manual: `scheduled=false`; esta validación no disparó el
job `340986653421253` ni ninguna escritura operacional.

Los eventos CDR intermediarios y tablas `_tmp_graph_*` existen solo durante la
ejecución y se eliminan al finalizar. El run log es compacto. El deploy del DAB
no ejecuta generación, Graph Intelligence ni build OntoBricks.

## Seguridad y permisos

- La service principal de Quetzal necesita `CAN_USE` en el App OntoBricks para
  que el preflight consulte su runtime.
- Las Apps OntoBricks y MCP necesitan acceso al Warehouse, al catálogo/schema,
  al Volume de registro y al schema Lakebase configurado.
- La tabla semántica usa nombres enmascarados. No se publica PII cruda.
- El acceso operacional y territorial continúa siendo aplicado por Quetzal;
  OntoBricks no amplía permisos ni autoriza acciones de retención.
- Las clases, relaciones e intenciones aceptadas están en allowlists del
  backend. URI, predicado y GraphQL enviados por el usuario son rechazados.
- El listado operativo exige `CARE_AGENT`; las referencias permanecen
  enmascaradas hasta abrir Cliente 360 bajo el mismo contexto autenticado.

## Rebuild, rollback y troubleshooting

Rebuild seguro: ejecute nuevamente Graph Intelligence, verifique el snapshot y
repita `ontobricks_admin.py sync`. El import es idempotente sobre
`quetzal_telecom` v1 y el build solo promueve después de completar.

Rollback lógico: no ejecute un nuevo refresh; Quetzal conserva la última tabla
publicada válida hasta el commit atómico. Si el dominio OntoBricks falla, el
App sigue usando sus tablas Gold, mas el preflight marca OntoBricks como
`DEGRADED`. Para recuperar la semántica, reimporte el OBX y reconstruya v1.

Problemas comunes:

- `CSRF token missing`: haga un `GET /healthz` con la misma sesión antes del
  POST; el script ya lo hace.
- `No R2RML mapping`: regenere el OBX y confirme que las nueve entidades tienen
  `sql_query` e `id_column`.
- grafo vacío: confirme primeiro el run v3 y `triple_count > 0` en
  `ops_graph_run_log`.
- `has_graph=false` con triplas existentes: confirme que el script ejecutó
  `build:persist-registry`; no fuerce la publicación manualmente.
- menos de 22 predicados: confirme que los entity mappings no comienzan con
  CTE y que los nueve aliases analíticos aparecen en el primer `SELECT`.
- Workflow `SUCCESS` mostrado como snapshot fallido: los IDs de Databricks
  exceden 32 bits; los parámetros SQL deben enviarse como `BIGINT`, no `INT`.
- `DRAFT -> IN-REVIEW` rechazado: el build no registró `last_build`; revise la
  tarea y `POST /domain/save-to-uc` antes de promover.
- GraphQL sin schema: la versión no está `PUBLISHED` o la ontología no tiene
  clases/propiedades.
- MCP sin herramientas: valide que `mcp_enabled=true`, que existe una versión
  publicada con grafo y que el App MCP tiene acceso al App principal.
