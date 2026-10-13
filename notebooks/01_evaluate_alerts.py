# Databricks notebook source
dbutils.widgets.text("catalog", "classic_stable_douglas_s_catalog")
dbutils.widgets.text("schema", "quetzal_telecom")

catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
assert catalog.replace("_", "").isalnum(), "invalid catalog"
assert schema.replace("_", "").isalnum(), "invalid schema"
fq = f"`{catalog}`.`{schema}`"

# One deterministic fingerprint per rule, market, metric and hour prevents alert storms.
spark.sql(f"""
MERGE INTO {fq}.ops_alert_events AS target
USING (
  WITH capacity AS (
    SELECT pais_codigo AS country, 'capacity_pct' AS metric,
           ROUND(AVG(avg_uso_capacidad_pct), 2) AS observed_value
    FROM {fq}.gold_network_health
    WHERE hora = (SELECT MAX(hora) FROM {fq}.gold_network_health)
    GROUP BY pais_codigo
  ), triggered AS (
    SELECT r.subscription_id, m.country, m.metric, m.observed_value, r.threshold,
           CASE WHEN m.observed_value >= r.threshold * 1.1 THEN 'CRITICAL' ELSE 'HIGH' END AS severity,
           CASE WHEN r.channel = 'IN_APP' THEN 'DELIVERED' ELSE 'PENDING_CONNECTOR' END AS notification_status
    FROM {fq}.ops_alert_subscriptions r JOIN capacity m ON r.metric = m.metric
    WHERE r.enabled = true AND (r.country IS NULL OR r.country = m.country)
      AND CASE r.operator WHEN '>' THEN m.observed_value > r.threshold
                          WHEN '>=' THEN m.observed_value >= r.threshold
                          WHEN '<' THEN m.observed_value < r.threshold
                          WHEN '<=' THEN m.observed_value <= r.threshold
                          WHEN '=' THEN m.observed_value = r.threshold ELSE false END
  )
  SELECT concat('ALT-', upper(substr(uuid(), 1, 12))) AS event_id, *,
         sha2(concat_ws(':', subscription_id, country, metric, date_format(current_timestamp(), 'yyyyMMddHH')), 256) AS fingerprint
  FROM triggered
) AS source
ON target.fingerprint = source.fingerprint
WHEN NOT MATCHED THEN INSERT (event_id, subscription_id, fingerprint, country, metric,
  observed_value, threshold, severity, status, notification_status, detected_at,
  notified_at, acknowledged_at, acknowledged_by, note)
VALUES (source.event_id, source.subscription_id, source.fingerprint, source.country, source.metric,
  source.observed_value, source.threshold, source.severity, 'OPEN', source.notification_status,
  current_timestamp(), CASE WHEN source.notification_status = 'DELIVERED' THEN current_timestamp() END,
  NULL, NULL, NULL)
""")

spark.sql(f"""
INSERT INTO {fq}.ops_audit_log
SELECT uuid(), 'ALERT_EVALUATION', 'alert_engine', 'scheduled', current_user(), current_timestamp(),
       to_json(named_struct('open_events', COUNT(*)))
FROM {fq}.ops_alert_events WHERE status = 'OPEN'
""")

print("Quetzal alert evaluation completed")
