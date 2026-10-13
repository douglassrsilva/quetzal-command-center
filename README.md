# Quetzal Command Center

Centro de comando operacional para uma empresa de telecomunicações presente em 12 mercados da América Latina. O Quetzal conecta sinais de rede, impacto no cliente, risco financeiro e decisões humanas em uma única experiência, com a proposta de marca **conexão sem fronteiras**.

## O que o produto entrega

- centro de mando com KPIs, incidentes prioritários, valor em risco e frescor dos dados;
- gestão de incidentes com severidade, estado, RCA baseada em evidências e nível de confiança;
- navegação de topologia por continente, país, cidade e torre;
- impacto por cliente, receita e churn, com identificadores mascarados;
- cuidado proativo e fila de ações com aprovação ou rejeição humana;
- execução idempotente por conectores CRM, BSS, OSS ou fila interna, com evidência por tentativa;
- simulação de capacidade por mercado;
- motor de alertas sob demanda pelo botão da aplicação, com deduplicação, acuse e trilha de auditoria;
- RBAC com alcance territorial e segregação entre solicitante e aprovador;
- SLA efetivo por contrato/segmento, relógio de incidente e crédito estimado;
- ciclo fechado de recomendações com decisão, conversão e resultado;
- Quetzal IQ para investigação assistida com ferramentas internas governadas;
- continuidade conversacional com histórico recuperável no Lakebase e memória semântica por usuário no Managed Agent Memory;
- Graph Intelligence sob demanda com 300 mil chamadas sintéticas, relações qualificadas e ponderadas, alcance, exposição relacional e grafo interativo no Cliente 360;
- integração OntoBricks por ontologia OWL/RDFS versionada e tabela Delta de triplas compatível com GraphQL/MCP;
- mesa operacional por grupo com clientes paginados, churn individual, alcance, NPS, SLA, plano atual, próxima melhor ação, ofertas elegíveis e playbooks;
- três espaços Genie versionados para receita, clientes e rede;
- tema claro/escuro e experiência responsiva para desktop e mobile.
- rota de decisão guiada que conecta preflight, incidente, grafo, Cliente 360, inteligência, Voz do Cliente, campanha e fechamento econômico;
- linha do tempo unificada e explicabilidade que separam churn individual, exposição relacional, alcance e prioridade de retenção;
- jornada econômica contrafactual reconciliada com a audiência exata da campanha, incluindo custos, ROI, sensibilidade e break-even sem apresentar estimativas como resultados observados;
- preflight manual de Warehouse, Genie, Quetzal IQ, Lakebase, Agent Memory, AI/BI, RBAC e grafo, sem inferência paga ou execução de jobs.
- Voz do Cliente baseada em regras sobre tickets, NPS e SLA, com temas, evidências e clientes afetados sem simular transcrições;
- Optimizador de campanhas read-only com consentimento, alcance do canal, serviço antes da venda, orçamento, capacidade e aprovação humana;

## Arquitetura

```text
React + TypeScript (frontend/dist)
              |
FastAPI (app.py + server/)
       |             |                 |                 |
Databricks SQL    Genie API     Unity AI Gateway    Lakebase LTAP
       |                                      
Unity Catalog: dados + estado Delta + triplas OntoBricks + Managed Agent Memory
```

O backend usa as credenciais gerenciadas do Databricks App. Tokens OAuth não são persistidos nem armazenados em cache. A identidade do usuário vem exclusivamente dos headers verificados pelo proxy do Databricks Apps; papéis e países são resolvidos na tabela governada de RBAC. As consultas à plataforma ainda usam a service principal do App, portanto filtros territoriais são aplicados pelo backend e serviços upstream que não conseguem comprová-los, como Genie e o dashboard global, falham fechados para perfis territoriais. Consultas internas do Quetzal IQ passam pela ferramenta curada `telecom_snapshot`; o modelo não recebe acesso a SQL arbitrário.

### Memória do Quetzal IQ

