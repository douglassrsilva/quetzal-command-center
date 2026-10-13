# Quetzal Command Center

## North star

Quetzal is a telecom operations and customer-intelligence application built around reach, freedom and connection without borders. It combines governed analytics, operational workflows and AI assistance for teams responsible for network, revenue and customer experience across Latin America.

## Graph Intelligence evolution

The Graph Intelligence module keeps the governed individual churn probability intact and adds operational context from qualified subscriber relationships. It turns call relationships into explainable reach, exposure, diffusion and retention-priority signals.

### Business experiences

- Customer 360 shows an interactive ego network with qualified contacts, relationship group, cross-border reach and relational exposure.
- Network Explorer provides community-level and customer-level drill-down without sending the full graph to the browser.
- Proactive care uses the unchanged churn propensity, related revenue and high-risk-neighbour exposure to prioritize treatment.
- Quetzal IQ can answer governed questions about reach, relationship groups, exposure and OntoBricks semantics without claiming causality.
- An authorized operator runs the complete snapshot manually from the app. No recurring schedule is created.

### Data architecture

1. `silver_customer_call_edges`: 300,000 deterministic synthetic call relationships across 60,000 existing customers and 12 countries.
2. `gold_customer_graph_features`: weighted PageRank reach, Personalized PageRank diffusion, degree, reciprocity, clustering, weighted relationship groups and neighbour exposure.
3. `gold_churn_graph_predictions`: unchanged baseline churn plus a distinct, non-probabilistic retention-priority score.
4. `gold_graph_community_summary`: bounded community aggregates for the application explorer.
5. `ops_graph_run_log`: audited manual execution state and row counts.
6. `gold_quetzal_knowledge_graph_triples`: OntoBricks-compatible semantic projection governed by `ontology/quetzal-telecom-v1.ttl`.

All assets live in the existing Unity Catalog catalog and schema. The Databricks Asset Bundle owns the job, notebook, app resource permission and runtime configuration.

### Runtime and cost controls

- Manual-only Databricks Workflow; no `schedule` or continuous trigger.
- Serverless job compute where supported by the workspace.
- Latest snapshot only for edges and derived Gold tables; compact run history only.
- Browser payloads are bounded to ego networks or aggregated communities.

### Visual language

- Quetzal green and cyan express movement, reach and open borders.
- Communities use distinct accessible hues; risk is never communicated by colour alone.
- Minimum 14 px actionable text and high-contrast graph edges in light and dark themes.
- Stable server-provided coordinates avoid layout movement between interactions.

## Security and governance

- Existing Databricks identity, country scope and operational RBAC apply to graph APIs.
- Full customer identifiers remain restricted to governed operational views.
- Graph actions require explicit operator intent; model outputs never execute retention actions automatically.
- All source data is synthetic and demonstrative.

## Guided telecom demo backend

The backend exposes a reproducible, read-only path for a presenter or future
frontend experience:

1. `GET /api/demo/preflight` checks SQL connectivity and the configured Genie,
   AI Gateway, Lakebase, Managed Memory, dashboard, RBAC and latest Graph
   Intelligence snapshot. It never invokes paid inference or starts a job.
2. `GET /api/demo/journey?country=ALL` deterministically selects the highest
   priority unresolved incident and a high-risk customer from the same
   authorized market.
3. `GET /api/customers/{customer_id}/360` unifies customer events, SLA,
   recommendations and graph evidence in one bounded timeline.
4. `POST /api/demo/financial-impact` remains available as a generic legacy
   simulator. The certified campaign journey does not use it: campaign
   economics come from the exact selected audience returned by
   `POST /api/campaigns/optimize`.

### Modo Demo Certificada

`GET /api/demo/manifest?country=ALL` is the read-only presenter contract. It
resolves one deterministic, territorially authorized scenario and freezes the
real incident, relationship group, customer, Quetzal IQ prompt, Voice of
Customer theme and campaign draft context behind a stable manifest ID. Its
eight stages are: Preflight, Incident, Graph Intelligence, Customer 360,
Quetzal IQ, Voice of Customer, Campaign Optimizer and Economic Journey.

