# Databricks notebook source
import re

dbutils.widgets.text("catalog", "classic_stable_douglas_s_catalog")
dbutils.widgets.text("schema", "quetzal_telecom")
dbutils.widgets.text("app_name", "quetzal-command-center")
dbutils.widgets.text("admin_users", "douglas.s@databricks.com")

catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
app_name = dbutils.widgets.get("app_name")
admin_users = [item.strip().lower() for item in dbutils.widgets.get("admin_users").split(",") if item.strip()]
assert all(re.fullmatch(r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}", item) for item in admin_users), "invalid admin user"
assert catalog.replace("_", "").isalnum(), "invalid catalog"
assert schema.replace("_", "").isalnum(), "invalid schema"
assert app_name.replace("-", "").isalnum(), "invalid app name"
fq = f"`{catalog}`.`{schema}`"


def sql(statement: str):
    return spark.sql(statement)


def ensure_columns(table: str, definitions: dict[str, str]):
    existing = {row.col_name.lower() for row in sql(f"DESCRIBE {fq}.{table}").collect() if row.col_name and not row.col_name.startswith("#")}
    missing = [f"{name} {definition}" for name, definition in definitions.items() if name.lower() not in existing]
    if missing:
        sql(f"ALTER TABLE {fq}.{table} ADD COLUMNS ({', '.join(missing)})")


sql(f"""
CREATE TABLE IF NOT EXISTS {fq}.ops_incident_state (
  incident_id STRING NOT NULL,
  status STRING NOT NULL,
  assignee STRING,
  acknowledged_at TIMESTAMP,
  resolved_at TIMESTAMP,
  updated_at TIMESTAMP NOT NULL,
  updated_by STRING NOT NULL
) USING DELTA
COMMENT 'Estado transacional dos incidentes derivados da operação de rede'
TBLPROPERTIES ('project'='quetzal', 'managed_by'='dabs', 'data_classification'='synthetic')
""")

sql(f"""
CREATE TABLE IF NOT EXISTS {fq}.ops_action_log (
  action_id STRING NOT NULL,
  incident_id STRING,
  action_type STRING NOT NULL,
  rationale STRING NOT NULL,
  status STRING NOT NULL,
  requested_by STRING NOT NULL,
  requested_at TIMESTAMP NOT NULL,
  decided_by STRING,
  decided_at TIMESTAMP,
  decision_note STRING
) USING DELTA
COMMENT 'Ações operacionais, aprovações humanas e trilha de decisão'
TBLPROPERTIES ('project'='quetzal', 'managed_by'='dabs', 'data_classification'='synthetic')
""")

sql(f"""
CREATE TABLE IF NOT EXISTS {fq}.ops_action_attempts (
  attempt_id STRING NOT NULL,
  action_id STRING NOT NULL,
  connector STRING NOT NULL,
  status STRING NOT NULL,
  idempotency_key STRING NOT NULL,
  request_json STRING,
  response_code INT,
  response_json STRING,
  started_at TIMESTAMP NOT NULL,
  completed_at TIMESTAMP,
  actor STRING NOT NULL,
  execution_ref STRING,
  detail STRING
) USING DELTA
COMMENT 'Intentos idempotentes de ejecución en conectores CRM, BSS, OSS o cola interna'
TBLPROPERTIES ('project'='quetzal', 'managed_by'='dabs', 'data_classification'='synthetic')
""")

sql(f"""
CREATE TABLE IF NOT EXISTS {fq}.ops_alert_subscriptions (
  subscription_id STRING NOT NULL,
  owner STRING NOT NULL,
  name STRING NOT NULL,
  domain STRING NOT NULL,
  country STRING,
  metric STRING NOT NULL,
  operator STRING NOT NULL,
  threshold DOUBLE NOT NULL,
  channel STRING NOT NULL,
  enabled BOOLEAN NOT NULL,
  created_at TIMESTAMP NOT NULL,
  updated_at TIMESTAMP NOT NULL
) USING DELTA
COMMENT 'Assinaturas e regras de alerta personalizadas por operador'
TBLPROPERTIES ('project'='quetzal', 'managed_by'='dabs', 'data_classification'='synthetic')
""")

sql(f"""
CREATE TABLE IF NOT EXISTS {fq}.ops_alert_events (
  event_id STRING NOT NULL,
  subscription_id STRING NOT NULL,
  fingerprint STRING NOT NULL,
  country STRING,
  metric STRING NOT NULL,
  observed_value DOUBLE NOT NULL,
  threshold DOUBLE NOT NULL,
  severity STRING NOT NULL,
  status STRING NOT NULL,
  notification_status STRING NOT NULL,
  detected_at TIMESTAMP NOT NULL,
  notified_at TIMESTAMP,
  acknowledged_at TIMESTAMP,
  acknowledged_by STRING,
  note STRING
) USING DELTA
COMMENT 'Eventos deduplicados producidos por el motor de alertas y su acuse'
TBLPROPERTIES ('project'='quetzal', 'managed_by'='dabs', 'data_classification'='synthetic')
""")

sql(f"""
CREATE TABLE IF NOT EXISTS {fq}.ops_user_roles (
  principal STRING NOT NULL,
  role STRING NOT NULL,
  country_scope STRING,
  active BOOLEAN NOT NULL,
  updated_at TIMESTAMP NOT NULL
) USING DELTA
COMMENT 'Roles y alcance territorial para RBAC y segregación de funciones'
TBLPROPERTIES ('project'='quetzal', 'managed_by'='dabs', 'data_classification'='synthetic')
""")

for principal in admin_users:
    sql(f"""
    MERGE INTO {fq}.ops_user_roles AS target
    USING (SELECT '{principal}' AS principal, 'ADMIN' AS role) AS source
    ON lower(target.principal) = source.principal AND target.role = source.role
    WHEN MATCHED THEN UPDATE SET active = true, updated_at = current_timestamp()
    WHEN NOT MATCHED THEN INSERT (principal, role, country_scope, active, updated_at)
      VALUES (source.principal, source.role, NULL, true, current_timestamp())
    """)

sql(f"""
CREATE TABLE IF NOT EXISTS {fq}.ops_audit_log (
  event_id STRING NOT NULL,
  event_type STRING NOT NULL,
  resource_type STRING NOT NULL,
  resource_id STRING NOT NULL,
  actor STRING NOT NULL,
  event_at TIMESTAMP NOT NULL,
  detail_json STRING
) USING DELTA
COMMENT 'Evidência auditável das mudanças realizadas pelo Quetzal Command Center'
TBLPROPERTIES ('project'='quetzal', 'managed_by'='dabs', 'data_classification'='synthetic')
""")

sql(f"""
CREATE TABLE IF NOT EXISTS {fq}.ops_sla_policy (
  segment_id STRING NOT NULL,
  policy_name STRING NOT NULL,
  first_response_target_hours DOUBLE NOT NULL,
  resolution_target_hours DOUBLE NOT NULL,
  service_target_pct DOUBLE NOT NULL,
  contractual BOOLEAN NOT NULL,
  policy_source STRING NOT NULL,
  updated_at TIMESTAMP NOT NULL
) USING DELTA
COMMENT 'Referências operacionais de atendimento por segmento; não substituem o contrato individual do cliente'
TBLPROPERTIES ('project'='quetzal', 'managed_by'='dabs', 'data_classification'='synthetic')
""")

ensure_columns("ops_sla_policy", {
    "business_hours_per_day": "DOUBLE COMMENT 'Horas de servicio por día'",
    "business_days": "STRING COMMENT 'Días aplicables del calendario'",
    "timezone": "STRING COMMENT 'Zona horaria contractual'",
    "breach_credit_pct": "DOUBLE COMMENT 'Crédito estimado por incumplimiento'",
})

sql(f"""
CREATE TABLE IF NOT EXISTS {fq}.ops_customer_sla_contract (
  contract_id STRING NOT NULL,
  customer_id STRING NOT NULL,
  policy_name STRING NOT NULL,
  first_response_target_hours DOUBLE NOT NULL,
  resolution_target_hours DOUBLE NOT NULL,
  service_target_pct DOUBLE NOT NULL,
  business_hours_per_day DOUBLE NOT NULL,
  business_days STRING NOT NULL,
  timezone STRING NOT NULL,
  breach_credit_pct DOUBLE NOT NULL,
  effective_from DATE NOT NULL,
  effective_to DATE,
  active BOOLEAN NOT NULL,
  source STRING NOT NULL,
  updated_at TIMESTAMP NOT NULL
) USING DELTA
COMMENT 'Excepciones contractuales individuales de SLA por cliente'
TBLPROPERTIES ('project'='quetzal', 'managed_by'='dabs', 'data_classification'='synthetic')
""")

sql(f"""
MERGE INTO {fq}.ops_sla_policy AS target
USING (
  SELECT * FROM VALUES
    ('PER', 'Quetzal Life Care', 24D, 72D, 99.0D, false, 'SEGMENT_REFERENCE', 24D, 'MON-SUN', 'UTC', 2D, current_timestamp()),
    ('BIZ', 'Quetzal Biz Priority', 4D, 24D, 99.5D, true, 'SEGMENT_CONTRACT', 12D, 'MON-SAT', 'America/Mexico_City', 5D, current_timestamp()),
    ('ENT', 'Quetzal Enterprise Mission Critical', 1D, 8D, 99.9D, true, 'SEGMENT_CONTRACT', 24D, 'MON-SUN', 'UTC', 10D, current_timestamp())
  AS policy(segment_id, policy_name, first_response_target_hours, resolution_target_hours,
            service_target_pct, contractual, policy_source, business_hours_per_day, business_days,
            timezone, breach_credit_pct, updated_at)
) AS source
ON target.segment_id = source.segment_id
WHEN MATCHED THEN UPDATE SET *
WHEN NOT MATCHED THEN INSERT *
""")

sql(f"""
CREATE OR REPLACE VIEW {fq}.ops_customer_sla_effective
COMMENT 'SLA efectivo: prioriza contrato individual vigente y conserva referencia de segmento'
AS
SELECT c.cliente_id AS customer_id,
       COALESCE(x.policy_name, p.policy_name) AS policy_name,
       COALESCE(x.first_response_target_hours, p.first_response_target_hours) AS first_response_target_hours,
       COALESCE(x.resolution_target_hours, p.resolution_target_hours) AS resolution_target_hours,
       COALESCE(x.service_target_pct, p.service_target_pct) AS service_target_pct,
       COALESCE(x.business_hours_per_day, p.business_hours_per_day) AS business_hours_per_day,
       COALESCE(x.business_days, p.business_days) AS business_days,
       COALESCE(x.timezone, p.timezone) AS timezone,
       COALESCE(x.breach_credit_pct, p.breach_credit_pct) AS breach_credit_pct,
       CASE WHEN x.contract_id IS NOT NULL THEN true ELSE p.contractual END AS contractual,
       CASE WHEN x.contract_id IS NOT NULL THEN x.source ELSE p.policy_source END AS policy_source,
       x.contract_id
FROM {fq}.silver_clientes c
LEFT JOIN {fq}.ops_sla_policy p ON c.segmento_id = p.segment_id
LEFT JOIN {fq}.ops_customer_sla_contract x ON c.cliente_id = x.customer_id
 AND x.active = true AND current_date() >= x.effective_from
 AND (x.effective_to IS NULL OR current_date() <= x.effective_to)
""")

sql(f"""
CREATE TABLE IF NOT EXISTS {fq}.ops_recommendation_log (
  recommendation_id STRING NOT NULL,
  customer_id STRING NOT NULL,
  recommendation_type STRING NOT NULL,
  product_id STRING,
  title STRING NOT NULL,
  reason STRING NOT NULL,
  score DOUBLE,
  status STRING NOT NULL,
  proposed_by STRING NOT NULL,
  proposed_at TIMESTAMP NOT NULL,
  updated_by STRING NOT NULL,
  updated_at TIMESTAMP NOT NULL,
  outcome_value_usd DOUBLE,
  outcome_at TIMESTAMP,
  note STRING
) USING DELTA
COMMENT 'Ciclo cerrado de recomendaciones, decisiones y resultados comerciales u operativos'
TBLPROPERTIES ('project'='quetzal', 'managed_by'='dabs', 'data_classification'='synthetic')
""")

sql(f"""
CREATE OR REPLACE VIEW {fq}.ops_incident_candidates
COMMENT 'Incidentes candidatos derivados de anomalias, telemetria, tickets e risco comercial'
AS
WITH anomaly_anchor AS (
  SELECT MAX(timestamp) AS max_ts FROM {fq}.gold_network_anomalies
), recent_anomalies AS (
  SELECT a.*
  FROM {fq}.gold_network_anomalies a CROSS JOIN anomaly_anchor x
  WHERE a.is_anomaly = 1 AND a.timestamp >= x.max_ts - INTERVAL 24 HOURS
), ticket_anchor AS (
  SELECT MAX(fecha_creacion) AS max_ts FROM {fq}.silver_tickets
), ticket_pressure AS (
  SELECT t.pais_codigo,
         COUNT(*) AS tickets_7d,
         SUM(CASE WHEN lower(t.prioridad) IN ('alta','crítica','critica') THEN 1 ELSE 0 END) AS urgent_tickets_7d
  FROM {fq}.silver_tickets t CROSS JOIN ticket_anchor x
  WHERE t.fecha_creacion >= x.max_ts - INTERVAL 7 DAYS
  GROUP BY t.pais_codigo
), churn_anchor AS (
  SELECT MAX(scored_at) AS max_ts FROM {fq}.gold_churn_predictions
), country_value AS (
  SELECT c.pais_codigo,
         AVG(c.gasto_mensual_total) AS avg_monthly_value,
         SUM(CASE WHEN lower(c.risk_tier) IN ('alto','crítico','critico','high','critical') THEN 1 ELSE 0 END) AS high_churn_customers
  FROM {fq}.gold_churn_predictions c CROSS JOIN churn_anchor x
  WHERE c.scored_at = x.max_ts
  GROUP BY c.pais_codigo
)
SELECT
  concat('NET-', a.torre_id) AS incident_id,
  concat('Degradación detectada en ', a.torre_id, ' · ', a.ciudad) AS title,
  'NETWORK' AS domain,
  CASE WHEN a.anomaly_score >= 0.90 OR a.anomaly_severity IN ('Crítica','Critical') THEN 'CRITICAL'
       WHEN a.anomaly_score >= 0.78 OR a.anomaly_severity IN ('Alta','High') THEN 'HIGH'
       ELSE 'MEDIUM' END AS severity,
  a.pais_codigo AS country,
  a.ciudad AS city,
  a.torre_id AS tower_id,
  a.tecnologia AS technology,
  a.timestamp AS detected_at,
  a.anomaly_score,
  a.latencia_ms AS latency_ms,
  a.throughput_mbps,
  a.packet_loss_pct,
  a.uso_capacidad_pct AS capacity_pct,
  a.temperatura_equipo_c AS equipment_temp_c,
  a.usuarios_conectados AS affected_customers,
  ROUND(a.usuarios_conectados * COALESCE(v.avg_monthly_value, 35) *
        CASE WHEN a.anomaly_score >= .9 THEN .18 WHEN a.anomaly_score >= .78 THEN .10 ELSE .05 END, 0) AS revenue_at_risk,
  COALESCE(t.tickets_7d, 0) AS tickets_7d,
  COALESCE(t.urgent_tickets_7d, 0) AS urgent_tickets_7d,
  COALESCE(v.high_churn_customers, 0) AS high_churn_customers,
  CASE WHEN a.temperatura_equipo_c >= 75 THEN 'THERMAL'
       WHEN a.uso_capacidad_pct >= 85 THEN 'CONGESTION'
       WHEN a.packet_loss_pct >= 3 THEN 'TRANSPORT'
       WHEN a.latencia_ms >= 80 THEN 'BACKHAUL'
       ELSE 'RADIO_SIGNAL' END AS probable_cause,
  LEAST(0.98, ROUND(0.55 + a.anomaly_score * 0.4, 2)) AS cause_confidence,
  a.alerta AS evidence
FROM recent_anomalies a
LEFT JOIN ticket_pressure t ON a.pais_codigo = t.pais_codigo
LEFT JOIN country_value v ON a.pais_codigo = v.pais_codigo
QUALIFY ROW_NUMBER() OVER (PARTITION BY a.torre_id ORDER BY a.anomaly_score DESC, a.timestamp DESC) = 1
""")

sql(f"""
CREATE OR REPLACE VIEW {fq}.ops_customer_360
COMMENT 'Perfil individual governado com valor, risco, experiência, cobrança e compromissos de serviço'
AS
WITH latest_churn AS (
  SELECT * FROM {fq}.gold_churn_predictions
  QUALIFY ROW_NUMBER() OVER (PARTITION BY cliente_id ORDER BY scored_at DESC) = 1
), latest_clv AS (
  SELECT * FROM {fq}.gold_clv_segments
  QUALIFY ROW_NUMBER() OVER (PARTITION BY cliente_id ORDER BY scored_at DESC) = 1
), subscriptions AS (
  SELECT s.cliente_id,
         COUNT(*) AS total_subscriptions,
         SUM(CASE WHEN upper(s.estado) IN ('ACTIVA','ACTIVE') THEN 1 ELSE 0 END) AS active_subscriptions,
         ROUND(SUM(CASE WHEN upper(s.estado) IN ('ACTIVA','ACTIVE') THEN s.precio_mensual_usd ELSE 0 END), 2) AS monthly_revenue
  FROM {fq}.silver_suscripciones s
  GROUP BY s.cliente_id
), tickets AS (
  SELECT cliente_id,
         COUNT(*) AS total_tickets,
         SUM(CASE WHEN upper(estado) NOT IN ('CERRADO','CLOSED','RESUELTO','RESOLVED') THEN 1 ELSE 0 END) AS open_tickets,
         ROUND(AVG(tiempo_resolucion_horas), 1) AS avg_resolution_hours,
         ROUND(AVG(csat_score), 1) AS support_csat,
         SUM(CASE WHEN recontacto THEN 1 ELSE 0 END) AS recontacts,
         MAX(fecha_creacion) AS last_ticket_at
  FROM {fq}.silver_tickets
  GROUP BY cliente_id
), billing AS (
  SELECT cliente_id,
         ROUND(SUM(monto_total_usd), 2) AS billed_total,
         ROUND(SUM(CASE WHEN upper(estado_pago) IN ('VENCIDA','OVERDUE') THEN monto_total_usd ELSE 0 END), 2) AS overdue_balance,
         SUM(CASE WHEN upper(estado_pago) IN ('VENCIDA','OVERDUE') THEN 1 ELSE 0 END) AS overdue_invoices,
         MAX(fecha_emision) AS last_invoice_at
  FROM {fq}.silver_facturas
  GROUP BY cliente_id
), cdr_anchor AS (
  SELECT MAX(fecha_hora) AS max_ts FROM {fq}.silver_cdrs
), experience AS (
  SELECT c.cliente_id,
         ROUND(AVG(c.`calidad_señal_dbm`), 1) AS avg_signal_dbm_30d,
         ROUND(100 * AVG(CASE WHEN c.llamada_caida THEN 1D ELSE 0D END), 2) AS dropped_call_pct_30d,
         ROUND(SUM(c.datos_mb) / 1024, 1) AS data_gb_30d,
         COUNT(*) AS network_events_30d,
         MAX(c.fecha_hora) AS last_network_event_at
  FROM {fq}.silver_cdrs c CROSS JOIN cdr_anchor a
  WHERE c.fecha_hora >= a.max_ts - INTERVAL 30 DAYS
  GROUP BY c.cliente_id
)
SELECT c.cliente_id,
       c.nombre_completo, c.email, c.telefono, c.pais_codigo, c.segmento_id,
       sg.segmento_nombre, sg.marca_comercial, c.estado, c.fecha_alta, c.antiguedad_dias,
       c.edad, c.credit_score, c.nps_ultimo, c.canal_adquisicion, c.acepta_marketing,
       COALESCE(s.total_subscriptions, 0) AS total_subscriptions,
       COALESCE(s.active_subscriptions, 0) AS active_subscriptions,
       COALESCE(s.monthly_revenue, 0) AS monthly_revenue,
       ch.churn_probability, ch.risk_tier, ch.scored_at AS churn_scored_at,
       clv.revenue_lifetime_est, clv.segment_name AS clv_segment, clv.scored_at AS clv_scored_at,
       COALESCE(t.total_tickets, 0) AS total_tickets,
       COALESCE(t.open_tickets, 0) AS open_tickets,
       t.avg_resolution_hours, t.support_csat, COALESCE(t.recontacts, 0) AS recontacts, t.last_ticket_at,
       COALESCE(b.billed_total, 0) AS billed_total,
       COALESCE(b.overdue_balance, 0) AS overdue_balance,
       COALESCE(b.overdue_invoices, 0) AS overdue_invoices, b.last_invoice_at,
       e.avg_signal_dbm_30d, e.dropped_call_pct_30d, e.data_gb_30d,
       COALESCE(e.network_events_30d, 0) AS network_events_30d, e.last_network_event_at,
       sla.policy_name AS sla_policy_name,
       sla.first_response_target_hours, sla.resolution_target_hours, sla.service_target_pct,
       sla.business_hours_per_day AS sla_business_hours_per_day, sla.business_days AS sla_business_days,
       sla.timezone AS sla_timezone, sla.breach_credit_pct AS sla_breach_credit_pct,
       sla.contractual AS sla_contractual, sla.policy_source AS sla_policy_source, sla.contract_id AS sla_contract_id
FROM {fq}.silver_clientes c
LEFT JOIN {fq}.bronze_segmentos sg ON c.segmento_id = sg.segmento_id
LEFT JOIN subscriptions s ON c.cliente_id = s.cliente_id
LEFT JOIN latest_churn ch ON c.cliente_id = ch.cliente_id
LEFT JOIN latest_clv clv ON c.cliente_id = clv.cliente_id
LEFT JOIN tickets t ON c.cliente_id = t.cliente_id
LEFT JOIN billing b ON c.cliente_id = b.cliente_id
LEFT JOIN experience e ON c.cliente_id = e.cliente_id
LEFT JOIN {fq}.ops_customer_sla_effective sla ON c.cliente_id = sla.customer_id
""")

sql(f"""
CREATE OR REPLACE VIEW {fq}.ops_customer_next_best_offer
COMMENT 'Ofertas explicáveis por cliente, excluindo planos já contratados e respeitando o segmento'
AS
WITH existing AS (
  SELECT s.cliente_id,
         collect_set(s.plan_id) AS plan_ids,
         collect_set(p.vertical) AS verticals,
         MAX(CASE WHEN p.es_bundle THEN 1 ELSE 0 END) AS has_bundle,
         SUM(CASE WHEN upper(s.estado) IN ('ACTIVA','ACTIVE') THEN s.precio_mensual_usd ELSE 0 END) AS monthly_spend
  FROM {fq}.silver_suscripciones s
  LEFT JOIN {fq}.bronze_planes p ON s.plan_id = p.plan_id
  WHERE upper(s.estado) IN ('ACTIVA','ACTIVE')
  GROUP BY s.cliente_id
), candidates AS (
  SELECT c.cliente_id, p.plan_id, p.nombre AS product_name, p.vertical, p.tier,
         p.precio_usd, p.es_bundle, p.data_gb, p.internet_mbps, p.minutos, p.tv_canales,
         CASE WHEN c.churn_probability >= 0.65 OR c.nps_ultimo <= 6 THEN 'RETENTION_OFFER'
              WHEN NOT COALESCE(array_contains(e.verticals, p.vertical), false) THEN 'CROSS_SELL'
              ELSE 'UPSELL' END AS recommendation_type,
         40
           + CASE WHEN NOT COALESCE(array_contains(e.verticals, p.vertical), false) THEN 25 ELSE 0 END
           + CASE WHEN p.es_bundle AND COALESCE(e.has_bundle, 0) = 0 THEN 20 ELSE 0 END
           + CASE WHEN p.precio_usd <= GREATEST(COALESCE(e.monthly_spend, 0) * 0.75, 25) THEN 10 ELSE 0 END
           + CASE WHEN c.acepta_marketing THEN 5 ELSE 0 END AS recommendation_score,
         concat_ws(' · ',
           CASE WHEN NOT COALESCE(array_contains(e.verticals, p.vertical), false) THEN concat('Amplía el portafolio con ', p.vertical) END,
           CASE WHEN p.es_bundle AND COALESCE(e.has_bundle, 0) = 0 THEN 'Consolida servicios en un bundle' END,
           CASE WHEN c.churn_probability >= 0.65 OR c.nps_ultimo <= 6 THEN 'Requiere tratamiento de retención antes de venta' END,
           CASE WHEN NOT c.acepta_marketing THEN 'Consentimiento comercial no disponible' END
         ) AS reason,
         c.acepta_marketing AS marketing_eligible
  FROM {fq}.ops_customer_360 c
  LEFT JOIN existing e ON c.cliente_id = e.cliente_id
  CROSS JOIN {fq}.bronze_planes p
  WHERE p.segmento = c.segmento_id
    AND NOT COALESCE(array_contains(e.plan_ids, p.plan_id), false)
)
SELECT * FROM candidates
QUALIFY ROW_NUMBER() OVER (PARTITION BY cliente_id ORDER BY recommendation_score DESC, precio_usd) <= 3
""")

sql(f"OPTIMIZE {fq}.ops_incident_state ZORDER BY (incident_id)")
sql(f"OPTIMIZE {fq}.ops_action_log ZORDER BY (incident_id, requested_at)")
sql(f"OPTIMIZE {fq}.ops_action_attempts ZORDER BY (action_id, started_at)")
sql(f"OPTIMIZE {fq}.ops_alert_events ZORDER BY (subscription_id, detected_at)")
sql(f"OPTIMIZE {fq}.ops_recommendation_log ZORDER BY (customer_id, proposed_at)")

from databricks.sdk import WorkspaceClient

app = WorkspaceClient().apps.get(app_name)
app_principal = app.service_principal_client_id
if app_principal:
    principal = f"`{app_principal}`"
    sql(f"GRANT USE CATALOG ON CATALOG `{catalog}` TO {principal}")
    sql(f"GRANT USE SCHEMA ON SCHEMA {fq} TO {principal}")
    sql(f"GRANT SELECT ON SCHEMA {fq} TO {principal}")
    for table in ("ops_incident_state", "ops_action_log", "ops_action_attempts", "ops_alert_subscriptions",
                  "ops_alert_events", "ops_audit_log", "ops_sla_policy", "ops_customer_sla_contract",
                  "ops_user_roles", "ops_recommendation_log"):
        sql(f"GRANT SELECT, MODIFY ON TABLE {fq}.`{table}` TO {principal}")

print(f"Quetzal operational model ready in {catalog}.{schema}")