- O Lakebase é o ledger recuperável de curto prazo: conversas, turnos, fontes e ferramentas. Reabrir uma conversa restaura esse histórico exato.
- O Managed Agent Memory guarda somente sínteses de pesquisas externas que realmente usaram `web_search`. Métricas internas, segredos e identidade enviada pelo modelo não são persistidos nele.
- O escopo é sempre derivado do usuário autenticado pelo proxy (`user:<email>`). O corpo da requisição e o modelo não podem selecionar outro escopo. Essa partição não substitui autorização: a service principal do App é o único runtime com `READ_MEMORY_STORE` e `WRITE_MEMORY_STORE`, e o backend impõe o isolamento por usuário.
- O recall é BM25 e consulta até seis candidatos, remove duplicatas e descarta artefatos incompletos de tool calling. A pergunta é gravada também na descrição para melhorar a recuperação por assunto.
- A resposta separa resultados independentes: `recalled`/`recalled_count` informam o contexto recuperado e `persisted` informa se a pesquisa atual foi salva. A UI mostra **Memoria recuperada** e **Memoria guardada** sem confundir os dois eventos.
- Memória recuperada é contexto histórico, não evidência factual atual. Quando necessário, o agente volta a pesquisar e apresenta as fontes atuais separadamente.
- O provisionamento e as migrações continuam exclusivamente manuais; abrir o chat, o preflight ou a demo não executa jobs.

### Componentes principais

- `frontend/src/`: aplicação React, componentes, contratos de API e design system.
- `frontend/dist/`: artefato estático servido pelo FastAPI.
- `app.py`: composição da API, Genie, Quetzal IQ e frontend.
- `server/operations.py`: incidentes, impacto, topologia, ações, cenários, alertas e governança.
- `server/platform.py`: autenticação, SQL parametrizado, timeout, cache TTL e chamadas à plataforma.
- `server/models.py`: contratos Pydantic estritos das entradas públicas.
- `server/memory.py`: ledger de sessões, mensagens, fontes e ferramentas no Lakebase.
- `server/managed_memory.py`: lembranças semânticas por escopo autenticado no Managed Agent Memory.
- `genie_spaces/`: configurações exportadas e versionadas dos espaços Genie.
- `dashboards/`: definição versionada do painel executivo AI/BI.
- `notebooks/00_bootstrap_operational.py`: criação idempotente do estado operacional e grants.
- `notebooks/03_graph_intelligence.py`: snapshot relacional ponderado, sinais separados, prioridade operacional e exportação de triplas.
- `notebooks/synthetic_data/`: gerador original recuperado, parametrizado e separado do scoring de modelos.
- `lakeflow/`: fontes reais Bronze, Silver e Gold do Lakeflow Declarative Pipeline.
- `ml/`: treinamento, avaliação, registro UC e scoring versionados para churn, anomalias e CLV.
- `ontology/`: ontologia telecom versionada e contrato de integração OntoBricks.
- `resources/`: recursos declarativos do Databricks Asset Bundle.
- `docs/data-ml-contract.md`: datasets, label, horizonte, features, limitações e operação manual.
- `docs/ontobricks.md`: arquitetura semântica, OBX, publicação, GraphQL/MCP, custo, rollback e troubleshooting.
- `tests/`: contratos, segurança, cache e integração governada.

## Dependências de plataforma

O bundle cria ou atualiza o Databricks App, o dashboard AI/BI, os três espaços Genie, o pipeline Lakeflow e os jobs manuais operacionais, sintéticos e de ML. O deploy só configura recursos; não executa pipelines, treinamento ou scoring. Os seguintes recursos são dependências externas e são recebidos como variáveis do bundle:

- catálogo e schema com as tabelas analíticas de telecom;
- SQL Warehouse serverless;
- Unity AI Gateway model service do Quetzal IQ;
- workspace de destino e permissões do usuário que executa o deploy.
- projeto Lakebase Autoscaling, branch, endpoint e role proprietária recebidos como variáveis;
- URLs opcionais dos conectores CRM, OSS e BSS; sem elas, ações entram na fila interna auditável.
- App OntoBricks implantado separadamente e recebido por URL; sem ele, a ontologia e o contrato Lakehouse continuam funcionais, mas o preflight marca o runtime semântico como degradado.

As tabelas operacionais de incidentes, ações, tentativas, alertas, RBAC, SLA, recomendações e auditoria são provisionadas pelo bootstrap. O notebook descobre a service principal pelo nome do App e aplica os grants necessários, evitando IDs fixos entre ambientes.

