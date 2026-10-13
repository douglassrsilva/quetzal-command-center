# Evidências textuais de execução — 2026-10-12

Este diretório registra provas textuais do App Quetzal que podem ser lidas,
comparadas e auditadas sem depender de capturas de tela. A coleta final foi
feita em `2026-10-12T19:03:21Z` no workspace FEVM da demonstração. Identidades
humanas foram substituídas por `[MASKED_DATABRICKS_ACTOR]`; nenhum token ou
segredo foi persistido.

## Resultado executivo

- App `quetzal-command-center`: `RUNNING`, compute `ACTIVE`, deployment
  `01f1c66f42181560b7e838842aad81ab` em `SUCCEEDED`.
- Preflight publicado: `READY` em Warehouse, Genie, AI Gateway, Lakebase,
  Managed Memory, AI/BI, RBAC, Graph Intelligence e OntoBricks.
- Manifesto certificado BR: `QDM-CFB18327A439`, oito etapas, dados sintéticos,
  somente leitura, sem inferência paga e sem job disparado.
- Modelos publicados: churn v3, CLV v2 e anomalia de rede v4, todos atribuídos
  a versões UC e runs MLflow reais.
- Lakeflow: job manual `62176317131697` em `SUCCESS`, update
  `e558c15d-84ef-4e2e-a82b-9ac203899787` em `COMPLETED`, com 27/27 fluxos
  Bronze, Silver e Gold concluídos.
- Genie Clientes: conversa histórica real em `COMPLETED`, statement
  `01f1bb5c-f44e-1102-a73c-24707cf65b2b` em `SUCCEEDED`, com pergunta, SQL,
  dez resultados mascarados e resposta natural preservados.
- Graph Intelligence: workflow manual `635974993711924` concluído, snapshot
  `04c290e225184d98a8b041c4f2e14316`, sem agenda.
- OntoBricks: `quetzal_telecom` v1 `PUBLISHED`, `has_graph=true`, 1.637.100
  triplas materializadas e GraphQL/MCP validados em leitura.
- Lakebase: migrações 001/002 íntegras; campanha `CMP-E8E61467CC115EDA`
  restaurada como `CANCELLED`, com duas versões imutáveis e
  `campaign_sent=false`.
- UI publicada: desktop claro/escuro e mobile 390 px, sem overflow horizontal,
  `console_errors=0` e `failed_requests=0`.
- Validação local final: 114 testes aprovados, Ruff aprovado, frontend
  compilado e DAB validado.

## Matriz de rastreabilidade

| Requisito | Fonte/comando | Evidência | Resultado | Limitação |
|---|---|---|---|---|
| App publicado | `databricks apps get quetzal-command-center` | [published-app.json](published-app.json) | RUNNING / ACTIVE / SUCCEEDED | Estado pontual da coleta |
| Dependências da demo | `GET /api/demo/preflight` | [preflight.json](preflight.json) | 9/9 READY | AI Gateway e Managed Memory verificados por configuração/metadado, sem inferência |
| Roteiro certificado | `GET /api/demo/manifest?country=BR` | [certified-demo.json](certified-demo.json) | Oito etapas e contrato de custo/segurança íntegros | Cenário sintético e determinístico |
| ML publicado | SQL statement `01f1c66d-84b0-1a47-ada0-82a70f4743bf` | [data-ml.json](data-ml.json) | Churn v3, CLV v2, rede v4 | A coleta não treinou nem pontuou modelos |
| Lakeflow executado | histórico de job run e pipeline update | [lakeflow-run.json](lakeflow-run.json) | Job `SUCCESS`, update `COMPLETED`, 27/27 fluxos | Evidência histórica; não houve rerun |
| Genie executado | histórico da conversa e query result | [genie-query.json](genie-query.json) | Pergunta, SQL, 10 resultados e resposta; statement `SUCCEEDED` | Evidência histórica; nenhuma nova consulta foi enviada |
| Grafo + OntoBricks | endpoints do App e `ontobricks_admin.py validate` | [graph-ontobricks.json](graph-ontobricks.json) | Snapshot e domínio publicados; GraphQL/MCP válidos | Associação, não causalidade |
| Lakebase/campanha | consulta SQL somente leitura | [lakebase-campaign.json](lakebase-campaign.json) | Persistência, versões, eventos e grants confirmados | Aprovação positiva remota com segundo ator não foi simulada |
| Migrações | `jobs get-run` e `jobs get-run-output` | [migration-run.json](migration-run.json) | Run manual `SUCCESS`; 001 já aplicada e 002 aplicada | Evidência histórica; não houve rerun |
| UI | Chrome headless/CDP no deployment publicado | [ui-validation.json](ui-validation.json) | Responsiva, guardrail visível, zero erros | Teste focal da campanha persistida |
| Quetzal IQ | validação E2E autenticada já autorizada | [quetzal-iq.json](quetzal-iq.json) | 3 memórias recuperadas e nova pesquisa persistida | Uma inferência ocorreu na validação histórica; não foi repetida |
| Qualidade local/DAB | pytest, Ruff, Vite e bundle validate | [local-validation.txt](local-validation.txt) | Todos aprovados | Vite alerta para chunk JS acima de 500 kB |

## Reproduzir apenas a coleta read-only

O coletor versionado imprime JSON no stdout. Ele não persiste credenciais, não
executa jobs e não chama Genie ou Quetzal IQ. `lakeflow-run.json` e
`genie-query.json` preservam históricos já concluídos e não dependem de um novo
refresh ou de uma nova pergunta:

```bash
uv run --with-requirements requirements.txt python scripts/collect_execution_evidence.py \
  --profile vibe-coding \
  --campaign-id CMP-E8E61467CC115EDA \
  --migration-run-id 396073321799068 \
  --statement-id 01f1c66d-84b0-1a47-ada0-82a70f4743bf
```

Para validar OntoBricks sem build:

```bash
uv run --with-requirements requirements.txt python scripts/ontobricks_admin.py \
  validate --profile vibe-coding
```

Consulte [limitations.md](limitations.md) antes de usar estes resultados fora
do roteiro demonstrativo.