The manifest exposes app, graph, churn, OntoBricks, VoC and campaign-rule
versions together with source tables and explicit cost/safety guarantees.
Optional evidence that is not available is returned as a visible warning; it
is never fabricated. Loading the manifest does not invoke model inference,
Genie, connectors, jobs, graph refreshes or campaign delivery.

The frontend persists only presenter progress and active-step context in the
browser. **Reiniciar demo** clears that ephemeral demo state and navigation
seeds only. It preserves the selected visual theme, existing Quetzal IQ
conversations and all Lakebase/backend memory. The expensive workflows remain
manual-only and are not prerequisites executed by this route.

Remote validation on 2026-10-12 published deployment
`01f1c65c668f1eb2972e15939108031d`. The certified BR route resolved manifest
`QDM-CFB18327A439` against Graph Intelligence snapshot
`04c290e225184d98a8b041c4f2e14316` and passed desktop/mobile plus light/dark
checks with GET-only navigation. No prompt, job, inference, connector or
campaign was executed during validation.

Economic-journey validation on 2026-10-12 published deployment
`01f1c6634f6a1111bb8c8cbbbf0785bc`. Manifest `QDM-CFB18327A439` exposed all
eight stages. A read-only BR/BILLING retention draft selected 100 customers;
funnel, impact and sensitivity reconciled to fingerprint
`1abab4ba30c118c8`, with `campaign_sent=false` and
`records_written=false`. Re-running the same audience with a zero response
assumption preserved a -100% ROI and `NEGATIVE` outcome. Browser validation
reused the same draft in the certified close, reported no console errors, and
passed desktop dark/light plus 390 px mobile without horizontal overflow. No
job, model inference, connector or campaign execution was triggered.

Network incidents in Customer 360 and the guided journey are labelled
`GEOGRAPHIC_CONTEXT` or `SAME_MARKET_EXAMPLE`, with
`direct_customer_attribution=false`. `silver_cdrs` has no tower identifier, so
Quetzal does not claim that a particular tower incident affected a customer.

Explainability is labelled `SEPARATED_PROPENSITY_AND_NETWORK_SIGNALS` and
`is_shap=false`. It separates the governed individual churn probability,
retention priority, relational exposure and reach. PageRank is never presented
as a churn model, and network association is never presented as causality.

## Voice of Customer and governed campaigns

`GET /api/voc/overview` derives a bounded market view from `silver_tickets`,
`silver_nps`, `ops_sla_policy` and `ops_customer_360`. Theme assignment is
deterministic (`voc-rules-v1`), uses no model inference and includes masked
customer examples within the operator's territorial scope. The interface calls
these examples synthetic summaries and never presents them as real transcripts.

`POST /api/campaigns/optimize` turns an optional Voice of Customer theme into a
governed audience. `campaign-rules-v1` applies, in order: territorial scope,
marketing consent, channel reachability, service-before-sales, objective and
theme eligibility, then budget and contact capacity. It returns a reproducible
`DRAFT` with exclusion counts, a bounded audience preview and counterfactual
impact. It writes no records, invokes no connector and sends no communication.

The draft is also the certified economic contract. The API fingerprints the
ordered selected customer IDs and reports `same_population_used_for_impact` so
the funnel, audience preview and economics can be reconciled. The UI carries
that same in-memory draft back to the certified journey and refuses to combine
it with a different country, Voice of Customer theme or objective. It exposes:

- selected population, eligible population before caps, `draft_id` and
  audience fingerprint;
- gross benefit, included contact cost, net impact, ROI and response-rate
  break-even;
- conservative, base and optimistic response assumptions without changing the
  audience, horizon or cost;
- the 30-day churn prediction horizon separately from the configurable
  commercial value horizon;
- excluded costs such as discounts, taxes, fulfillment, incremental labor,
  cannibalization and competitive response.

The response rate is an explicit combined response-and-treatment-success
hypothesis. Results are synthetic counterfactual estimates, not causal effects
or guarantees. Negative ROI is preserved. When no potential benefit exists,
break-even is reported as unavailable rather than coerced into a positive
case.