Voz do Cliente e Optimizador de campanhas não exigem novas tabelas ou jobs. Os endpoints leem as fontes governadas existentes no Unity Catalog e constroem respostas determinísticas e limitadas. O optimizador retorna somente um `DRAFT`: não executa `INSERT`/`UPDATE`, não chama conectores e não envia comunicação.

O próprio `DRAFT` é o contrato da jornada econômica. A resposta identifica a população selecionada e uma huella determinística dos clientes, calcula benefício, custo de contato, impacto líquido, ROI, sensibilidade e taxa de resposta de equilíbrio sobre essa mesma audiência. O App rejeita a reconciliação visual quando mercado, tema de Voz do Cliente ou objetivo não correspondem. A probabilidade de churn mantém seu horizonte preditivo de 30 dias, separado do horizonte comercial em meses; custos de desconto, impostos, fulfillment, mão de obra adicional, canibalização e resposta competitiva são explicitamente excluídos. ROI negativo e break-even indisponível permanecem visíveis.

## Semântica governada

- receita: últimos 12 meses fechados;
- assinantes, ARPU, cobrança e satisfação: último mês fechado;
- rede: último snapshot horário disponível;
- churn e CLV: última execução de scoring;
- `network.health_score` e `uptime_pct`: percentual de medições sem alerta, nunca disponibilidade contratual ou SLA;
- churn previsto e churn observado são conceitos distintos;
- `synthetic_churn_propensity` é uma regra demonstrativa; `churn_risk_score` é somente seu alias legado e nenhum dos dois é probabilidade ML;
- `churn_probability` é produzido exclusivamente pelo modelo registrado e cada saída grava versão, run do MLflow e horizonte futuro de 30 dias da demo;
- PageRank ponderado mede alcance, não churn; Personalized PageRank mede difusão de exposição, não probabilidade ou causalidade;
- `retention_priority_score` é um ranking operacional 0–100 e nunca substitui `churn_probability`;
- dados sintéticos são identificados e PII não deve ser exposta.
- os temas de Voz do Cliente são classificações por regras de categoria e motivo, não sentimento inferido nem transcrição;
- estimativas de conversão, retenção e receita de campanha são contrafactuais, não causais ou garantidas.

A aplicação mostra o frescor por domínio. Um estado `stale` descreve a origem dos dados e não uma falha técnica do App.

## Desenvolvimento local

Pré-requisitos: Python 3.11+, Node.js/npm, Databricks CLI e um perfil autenticado.

```bash
export QUETZAL_RUNTIME=local
export QUETZAL_LOCAL_MODE=true
export QUETZAL_LOCAL_ACTOR=developer@example.com
export QUETZAL_LOCAL_ROLES=ADMIN,NOC_OPERATOR,ACTION_APPROVER,CARE_AGENT,EXECUTIVE_VIEWER
# Opcional; vazio significa todos os mercados no modo local controlado.
export QUETZAL_LOCAL_COUNTRIES=BR

cd frontend
npm ci
npm run build
cd ..
uv run --with-requirements requirements.txt uvicorn app:app --host 127.0.0.1 --port 8000
```

O modo local precisa ser ativado explicitamente e nunca é aceito quando `QUETZAL_RUNTIME=published`, `QUETZAL_RUNTIME=production` ou `DATABRICKS_APP_NAME` está presente. Sem identidade válida, a API publicada retorna `401`; sem papel ativo, retorna `403` antes de consultar dados. Para chamadas reais, configure autenticação Databricks válida e as variáveis listadas em `resources/app.yml`. `app.yaml` permanece apenas como compatibilidade local; o bundle é a fonte de verdade do deployment.

## Deploy reproduzível com DAB

O target `dev` cria um App isolado por padrão. O target `demo` atualiza o App publicado `quetzal-command-center`.

```bash
cd frontend
npm ci
npm run build
cd ..

databricks bundle validate -t demo --profile <perfil>
databricks bundle deploy -t demo --profile <perfil>
databricks bundle run -t demo quetzal_operational_bootstrap --profile <perfil>
databricks bundle run -t demo quetzal_memory_foundation --profile <perfil>
databricks bundle run -t demo quetzal_lakebase_migrate --profile <perfil>
databricks bundle run -t demo quetzal_alert_evaluator --profile <perfil>
# Somente quando um administrador solicitar um novo snapshot:
databricks bundle run -t demo quetzal_graph_intelligence --profile <perfil>
```

