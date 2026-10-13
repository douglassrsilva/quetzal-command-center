export type GraphLevel = 'community' | 'customer' | 'semantic'

export type GraphRun = {
  run_id?: string
  status?: string
  computed_at?: string
  started_at?: string
  completed_at?: string
  message?: string
  error?: string
}

export type GraphNode = {
  id?: string
  node_id?: string
  customer_id?: string
  cliente_id?: string
  community_id?: string
  node_type?: GraphLevel
  type?: GraphLevel
  label?: string
  name?: string
  country?: string
  risk_tier?: string
  churn_probability?: number
  baseline_churn_probability?: number
  retention_priority_score?: number
  reach_score?: number
  network_exposure_score?: number
  risk_diffusion_score?: number
  bridge_score?: number
  influence_score?: number
  contagion_score?: number
  monthly_revenue?: number
  influenced_revenue_usd?: number
  customers?: number
  customer_count?: number
  high_risk_customers?: number
  entity_count?: number
  class_name?: string
  countries_reached?: number
  international_ratio?: number
  calls?: number
  minutes?: number
  is_center?: boolean
  x?: number
  y?: number
  [key: string]: unknown
}

export type GraphEdge = {
  source: string
  target: string
  calls?: number
  minutes?: number
  weight?: number
  affinity?: string
  international?: boolean
  reciprocal?: boolean
  dropped_pct?: number
  [key: string]: unknown
}

export type GraphSummary = {
  nodes?: number
  edges?: number
  total_nodes?: number
  total_edges?: number
  communities?: number
  high_risk_customers?: number
  influenced_revenue?: number
  influenced_revenue_usd?: number
  countries_reached?: number
  [key: string]: unknown
}

export type GraphPayload = {
  available?: boolean
  level?: GraphLevel
  run?: GraphRun
  run_id?: string
  computed_at?: string
  center?: GraphNode
  summary?: GraphSummary
  nodes: GraphNode[]
  edges: GraphEdge[]
  message?: string
  relationship_definition?: {
    version: string
    status: string
    label: string
    criteria: string[]
    affinity_semantics?: string
  }
  provenance?: GraphProvenance
}

export type GraphProvenance = {
  source_type: string
  domain: string
  version: string
  table: string
  snapshot?: {run_id?:string;generated_at?:string}
  algorithm: string
  predicates: string[]
  territorial_scope: string[]
  manual_only: boolean
}

export type SemanticEntity = {
  entity_uri:string
  entity_id:string
  label:string
  class_uri:string
  customer_id?:string
  customer_ref?:string
  country?:string
  segment?:string
  churn_probability?:number
  current_plan?:string
  sla_policy_name?:string
  open_tickets?:number
  proposed_plan_id?:string
  proposed_product?:string
  recommendation_type?:string
  recommendation_score?:number
  marketing_eligible?:boolean
}

export type SemanticEntitiesPayload = {
  available:boolean
  reason?:string
  class_name:string
  predicate?:string|null
  entities:SemanticEntity[]
  pagination:{offset:number;limit:number;total:number}
  provenance?:GraphProvenance
}

export type GraphGroup = {
  technical_id: string
  display_name: string
  primary_country?: string
  dominant_segment?: string
  countries?: string
  countries_reached?: number
  customer_count?: number
  avg_churn_probability?: number
  high_risk_customers?: number
  monthly_revenue_usd?: number
  monthly_revenue_at_risk_usd?: number
  avg_influence_score?: number
  customers_with_open_tickets?: number
  customers_with_sla_pressure?: number
  detractors?: number
  marketing_eligible_customers?: number
  computed_at?: string
}

export type GraphGroupMember = {
  customer_id: string
  customer_ref: string
  country?: string
  segment?: string
  current_plan?: string
  monthly_revenue?: number
  churn_probability?: number
  graph_lift?: number
  risk_tier?: string
  influence_score?: number
  contagion_score?: number
  nps_ultimo?: number
  open_tickets?: number
  overdue_balance?: number
  active_subscriptions?: number
  sla_status?: 'AT_RISK' | 'OPEN' | 'ON_TRACK'
  next_best_action?: string
  proposed_plan_id?: string
  proposed_product?: string
  proposed_vertical?: string
  proposed_price_usd?: number
  offer_score?: number
  marketing_eligible?: boolean
}

export type GraphGroupOffer = {
  plan_id: string
  product_name: string
  vertical?: string
  tier?: string
  price_usd?: number
  recommendation_type?: string
  eligible_customers?: number
  avg_score?: number
  reason?: string
}

export type GraphPlaybook = {
  type: string
  priority: string
  title: string
  audience: number
  reason: string
  action: string
}

export type GraphGroupOperationalPayload = {
  available: boolean
  reason?: string
  group: GraphGroup | null
  members: GraphGroupMember[]
  offers: GraphGroupOffer[]
  playbooks: GraphPlaybook[]
  pagination?: {offset: number; limit: number; total: number}
  filters?: {country: string; risk_tier: string; sort: GraphGroupSort}
}

export type GraphGroupSort = 'priority' | 'opportunity' | 'influence'

export type GraphAlgorithm = {
  id: string
  label: string
  algorithm: string
  output: string
  role: string
}

export type GraphMethodology = {
  status: string
  active_model_version: string
  target_model_version: string
  manual_only: boolean
  snapshot?: {
    run_id?: string
    computed_at?: string
    customers?: number
    [key:string]:unknown
  }
  relationship: {label:string;criteria:string[];weight:string;semantics:string}
  algorithms: GraphAlgorithm[]
  pagerank_decision: {is_best_churn_algorithm:boolean;decision:string;validation_required:string}
  ontobricks: {
    mode:string
    version:string
    domain:string
    ontology_path:string
    triple_table:string
    external_app_url?:string|null
    runtime_status?:string
    snapshot?:Record<string,unknown>
    purpose:string[]
    analytics_policy:string
    lineage?:string[]
  }
  limitations:string[]
}

export const graphNodeId = (node: GraphNode) => String(
  node.id ?? node.node_id ?? node.customer_id ?? node.cliente_id ?? node.community_id ?? '',
)

export const graphNodeLabel = (node: GraphNode) => String(
  node.label ?? node.name ?? node.customer_id ?? node.cliente_id ?? node.community_id ?? node.node_id ?? 'Nodo',
)

export const graphNodeType = (node: GraphNode): GraphLevel => (
  node.node_type === 'semantic' || node.type === 'semantic'
    ? 'semantic'
    : node.node_type === 'community' || node.type === 'community' || (!node.customer_id && !node.cliente_id && (!!node.community_id || !!node.node_id))
    ? 'community'
    : 'customer'
)

export const graphRunId = (run: GraphRun | { run?: GraphRun } | null | undefined) => {
  if (!run) return ''
  return 'run' in run && run.run ? String(run.run.run_id ?? '') : String((run as GraphRun).run_id ?? '')
}

export const graphScorePercent = (value: unknown) => {
  return Number(value || 0)
}

export const graphRunFromResponse = (value: GraphRun | {run?:GraphRun;workflow?:GraphRun;snapshot?:GraphRun}): GraphRun => {
  if ('run' in value && value.run) return value.run
  if ('workflow' in value || 'snapshot' in value) {
    const workflow=value.workflow||{}
    const snapshot=value.snapshot||{}
    return {...snapshot,...workflow,computed_at:snapshot.computed_at||snapshot.completed_at||workflow.computed_at}
  }
  return value as GraphRun
}