Saving is an explicit second step. The App recomputes the audience server-side
and persists the governed request, current snapshot, immutable versions,
owner and audit events in Lakebase. Reloading restores the same campaign and
economic fingerprint. Submission, approval, rejection and cancellation use
optimistic concurrency and idempotency; the requester cannot approve their own
campaign. There is deliberately no delivery transition or connector and the
database enforces `campaign_sent=false`.

### Presenter route

1. **Preflight** — show that Warehouse, Genie, Quetzal IQ, memory, AI/BI, RBAC
   and Graph Intelligence are available without paid inference or job execution.
2. **Priority incident** — establish the operational signal, severity, SLA and
   value at risk without claiming direct tower-to-customer attribution.
3. **Graph Intelligence** — show relationship reach, exposure and priority as
   separate non-causal signals, with OntoBricks provenance.
4. **Customer 360** — open one affected customer and connect subscription,
   tickets, NPS, SLA, churn baseline and relationship evidence.
5. **Quetzal IQ** — investigate the prepared customer and relationship context
   while keeping internal evidence and external research distinct.
6. **Voice of Customer** — filter the same market, explain the leading theme,
   its evidence and affected customers, and select **Optimizar campaña**.
7. **Campaign Optimizer** — adjust channel, budget and capacity; narrate the
   eligibility funnel, exclusions, audience preview and `NO ENVIADA` status.
8. **Persistent campaign cycle** — save the draft, reload it from Lakebase,
   show owner, immutable snapshot version and audit events, then submit it for
   segregated approval. Do not simulate a second identity when none is present.
9. **Economic Journey** — return to the certified route and close with the same
   `draft_id`, audience fingerprint, benefit, cost, net impact, sensitivity and
   break-even. Explain the 30-day churn horizon, commercial horizon, excluded
   costs and counterfactual limitations.

No recurring job is required for this route. The expensive Graph Intelligence
refresh remains manual and must not be started as part of the presentation.
The OntoBricks build is also manual and should be prepared before the demo;
validation is read-only with `python3 scripts/ontobricks_admin.py validate`.

### Persistent campaign validation evidence

The manual Lakebase migration run `396073321799068` completed successfully:
`001_retention_cases` was already applied and `002_campaign_workflow` was
applied. The authenticated E2E campaign `CMP-E8E61467CC115EDA` proved create,
idempotent replay, reload, immutable snapshot versions 1 and 2, optimistic
concurrency, submission, requester self-approval rejection (`409`) and safe
cancellation. The final Lakebase row remained `campaign_sent=false` and every
audit event carried the same non-delivery evidence.

The positive approver path is covered by the backend contract test with a
distinct `ACTION_APPROVER`. It was intentionally not impersonated in the remote
test because only one authenticated browser identity was available. Desktop
and mobile, light and dark themes were inspected against the deployed App with
no horizontal overflow, console error or failed request.

## Quetzal IQ memory validation

Quetzal IQ uses Lakebase for the exact recoverable transcript and Managed
Agent Memory for durable external-research context. Recall and write are
reported separately: `recalled`/`recalled_count` describe prior context used by
the answer, while `persisted` confirms that the current web research was saved.
The authenticated Databricks Apps identity determines the per-user scope; the
request body and model cannot choose it.

Remote end-to-end validation on 2026-10-12 passed on deployment
`01f1c65ff1bd147ea9da80cafe552287`. Conversation
`iqc-2ff53812d00f42f287f827e8cd72e134`, trace `iq-bb4a400035aa`, recalled three
memories and recovered the prior fixed-mobile convergence finding. The answer
explicitly separated historical memory from current web verification; the UI
showed **Memoria recuperada** and **Memoria guardada**. Lakebase persistence
remained active. The validation made one authorized `/api/chat` inference call
and executed no job, campaign or operational action.

## Textual execution evidence

The auditable execution package is indexed at
[`evidence/execution/2026-10-12/README.md`](evidence/execution/2026-10-12/README.md).
It records the published deployment, read-only preflight, certified manifest,
ML attribution, Graph Intelligence/OntoBricks state, Lakebase migrations and
campaign audit, responsive UI metrics and the Quetzal IQ validation trace.
Human identities are masked and no credentials are stored. JSON/TXT records
are the primary evidence; screenshots are supplemental.