Os recursos de dados e ML também são exclusivamente manuais e podem sobrescrever o landing ou tabelas de scoring. Eles não fazem parte do deploy nem de um smoke test comum:

```bash
# Executar somente após revisão explícita de custo e impacto:
databricks bundle run -t demo quetzal_synthetic_data_generation --profile <perfil>
databricks bundle run -t demo quetzal_lakeflow_refresh --profile <perfil>
databricks bundle run -t demo quetzal_ml_refresh --profile <perfil>
```

O refresh Lakeflow é um full refresh intencional: o gerador sobrescreve o landing Parquet, então os checkpoints do Auto Loader precisam ser reiniciados para reconstruir Bronze, Silver e Gold de forma determinística. Nada disso possui agenda.

O contrato completo, inclusive a limitação do label de churn no mesmo snapshot e o caminho para um horizonte temporal de produção, está em [docs/data-ml-contract.md](docs/data-ml-contract.md).

O workflow transacional de retenção, seus estados, controles de idempotência/concorrência e migração manual estão em [docs/lakebase-retention.md](docs/lakebase-retention.md).

O ciclo persistente de campanhas, suas versões imutáveis, segregação de aprovação, auditoria e limite explícito de não envio estão em [docs/lakebase-campaigns.md](docs/lakebase-campaigns.md).

Os jobs de memória, alertas e Graph Intelligence não possuem `schedule` ou `trigger`; são executados somente sob demanda. Graph Intelligence usa `max_concurrent_runs: 1`, prepara o snapshot em tabelas intermediárias e só publica após validar os volumes. O banco físico `quetzal` isola o histórico dentro de um projeto Lakebase Autoscaling compartilhado, com scale-to-zero. Ao promover para outro workspace, informe `lakebase_app_principal` com o `service_principal_client_id` retornado por `databricks apps get <app>`; o job de memória descobre o mesmo App e aplica os privilégios `READ/WRITE MEMORY STORE` de menor privilégio.

No explorador, “grupos de relacionamento” é a linguagem de negócio para as comunidades detectadas pelo algoritmo. O identificador `COM-*` permanece apenas como referência técnica. Selecionar um grupo carrega automaticamente `GET /api/graph/communities/{community_id}/operational`, que recalcula todos os agregados sobre os clientes visíveis ao operador, respeita seu escopo territorial e só retorna ofertas com consentimento comercial. O drill-down da rede continua disponível como análise secundária; a jornada principal termina no Cliente 360 individual.

### Relações qualificadas e OntoBricks

O pipeline alvo `graph-intelligence-v3-ontobricks` não transforma uma chamada isolada em relacionamento. Um par só entra no grafo quando possui pelo menos 3 chamadas, 10 minutos acumulados ou reciprocidade, e sua última atividade ocorreu nos últimos 60 dias. O peso combina recorrência e duração logarítmicas, recência e reciprocidade. Na demonstração, `FREQUENT` significa somente contato recorrente; o App não afirma vínculo familiar, social ou profissional sem evidência cadastral.

O modelo individual continua sendo a única fonte da probabilidade de churn. A rede produz quatro sinais separados: exposição direta por risco ponderado dos contatos, difusão por Personalized PageRank, alcance por PageRank ponderado e grupo por Label Propagation ponderado. A prioridade de retenção combina esses sinais para ordenar trabalho, sem se apresentar como probabilidade.

O mesmo refresh publica `gold_quetzal_knowledge_graph_triples` com `subject`, `predicate` e `object`, além de tipo, linhagem e execução. A ontologia, o SHACL e o OBX reproduzível ficam em `ontology/`; `scripts/ontobricks_admin.py` automatiza import, build, promoção, GraphQL e MCP. Para 60 mil clientes e o volume qualificado esperado, a projeção é de aproximadamente 1,0–1,7 milhão de triplas e 60–180 MB comprimidos em Delta; `/api/graph/methodology` e o preflight reportam o volume real após a execução. O analytics genérico do OntoBricks não substitui o pipeline ponderado porque sua projeção padrão deduplica arestas como não direcionadas e sem peso. Consulte [docs/ontobricks.md](docs/ontobricks.md).

O Cliente 360 expõe a versão e os critérios do snapshot. Se um ambiente ainda publicar `graph-fusion-v1`, a interface o identifica como anterior e informa que a política v3 depende da próxima atualização manual. Fazer deploy do bundle nunca executa esse processamento caro.

