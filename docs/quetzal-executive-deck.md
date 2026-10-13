---
pagetitle: "Quetzal — alcance sem fronteiras"
lang: pt-BR
---

<p class="eyebrow">QUETZAL COMMAND CENTER · TELECOM</p>

# Alcance sem fronteiras

## Da rede ao cliente. Do sinal à decisão.

Uma experiência operacional governada que conecta rede, receita, churn,
relacionamentos e ação humana em 12 mercados da América Latina.

<p class="hero-note">Liberdade sempre · alcance máximo · conexão sem fronteiras</p>

---

<p class="eyebrow">01 · O PROBLEMA</p>

# Telecom opera com sinais fragmentados

- A degradação começa na rede, mas o impacto aparece em tickets, NPS, cobrança,
  churn e receita.
- NOC, atendimento, retenção e liderança trabalham com prioridades e tempos
  diferentes.
- Um score isolado não informa quem abordar, qual oferta é elegível nem qual
  dependência de rede deve ser resolvida primeiro.
- IA sem escopo territorial, evidência e aprovação cria risco operacional em
  vez de velocidade.

<p class="callout">Pergunta central: como transformar milhões de sinais em uma
decisão explicável, executável e economicamente defensável?</p>

---

<p class="eyebrow">02 · VALOR DE NEGÓCIO</p>

# Uma linha contínua entre incidente e resultado

| Decisão | Valor esperado |
|---|---|
| Priorizar incidentes | Concentrar operação em clientes e receita expostos |
| Reter com contexto | Combinar churn individual, SLA, NPS, produto e alcance |
| Desenhar campanhas | Respeitar consentimento, capacidade, orçamento e margem |
| Investigar com IA | Obter SQL, fontes e memória sem perder governança |
| Fechar o ciclo | Registrar decisão, aprovação, execução e resultado econômico |

As projeções do App são contrafactuais para decisão; não são apresentadas como
receita realizada ou causalidade comprovada.

---

<p class="eyebrow">03 · JORNADA DEMONSTRADA</p>

# Do preflight ao fechamento econômico

1. Validar Warehouse, Lakebase, Genie, IQ, AI/BI, RBAC e grafo.
2. Identificar incidente e população potencialmente afetada.
3. Navegar pelo grupo de relacionamento e abrir o Cliente 360.
4. Separar churn individual, exposição relacional, alcance e prioridade.
5. Investigar com Genie ou Quetzal IQ e inspecionar as fontes.
6. Ouvir a Voz do Cliente e selecionar uma ação elegível.
7. Otimizar a campanha com consentimento, orçamento e capacidade.
8. Persistir rascunho, aprovação e economia reconciliada no Lakebase.

<p class="callout">A demo conta uma história completa; nenhuma campanha é
enviada e os workloads caros permanecem manuais.</p>

---

<p class="eyebrow">04 · ARQUITETURA</p>

# Uma plataforma, dois ritmos de dados

```text
Fontes sintéticas demonstrativas
            │
Lakeflow: Bronze → Silver → Gold ────────┐
            │                            │
Unity Catalog + MLflow + Graph           │
            │                            ▼
AI/BI · Genie · OntoBricks ───────► FastAPI ─► React
            │                            │
Unity AI Gateway + Managed Memory        ▼
                                      Lakebase
                              casos · campanhas · memória
```

- Unity Catalog sustenta o plano analítico governado.
- Lakebase sustenta estado transacional, concorrência e auditoria.
- Databricks Apps entrega a experiência usando identidade gerenciada.
- Databricks Asset Bundles reproduzem código e recursos entre ambientes.

---

<p class="eyebrow">05 · CAPACIDADES</p>

# Inteligência acionável para telecom

| Operação | Cliente e crescimento | Inteligência governada |
|---|---|---|
| Centro de mando | Cliente 360 | Três espaços Genie |
| Incidentes e RCA | SLA e crédito estimado | Quetzal IQ com ferramentas curadas |
| Topologia de rede | Next Best Product/Action | Deep Research com fontes |
| Alertas sob demanda | Voz do Cliente | AI/BI embutido |
| Capacidade por mercado | Otimizador de campanhas | Memória recuperável e semântica |
| Ações CRM/BSS/OSS | Jornada econômica | Grafo semântico OntoBricks |

RBAC territorial, mascaramento, aprovação humana, idempotência e evidência
fazem parte do fluxo — não são uma camada posterior.

---

<p class="eyebrow">06 · DECISÕES DE DESIGN</p>

# Separar sinais evita falsas certezas

- `churn_probability`: única probabilidade individual; vem do modelo ML
  registrado e possui horizonte de 30 dias.
- exposição direta: risco ponderado dos contatos qualificados.
- Personalized PageRank: difusão de exposição; não é probabilidade.
- PageRank ponderado: alcance estrutural; não é influência causal.
- Label Propagation: grupos de relacionamento; serve para navegação e ação.
- `retention_priority_score`: ranking operacional que combina sinais distintos.

Uma relação exige recorrência, duração ou reciprocidade e atividade recente.
Uma chamada isolada não cria vínculo; o App não infere parentesco ou amizade.

