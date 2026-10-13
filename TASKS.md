# Quetzal delivery tasks

## FE Bar alignment

- [x] Audit the local app, published snapshot and Customer Kit against the current FE Bar instructions.
- [x] Document the implementation sequence and acceptance criteria in [AJUSTES_FE_BAR.md](AJUSTES_FE_BAR.md).
- [ ] Close identity, authorization and territorial-scope gaps with regression tests.
- [ ] Package the real Lakeflow, ML training and scoring sources in the sanitized Customer Kit.
- [ ] Demonstrate Lakebase's operational role in the connected telecom journey.
- [x] Reconcile the guided journey and financial estimates for a consistent eligible population.
- [x] Add auditable textual execution evidence with masked identities, reproduction commands and explicit limitations.
- [ ] Consolidate implementation decisions and the business presentation as separate delivery artifacts.
- [x] Complete an authorized validation deployment and remote regression checks.

## Stage B in the original app

- [x] Recover the real Bronze, Silver and Gold Lakeflow sources by read-only export.
- [x] Recover and parameterize the original synthetic data generation notebooks.
- [x] Version churn, network anomaly and CLV train/register/score sources.
- [x] Separate `synthetic_churn_propensity` from model `churn_probability`.
- [x] Attribute scoring outputs to UC model version and MLflow run.
- [x] Add DAB resources with serverless, manual-only jobs and no schedules or triggers.
- [x] Document label, horizon, split, leakage limitations and overwrite behavior.
- [ ] Replicate these changes into the sanitized Customer Kit (explicitly out of scope for this request).
- [ ] Deploy Stage B resources after local review and explicit authorization.
- [ ] Execute data generation, Lakeflow or ML jobs only after separate cost/overwrite authorization.

## Stage C — Lakebase retention workflow

- [x] Define Lakebase as the operational source of truth for retention case state, SLA, approval and audit.
- [x] Add a checksum-protected, manual-only DAB migration and least-privilege App grants.
- [x] Add idempotent case creation, optimistic transitions, self-approval prevention, RBAC and territorial scope.
- [x] Preserve UC/Delta as the analytical source and capture real model version and MLflow run in every case.
- [x] Surface READY/DEGRADED state, cases and immutable events in Customer 360.
- [x] Give Quetzal IQ territorially scoped, read-only access to retention cases.
- [x] Build responsive light/dark frontend components and local contract coverage.
- [x] Deploy, run the migration manually and complete remote persistence/reload validation.

## Graph Intelligence

- [x] Approve data volume, schema and manual serverless execution.
- [x] Define Graph Intelligence business and technical architecture.
- [x] Add deterministic call-edge generation and graph feature notebook.
- [x] Add manual-only DAB job and Databricks App job permission.
- [x] Add graph job status, manual run, overview, community and ego-network APIs.
- [x] Enrich Customer 360 recommendations with graph signals.
- [x] Expose a governed graph scope to Quetzal IQ.
- [x] Add graph tables and guidance to the customer Genie Space.
- [x] Build interactive Customer 360 ego graph.
- [x] Build community/customer Graph Explorer and manual-run control.
- [x] Add backend contract tests and frontend build validation.
- [x] Run the DAB job and validate Unity Catalog row counts and quality.
- [x] Deploy the app with DAB and complete remote end-to-end validation.

## Relationship group operations

- [x] Replace technical community labels with business-facing relationship group names.
- [x] Add a governed operational group endpoint with RBAC and territorial scope.
- [x] Add paginated customer prioritization, SLA, churn, influence and current plan context.
- [x] Add eligible product offers and deterministic care, retention, NPS and growth playbooks.
- [x] Connect every member row to the real Customer 360 journey.
- [x] Validate aggregate, member and offer SQL against the published graph snapshot.
- [x] Deploy with DAB and complete remote UI validation.

## Qualified customer relationships

- [x] Version the relationship policy as `graph-fusion-v2-qualified`.
- [x] Generate repeated calls over stable subscriber relationship slots.
- [x] Require 3+ calls, 10+ minutes or reciprocity, plus activity within 60 days.
- [x] Apply recency and reciprocity weights to network churn exposure.
- [x] Replace unsupported household/social/work claims with frequent-contact semantics.
- [x] Expose active versus legacy policy metadata in Customer 360.
- [x] Preserve manual-only execution and DAB reproducibility.
- [x] Execute the expensive graph refresh manually when explicitly approved.

## Graph Intelligence v3 + OntoBricks