O grafo semântico embutido agora é operacional: classe ou relação abre
entidades paginadas e territorialmente filtradas, com navegação para Cliente
360, plano, SLA, oferta e rascunho de campanha. A procedência apresenta
algoritmo, snapshot e predicados. Perguntas relacionais do Quetzal IQ usam uma
ferramenta OntoBricks MCP de intenções restritas; o modelo não recebe acesso a
GraphQL arbitrário. O endpoint MCP também é variável DAB
`ontobricks_mcp_url`, portanto a promoção entre ambientes não exige editar o
código.

Para outro workspace ou ambiente, sobrescreva variáveis sem editar o código:

```bash
databricks bundle deploy -t dev --profile <perfil> \
  --var="app_name=quetzal-command-center-dev,catalog=<catalogo>,schema=<schema>,sql_warehouse_id=<warehouse>"
```

Os IDs usados pelo App para os espaços Genie vêm das referências de recursos do próprio bundle. Nunca faça do sync manual a etapa final de uma entrega.

## Validação

O deck executivo anexável e editável, com problema telecom, valor de negócio,
arquitetura, decisões, limitações, contribuição do build e capturas reais do
App, está disponível em
[docs/quetzal-executive-deck.pptx](docs/quetzal-executive-deck.pptx). Ele pode
ser reconstruído por
[scripts/build_executive_deck.py](scripts/build_executive_deck.py); as capturas
incorporadas ficam em `docs/screenshots/deck/` e identidades humanas visíveis
foram mascaradas antes da inclusão.

As evidências textuais da execução publicada, incluindo deployment, preflight,
Lakeflow, consulta Genie, versões ML, OntoBricks, Lakebase, UI e limitações,
estão indexadas em
[evidence/execution/2026-10-12/README.md](evidence/execution/2026-10-12/README.md).
Os JSON/TXT são a prova primária; capturas de tela são apenas suplementares.

```bash
uv run --with-requirements requirements-dev.txt pytest -q
uv run --with ruff ruff check app.py server tests
cd frontend && npm run build
```

Após o deploy, valide `/api/health`, `/api/voc/overview`, `/api/campaigns/optimize`, `/api/campaigns/drafts`, persistência/reload de campanhas, a rota guiada, incidentes, ações e cenários, os dois modos de inteligência, os temas claro/escuro e o layout mobile. Consulte também os logs do App:

```bash
databricks apps logs quetzal-command-center --tail-lines 500 --profile <perfil>
```

## Operação atual

- versão da API: `3.0.0`;
- App de demonstração: `quetzal-command-center`;
- job DAB de bootstrap: `[demo] Quetzal | Bootstrap operacional`;
- job DAB manual de memória: `[demo] Quetzal | Managed Memory Foundation`;
- job DAB manual de migração Lakebase: `[demo] Quetzal | Migración Lakebase manual`;
- job DAB manual de grafo: `[demo] Quetzal | Graph Intelligence manual`;
- pipeline DAB Lakeflow: `[demo] Quetzal | Lakeflow medallion`, serverless e não contínuo;
- jobs DAB de geração, Lakeflow e ML: todos `manual-only`, sem schedule ou trigger;
- fontes de Lakeflow/ML recuperados e parametrizados; nenhuma nova geração, atualização do pipeline, inferência ou promoção de modelo foi executada na Etapa B;
- snapshot Graph Intelligence publicado: `graph-intelligence-v3-ontobricks`, run `04c290e225184d98a8b041c4f2e14316`, 60.000 clientes, 300.000 chamadas, 72.273 relações qualificadas e 36.303 grupos;
- domínio OntoBricks publicado: `quetzal_telecom` v1, build `915fa736`, 1.637.100 triplas, 22 predicados, `has_graph=true`, GraphQL e MCP validados com cliente real mascarado;
- estado de incidentes e ações persistido em Delta; casos de retenção e campanhas governadas, com ownership, aprovação, versões e eventos, persistidos no Lakebase.
- histórico do Quetzal IQ persistido no banco `quetzal` do projeto Lakebase `quilla-ltap`; pesquisa externa durável no Managed Memory `classic_stable_douglas_s_catalog.quetzal_telecom.quetzal_iq_memory`.