---

<p class="eyebrow">07 · DADOS, IA E SEMÂNTICA</p>

# Componentes com responsabilidades explícitas

- **Lakeflow** — pipeline medallion serverless com 27 fluxos declarativos.
- **MLflow/Unity Catalog** — churn, CLV e anomalia de rede com versão e run.
- **Genie** — pergunta em linguagem natural, SQL visível e resultados reais.
- **Quetzal IQ** — investigação interna curada e pesquisa externa com fontes.
- **Lakebase** — conversas, casos, campanhas, versões, SLA e auditoria.
- **Managed Agent Memory** — sínteses por usuário; não substitui autorização.
- **Graph Intelligence** — relações ponderadas, alcance, exposição e grupos.
- **OntoBricks** — ontologia versionada, GraphQL e MCP read-only.

O deployment só configura recursos. Geração, Lakeflow, ML e grafo são
executados manualmente e não possuem agenda recorrente.

---

<p class="eyebrow">08 · EVIDÊNCIA REAL</p>

# A jornada está ancorada em execução

| Prova | Resultado |
|---|---|
| App publicado | `RUNNING` · compute `ACTIVE` · deployment `SUCCEEDED` |
| Lakeflow | run `62176317131697` · `SUCCESS` · 27/27 fluxos |
| Genie Clientes | statement `01f1bb5c…` · `SUCCEEDED` · 10 linhas |
| Graph Intelligence | workflow manual concluído · 72.273 relações |
| OntoBricks | domínio v1 publicado · 1.637.100 triplas |
| Validação local | 114 testes · Ruff · frontend · DAB aprovados |

Pergunta Genie comprovada: “Cuales son los clientes con el mayor potencial de
abandono?”. A evidência anexada preserva pergunta, SQL, resultados mascarados e
resposta natural, sem executar uma nova consulta.

---

<p class="eyebrow">09 · SEGURANÇA E GOVERNANÇA</p>

# A IA não amplia autoridade

- Identidade recebida do proxy verificado do Databricks Apps.
- Credenciais OAuth gerenciadas; tokens não são persistidos.
- Escopo territorial e papéis avaliados antes do acesso a dados.
- SQL parametrizado; o Quetzal IQ não recebe SQL arbitrário.
- Ferramenta OntoBricks limitada a intenções MCP read-only.
- Segregação entre solicitante e aprovador no Lakebase.
- Consentimento e elegibilidade aplicados antes da recomendação comercial.
- Trilha de versões e eventos para casos e campanhas.

Perfis territoriais falham fechados quando um serviço upstream não consegue
comprovar o mesmo filtro.

---

<p class="eyebrow">10 · LIMITAÇÕES</p>

# O que esta demo não pretende provar

- Dados, eventos, clientes e resultados são sintéticos.
- Scores extremos refletem o cenário demonstrativo, não calibração produtiva.
- Relação e comunidade indicam associação observada, nunca causalidade.
- Atribuição direta de incidente exige chaves de rede que a fonte atual não tem.
- Conversão, retenção, receita e ROI de campanha são estimativas contrafactuais.
- Conectores CRM/BSS/OSS dependem dos sistemas reais do cliente.
- O dashboard global e Genie exigem desenho adicional de governança territorial
  em uma implantação produtiva.
- Escala, custo, SLAs e qualidade precisam ser recalibrados com dados reais.

O App explicita essas fronteiras na interface e nas evidências versionadas.

---

<p class="eyebrow">11 · CONTRIBUIÇÃO DO BUILD ATUAL</p>

# De protótipo visual a produto demonstrável

- Redesenho da marca e da experiência responsiva em temas claro e escuro.
- Reconstrução do backend com autenticação, RBAC, contratos e falha segura.
- Recuperação e parametrização do ciclo Lakeflow/ML, sem agendas caras.
- Cliente 360, SLA, recomendações, Voz do Cliente e campanhas governadas.
- Quetzal IQ com pesquisa, fontes, memória e continuidade conversacional.
- Graph Intelligence explicado e transformado em fluxo operacional útil.
- Integração OntoBricks com grafo semântico navegável e ferramenta MCP.
- Jornada econômica reconciliada e prova textual auditável da execução.
- DAB como fonte de verdade para implantação e promoção futura.

O resultado é um ativo reproduzível, explicável e pronto para ser reconstruído
com fontes e políticas do cliente.

---

<p class="eyebrow">12 · PRÓXIMO PASSO</p>

# Reconstruir com a realidade do cliente

1. Mapear fontes OSS, BSS, CRM, billing, NPS, consentimento e contratos.
2. Definir identidade, território, papéis, retenção e critérios de aprovação.
3. Recalibrar labels, features, scores e custos com observação temporal real.
4. Homologar ações e ofertas com atendimento, rede, jurídico e segurança.
5. Medir uplift por experimento controlado e reconciliar resultado observado.
6. Promover por DAB entre desenvolvimento, homologação e produção.

<p class="hero-note">Quetzal transforma alcance em contexto — e contexto em
decisão responsável.</p>