- [x] Keep the governed individual churn probability unchanged.
- [x] Add weighted PageRank for reach and weighted Personalized PageRank for risk diffusion.
- [x] Add weighted neighbour exposure, weighted deterministic Label Propagation and a non-probabilistic retention-priority score.
- [x] Version the telecom ontology and publish an OntoBricks-compatible Delta triple contract.
- [x] Add methodology, limitations and OntoBricks status to the backend and Graph Explorer.
- [x] Fix successful notebook exits being caught and logged as failed runs.
- [x] Preserve DAB reproducibility and manual-only execution.
- [x] Execute the v3 refresh manually only when explicitly approved.
- [x] Configure the separate OntoBricks App URL and publish `quetzal_telecom` v1.
- [x] Materialize all 22 governed predicates and persist `last_build` so the registry reports `has_graph=true`.
- [x] Validate a real masked customer through direct GraphQL and MCP `query_graphql`.
- [x] Route relational Quetzal IQ questions through an allowlisted OntoBricks MCP tool.
- [x] Add territorial class/relation projection and paginated semantic entities.
- [x] Connect semantic entity → Customer 360 → plan/SLA/offer → campaign draft.
- [x] Expose algorithm, snapshot, predicates, domain/version and territorial provenance.
- [x] Add the MCP endpoint to DAB variables and App environment without a schedule.
- [x] Add local backend contracts and frontend production-build validation.
- [x] Deploy and complete remote MCP/UI end-to-end validation after explicit authorization.

## Guided telecom demo

- [x] Add a deterministic, territorially governed incident-to-customer journey.
- [x] Add a counterfactual retention impact contract with formulas, intermediate values and sensitivity.
- [x] Unify scoring, subscription, ticket, billing, NPS, recommendation and geographic-context events in Customer 360.
- [x] Separate baseline, graph lift, contagion and influence as directional evidence; never label it SHAP or causal.
- [x] Add a manual read-only preflight with explicit no-inference and no-job guarantees.
- [x] Add contract, validation, RBAC, territorial-scope and no-paid-call tests.
- [x] Connect these backend contracts to the guided frontend experience.
- [x] Deploy and run remote end-to-end validation in desktop, mobile, light and dark modes.

## Modo Demo Certificada

- [x] Add a deterministic, territorially governed read-only manifest with real snapshot IDs.
- [x] Build the eight-step Spanish presenter route with persisted progress and destination context.
- [x] Surface preflight, source/model versions, optional-evidence warnings and cost guarantees.
- [x] Add a browser-only reset that preserves theme, Quetzal IQ conversations and Lakebase memory.
- [x] Preserve manual-only jobs, DAB reproducibility, RBAC and human approval boundaries.
- [x] Add backend safety/determinism/scope contracts and local frontend production-build validation.
- [x] Deploy the certified experience after explicit authorization.
- [x] Complete remote desktop/mobile and light/dark validation after deployment authorization.

## Voice of Customer and Campaign Optimizer

- [x] Derive bounded customer themes from governed tickets, NPS, SLA and Customer 360 signals.
- [x] Label every signal and example as synthetic demonstrative data; never claim a generated transcript.
- [x] Expose affected customer examples with territorial scope and Customer 360 navigation.
- [x] Connect a selected Voice of Customer theme to deterministic campaign eligibility.
- [x] Enforce consent, channel reachability, service-before-sales, objective, budget and contact capacity.
- [x] Return a read-only campaign draft with funnel, exclusions, audience preview and counterfactual impact.
- [x] Add RBAC, territorial-scope, validation, determinism and no-mutation contract tests.
- [x] Add both capabilities to the guided demo journey and responsive React navigation.
- [x] Reuse the exact selected campaign audience for benefit, cost, net impact, ROI, sensitivity and break-even.
- [x] Carry the same draft ID and audience fingerprint into the certified economic close.
- [x] Separate the 30-day churn prediction horizon from the commercial value horizon and list excluded costs.
- [x] Preserve negative ROI and unavailable break-even with regression coverage.
- [x] Deploy with DAB and complete remote API and visual validation.
- [x] Persist governed campaign drafts, ownership and reload recovery in Lakebase.
- [x] Preserve immutable audience/economic revisions with idempotency and optimistic concurrency.
- [x] Add segregated submission, approval, rejection and cancellation with an immutable audit trail.
- [x] Enforce `campaign_sent=false` and exclude delivery connectors and transitions by design.
- [x] Add the checksum-protected `002_campaign_workflow` migration to the manual-only DAB job.
- [x] Deploy the persistent campaign cycle, run migration 002 manually and complete remote reload/segregation validation.

## Quetzal IQ memory

- [x] Persist recoverable conversation transcripts and tool traces in Lakebase.
- [x] Partition transcript and semantic-memory access by verified Databricks Apps identity.
- [x] Persist only external research to Managed Agent Memory.
- [x] Improve BM25 retrieval with topic-bearing descriptions, bounded recall and legacy tool-artifact filtering.
- [x] Report recall and persistence as independent API/UI outcomes.
- [x] Keep provisioning and migrations manual-only with no recurring schedule.
- [x] Complete the post-fix remote cross-conversation recall validation.
