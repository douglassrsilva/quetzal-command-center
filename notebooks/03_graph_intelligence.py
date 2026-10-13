# Databricks notebook source
# MAGIC %md
# MAGIC # Quetzal Graph Intelligence
# MAGIC
# MAGIC Deterministic, manually executed telecom relationship graph. The job keeps
# MAGIC only the latest qualified relationships/features/prediction snapshot and a compact run log.
# MAGIC Source plan: 300,000 synthetic calls across 60,000 existing customers, seed 42.

# COMMAND ----------

import re
from uuid import uuid4

dbutils.widgets.text("catalog", "classic_stable_douglas_s_catalog")
dbutils.widgets.text("schema", "quetzal_telecom")
dbutils.widgets.text("app_name", "quetzal-command-center")
dbutils.widgets.text("node_limit", "60000")
dbutils.widgets.text("edge_count", "300000")
dbutils.widgets.text("window_days", "90")
dbutils.widgets.text("seed", "42")
dbutils.widgets.text("relationship_slots", "3")
dbutils.widgets.text("min_contact_calls", "3")
dbutils.widgets.text("min_contact_minutes", "10")
dbutils.widgets.text("max_contact_recency_days", "60")
dbutils.widgets.text("workflow_run_id", "0")

catalog = dbutils.widgets.get("catalog")
schema = dbutils.widgets.get("schema")
app_name = dbutils.widgets.get("app_name")
node_limit = int(dbutils.widgets.get("node_limit"))
edge_count = int(dbutils.widgets.get("edge_count"))
window_days = int(dbutils.widgets.get("window_days"))
seed = int(dbutils.widgets.get("seed"))
relationship_slots = int(dbutils.widgets.get("relationship_slots"))
min_contact_calls = int(dbutils.widgets.get("min_contact_calls"))
min_contact_minutes = int(dbutils.widgets.get("min_contact_minutes"))
max_contact_recency_days = int(dbutils.widgets.get("max_contact_recency_days"))
workflow_run_id = int(dbutils.widgets.get("workflow_run_id") or "0")

identifier = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
if not identifier.fullmatch(catalog) or not identifier.fullmatch(schema):
    raise ValueError("Invalid catalog or schema identifier")
if not 1_000 <= node_limit <= 100_000:
    raise ValueError("node_limit must be between 1,000 and 100,000")
if not 10_000 <= edge_count <= 500_000:
    raise ValueError("edge_count must be between 10,000 and 500,000")
if not 30 <= window_days <= 365:
    raise ValueError("window_days must be between 30 and 365")
if not 1 <= relationship_slots <= 10:
    raise ValueError("relationship_slots must be between 1 and 10")
if not 2 <= min_contact_calls <= 20:
    raise ValueError("min_contact_calls must be between 2 and 20")
if not 1 <= min_contact_minutes <= 120:
    raise ValueError("min_contact_minutes must be between 1 and 120")
if not 7 <= max_contact_recency_days <= window_days:
    raise ValueError("max_contact_recency_days must be between 7 and window_days")

fq = f"`{catalog}`.`{schema}`"
run_id = uuid4().hex
tmp_rank_a = f"_tmp_graph_rank_a_{run_id[:12]}"
tmp_rank_b = f"_tmp_graph_rank_b_{run_id[:12]}"
tmp_risk_a = f"_tmp_graph_risk_a_{run_id[:12]}"
tmp_risk_b = f"_tmp_graph_risk_b_{run_id[:12]}"
tmp_label_a = f"_tmp_graph_label_a_{run_id[:12]}"
tmp_label_b = f"_tmp_graph_label_b_{run_id[:12]}"
tmp_edges = f"_tmp_graph_edges_{run_id[:12]}"
tmp_features = f"_tmp_graph_features_{run_id[:12]}"
tmp_predictions = f"_tmp_graph_predictions_{run_id[:12]}"
tmp_communities = f"_tmp_graph_communities_{run_id[:12]}"
tmp_triples = f"_tmp_graph_triples_{run_id[:12]}"


def sql(statement: str):
    return spark.sql(statement)


def drop_intermediate_tables():
    for table in (
        tmp_rank_a, tmp_rank_b, tmp_risk_a, tmp_risk_b, tmp_label_a, tmp_label_b,
        tmp_edges, tmp_features, tmp_predictions, tmp_communities, tmp_triples,
    ):
        sql(f"DROP TABLE IF EXISTS {fq}.`{table}`")


sql(f"CREATE SCHEMA IF NOT EXISTS {fq}")
sql(f"USE CATALOG `{catalog}`")
sql(f"USE SCHEMA `{schema}`")

sql(f"""
CREATE TABLE IF NOT EXISTS {fq}.ops_graph_run_log (
  run_id STRING NOT NULL,
  status STRING NOT NULL,
  started_at TIMESTAMP NOT NULL,
  completed_at TIMESTAMP,
  window_days INT NOT NULL,
  requested_node_count BIGINT NOT NULL,
  requested_edge_count BIGINT NOT NULL,
  node_count BIGINT,
  edge_count BIGINT,
  feature_count BIGINT,
  prediction_count BIGINT,
  community_count BIGINT,
  triple_count BIGINT,
  model_version STRING,
  workflow_run_id BIGINT,
  published_at TIMESTAMP,
  error_message STRING,
  generation_seed INT NOT NULL
) USING DELTA
TBLPROPERTIES ('delta.enableChangeDataFeed' = 'true')
""")

# Existing demo environments can contain the v1/v2 log schema. Evolve it
# idempotently so the App can bind a workflow run to the exact semantic
# snapshot and never report a false-positive success.
run_log_columns = set(spark.table(f"{catalog}.{schema}.ops_graph_run_log").columns)
for column_name, data_type in (
    ("triple_count", "BIGINT"),
    ("model_version", "STRING"),
    ("workflow_run_id", "BIGINT"),
    ("published_at", "TIMESTAMP"),
):
    if column_name not in run_log_columns:
        sql(f"ALTER TABLE {fq}.ops_graph_run_log ADD COLUMNS ({column_name} {data_type})")

sql(f"""
INSERT INTO {fq}.ops_graph_run_log
  (run_id, status, started_at, completed_at, window_days,
   requested_node_count, requested_edge_count, node_count, edge_count,
   feature_count, prediction_count, community_count, triple_count,
   model_version, workflow_run_id, published_at, error_message, generation_seed)
VALUES ('{run_id}', 'RUNNING', current_timestamp(), NULL, {window_days}, {node_limit},
        {edge_count}, NULL, NULL, NULL, NULL, NULL, NULL,
        'graph-intelligence-v3-ontobricks', {workflow_run_id}, NULL, NULL, {seed})
""")

# COMMAND ----------

try:
    # Stable sample of active customers. Country and segment affinity make the
    # generated graph useful for community detection while retaining 8% of
    # cross-border calls.
    sql(f"""
    CREATE OR REPLACE TEMP VIEW graph_nodes_base AS
    WITH selected AS (
      SELECT cliente_id, pais_codigo, segmento_id
      FROM {fq}.silver_clientes
      WHERE upper(estado) IN ('ACTIVO', 'ACTIVA', 'ACTIVE')
        AND cliente_id IS NOT NULL AND pais_codigo IS NOT NULL AND segmento_id IS NOT NULL
      ORDER BY xxhash64(cliente_id, {seed})
      LIMIT {node_limit}
    )
    SELECT cliente_id,
           pais_codigo,
           segmento_id,
           row_number() OVER (ORDER BY xxhash64(cliente_id, {seed})) - 1 AS node_idx,
           row_number() OVER (PARTITION BY pais_codigo ORDER BY xxhash64(cliente_id, {seed + 1})) - 1 AS country_idx,
           count(*) OVER (PARTITION BY pais_codigo) AS country_count,
           row_number() OVER (PARTITION BY pais_codigo, segmento_id ORDER BY xxhash64(cliente_id, {seed + 2})) - 1 AS affinity_idx,
           count(*) OVER (PARTITION BY pais_codigo, segmento_id) AS affinity_count
    FROM selected
    """)

    sql("""
    CREATE OR REPLACE TEMP VIEW graph_countries AS
    SELECT pais_codigo,
           dense_rank() OVER (ORDER BY pais_codigo) - 1 AS country_ord,
           count(*) AS country_count
    FROM graph_nodes_base
    GROUP BY pais_codigo
    """)

    sql("""
    CREATE OR REPLACE TEMP VIEW graph_nodes AS
    SELECT n.*, c.country_ord, t.country_total
    FROM graph_nodes_base n
    JOIN graph_countries c USING (pais_codigo)
    CROSS JOIN (SELECT count(*) AS country_total FROM graph_countries) t
    """)

    node_count = sql("SELECT count(*) AS n FROM graph_nodes").first()["n"]
    if node_count < 1_000:
        raise RuntimeError(f"Insufficient eligible customers: {node_count}")

    # Each range row is one synthetic call. Calls are distributed over a small,
    # stable set of relationship slots per subscriber so repeated interactions
    # can qualify a relationship. Routes are deterministic: 65% within
    # country+segment, 27% elsewhere in-country and 8% cross-border.
    sql(f"""
    CREATE OR REPLACE TABLE {fq}.`{tmp_edges}`
    USING DELTA
    TBLPROPERTIES (
      'delta.enableChangeDataFeed' = 'true',
      'comment' = 'Synthetic directed subscriber call relationships for Quetzal Graph Intelligence'
    ) AS
    WITH events AS (
      SELECT id AS event_id,
             pmod(xxhash64(id, {seed}), {node_count}) AS source_idx,
             pmod(xxhash64(id, {seed + 5}), {relationship_slots}) AS relationship_slot,
             xxhash64(id, {seed + 30}) AS attribute_hash
      FROM range({edge_count})
    ), sourced AS (
      SELECT e.*, s.*,
             pmod(xxhash64(s.cliente_id, e.relationship_slot, {seed + 10}), 100) AS route_bucket,
             xxhash64(s.cliente_id, e.relationship_slot, {seed + 20}) AS destination_hash
      FROM events e JOIN graph_nodes s ON e.source_idx = s.node_idx
    ), routed AS (
      SELECT *,
             CASE
               WHEN route_bucket < 65 AND affinity_count > 1 THEN 'AFFINITY'
               WHEN route_bucket < 92 THEN 'DOMESTIC'
               ELSE 'CROSS_BORDER'
             END AS route_type
      FROM sourced
    ), affinity_calls AS (
      SELECT s.event_id, s.cliente_id AS source_customer_id,
             d.cliente_id AS destination_customer_id,
             s.pais_codigo AS source_country_code,
             d.pais_codigo AS destination_country_code,
             s.attribute_hash, s.route_type
      FROM routed s
      JOIN graph_nodes d
        ON s.route_type = 'AFFINITY'
       AND d.pais_codigo = s.pais_codigo
       AND d.segmento_id = s.segmento_id
       AND d.affinity_idx = pmod(s.affinity_idx + 1 + pmod(s.destination_hash, s.affinity_count - 1), s.affinity_count)
    ), domestic_calls AS (
      SELECT s.event_id, s.cliente_id AS source_customer_id,
             d.cliente_id AS destination_customer_id,
             s.pais_codigo AS source_country_code,
             d.pais_codigo AS destination_country_code,
             s.attribute_hash, s.route_type
      FROM routed s
      JOIN graph_nodes d
        ON s.route_type = 'DOMESTIC'
       AND d.pais_codigo = s.pais_codigo
       AND d.country_idx = pmod(s.country_idx + 1 + pmod(s.destination_hash, s.country_count - 1), s.country_count)
    ), cross_routes AS (
      SELECT s.*, c.pais_codigo AS target_country_code, c.country_count AS target_country_count
      FROM routed s
      JOIN graph_countries c
        ON s.route_type = 'CROSS_BORDER'
       AND c.country_ord = pmod(s.country_ord + 1 + pmod(s.destination_hash, s.country_total - 1), s.country_total)
    ), cross_calls AS (
      SELECT s.event_id, s.cliente_id AS source_customer_id,
             d.cliente_id AS destination_customer_id,
             s.pais_codigo AS source_country_code,
             d.pais_codigo AS destination_country_code,
             s.attribute_hash, s.route_type
      FROM cross_routes s
      JOIN graph_nodes d
        ON d.pais_codigo = s.target_country_code
       AND d.country_idx = pmod(s.destination_hash, s.target_country_count)
    ), all_calls AS (
      SELECT * FROM affinity_calls
      UNION ALL SELECT * FROM domestic_calls
      UNION ALL SELECT * FROM cross_calls
    ), enriched AS (
      SELECT concat('CALL-', lpad(cast(event_id AS STRING), 12, '0')) AS call_edge_id,
             source_customer_id,
             destination_customer_id,
             source_country_code,
             destination_country_code,
             timestampadd(MINUTE, -pmod(attribute_hash, {window_days * 1440}), current_timestamp()) AS occurred_at,
             CASE
               WHEN pmod(attribute_hash, 100) < 55 THEN 10 + pmod(attribute_hash, 171)
               WHEN pmod(attribute_hash, 100) < 90 THEN 181 + pmod(attribute_hash, 720)
               ELSE 901 + pmod(attribute_hash, 2700)
             END AS duration_seconds,
             CASE WHEN pmod(attribute_hash, 1000) <
               CASE WHEN pmod(attribute_hash, 100) >= 95 THEN 65 ELSE 25 END
               THEN true ELSE false END AS dropped,
             CASE WHEN pmod(attribute_hash, 100) < 45 THEN '5G'
                  WHEN pmod(attribute_hash, 100) < 95 THEN '4G' ELSE '3G' END AS technology,
             CASE WHEN source_country_code <> destination_country_code
                       THEN pmod(attribute_hash, 100) < 45
                  ELSE pmod(attribute_hash, 1000) < 10 END AS roaming,
             source_country_code <> destination_country_code AS international,
             CASE route_type WHEN 'AFFINITY' THEN 'FREQUENT'
                  WHEN 'CROSS_BORDER' THEN 'CROSS_BORDER' ELSE 'OTHER' END AS contact_affinity,
             'QUETZAL_SYNTHETIC_CDR' AS source_system,
             current_timestamp() AS generated_at,
             '{run_id}' AS run_id
      FROM all_calls
    )
    SELECT * FROM enriched
    """)

    generated_call_count = sql(f"SELECT count(*) AS n FROM {fq}.`{tmp_edges}`").first()["n"]
    if generated_call_count != edge_count:
        raise RuntimeError(f"Expected {edge_count} calls, generated {generated_call_count}")

    # Aggregate all interactions first, then retain only meaningful and recent
    # relationships. Recurrence, accumulated duration or reciprocity can each
    # establish a relationship; isolated one-off calls no longer create edges.
    sql(f"""
    CREATE OR REPLACE TEMP VIEW graph_directed_all AS
    SELECT source_customer_id, destination_customer_id,
           count(*) AS calls,
           round(sum(duration_seconds) / 60.0, 1) AS minutes,
           round(100 * avg(CASE WHEN dropped THEN 1D ELSE 0D END), 1) AS dropped_pct,
           max(CASE WHEN international THEN 1 ELSE 0 END) = 1 AS international,
           max(contact_affinity) AS affinity,
           max(occurred_at) AS last_contact_at
    FROM {fq}.`{tmp_edges}`
    GROUP BY source_customer_id, destination_customer_id
    """)
    sql("""
    CREATE OR REPLACE TEMP VIEW graph_undirected_all AS
    SELECT least(source_customer_id, destination_customer_id) AS node_a,
           greatest(source_customer_id, destination_customer_id) AS node_b,
           sum(calls) AS calls,
           round(sum(minutes), 1) AS minutes,
           round(sum(dropped_pct * calls) / sum(calls), 1) AS dropped_pct,
           max(CASE WHEN international THEN 1 ELSE 0 END) = 1 AS international,
           max(affinity) AS affinity,
           max(last_contact_at) AS last_contact_at,
           count(DISTINCT concat(source_customer_id, '>', destination_customer_id)) = 2 AS reciprocal
    FROM graph_directed_all
    WHERE source_customer_id <> destination_customer_id
    GROUP BY least(source_customer_id, destination_customer_id),
             greatest(source_customer_id, destination_customer_id)
    """)
    sql(f"""
    CREATE OR REPLACE TEMP VIEW graph_undirected AS
    SELECT *,
           CASE WHEN reciprocal THEN 'RECIPROCAL'
                WHEN calls >= {min_contact_calls} THEN 'RECURRING_CALLS'
                ELSE 'ACCUMULATED_DURATION' END AS qualification_reason,
           round(exp(-datediff(current_timestamp(), last_contact_at) / 45D), 4) AS recency_weight,
           round((0.45D * ln(1D + calls) + 0.35D * ln(1D + minutes)
                 + 0.20D * CASE WHEN reciprocal THEN 1D ELSE 0D END)
                 * exp(-datediff(current_timestamp(), last_contact_at) / 45D)
                 * CASE WHEN reciprocal THEN 1.15D ELSE 1D END, 6) AS relationship_weight
    FROM graph_undirected_all
    WHERE (calls >= {min_contact_calls} OR minutes >= {min_contact_minutes} OR reciprocal)
      AND last_contact_at >= current_timestamp() - INTERVAL {max_contact_recency_days} DAYS
    """)
    sql("""
    CREATE OR REPLACE TEMP VIEW graph_directed AS
    SELECT d.*
    FROM graph_directed_all d
    JOIN graph_undirected q
      ON least(d.source_customer_id, d.destination_customer_id) = q.node_a
     AND greatest(d.source_customer_id, d.destination_customer_id) = q.node_b
    """)

    sql("""
    CREATE OR REPLACE TEMP VIEW graph_weighted_arcs AS
    SELECT node_a AS source, node_b AS destination, relationship_weight FROM graph_undirected
    UNION ALL
    SELECT node_b AS source, node_a AS destination, relationship_weight FROM graph_undirected
    """)
    sql("""
    CREATE OR REPLACE TEMP VIEW graph_neighbours AS
    SELECT source AS node, destination AS neighbour, relationship_weight
    FROM graph_weighted_arcs
    """)
    sql("""
    CREATE OR REPLACE TEMP VIEW graph_out_strength AS
    SELECT source AS customer_id, sum(relationship_weight) AS out_strength
    FROM graph_weighted_arcs GROUP BY source
    """)
    sql(f"""
    CREATE OR REPLACE TEMP VIEW graph_latest_churn AS
    SELECT cliente_id AS customer_id, churn_probability, gasto_mensual_total, scored_at
    FROM {fq}.gold_churn_predictions
    QUALIFY row_number() OVER (PARTITION BY cliente_id ORDER BY scored_at DESC) = 1
    """)

    # Serverless Spark Connect intentionally does not support DataFrame.cache().
    # Materializing bounded intermediate Delta tables keeps each iteration's
    # logical plan small and is cleaned up before the run completes. PageRank
    # measures weighted reach; it is never interpreted as churn probability.
    sql(f"""
    CREATE OR REPLACE TABLE {fq}.`{tmp_rank_a}` USING DELTA AS
    SELECT cliente_id AS customer_id, 1D / {node_count} AS weighted_pagerank FROM graph_nodes
    """)
    current_rank, next_rank = tmp_rank_a, tmp_rank_b
    for _ in range(10):
        sql(f"""
        CREATE OR REPLACE TABLE {fq}.`{next_rank}` USING DELTA AS
        SELECT n.cliente_id AS customer_id,
               0.15D / {node_count} + 0.85D * coalesce(
                 sum(r.weighted_pagerank * e.relationship_weight / o.out_strength), 0D
               ) AS weighted_pagerank
        FROM graph_nodes n
        LEFT JOIN graph_weighted_arcs e ON n.cliente_id = e.destination
        LEFT JOIN {fq}.`{current_rank}` r ON e.source = r.customer_id
        LEFT JOIN graph_out_strength o ON e.source = o.customer_id
        GROUP BY n.cliente_id
        """)
        current_rank, next_rank = next_rank, current_rank
    sql(f"CREATE OR REPLACE TEMP VIEW graph_pagerank AS SELECT * FROM {fq}.`{current_rank}`")

    # Personalized PageRank diffuses *where* governed high-risk seeds sit in
    # the relationship graph. It is an exposure signal, not a second churn
    # model and not evidence that churn is socially contagious.
    sql(f"""
    CREATE OR REPLACE TEMP VIEW graph_risk_seeds AS
    WITH raw AS (
      SELECT n.cliente_id AS customer_id,
             greatest(coalesce(c.churn_probability, 0D) - 0.50D, 0D) AS risk_seed
      FROM graph_nodes n LEFT JOIN graph_latest_churn c ON n.cliente_id = c.customer_id
    ), totals AS (
      SELECT *, sum(risk_seed) OVER () AS total_seed FROM raw
    )
    SELECT customer_id,
           CASE WHEN total_seed > 0D THEN risk_seed / total_seed ELSE 1D / {node_count} END AS seed_mass
    FROM totals
    """)
    sql(f"""
    CREATE OR REPLACE TABLE {fq}.`{tmp_risk_a}` USING DELTA AS
    SELECT customer_id, seed_mass AS risk_diffusion FROM graph_risk_seeds
    """)
    current_risk, next_risk = tmp_risk_a, tmp_risk_b
    for _ in range(10):
        sql(f"""
        CREATE OR REPLACE TABLE {fq}.`{next_risk}` USING DELTA AS
        SELECT n.cliente_id AS customer_id,
               0.15D * s.seed_mass + 0.85D * coalesce(
                 sum(r.risk_diffusion * e.relationship_weight / o.out_strength), 0D
               ) AS risk_diffusion
        FROM graph_nodes n
        JOIN graph_risk_seeds s ON n.cliente_id = s.customer_id
        LEFT JOIN graph_weighted_arcs e ON n.cliente_id = e.destination
        LEFT JOIN {fq}.`{current_risk}` r ON e.source = r.customer_id
        LEFT JOIN graph_out_strength o ON e.source = o.customer_id
        GROUP BY n.cliente_id, s.seed_mass
        """)
        current_risk, next_risk = next_risk, current_risk
    sql(f"CREATE OR REPLACE TEMP VIEW graph_risk_diffusion AS SELECT * FROM {fq}.`{current_risk}`")

    sql(f"""
    CREATE OR REPLACE TABLE {fq}.`{tmp_label_a}` USING DELTA AS
    SELECT cliente_id AS node, cliente_id AS label FROM graph_nodes
    """)
    current_label, next_label = tmp_label_a, tmp_label_b
    for _ in range(5):
        sql(f"""
        CREATE OR REPLACE TABLE {fq}.`{next_label}` USING DELTA AS
        WITH votes AS (
          SELECT e.node, l.label, sum(e.relationship_weight) AS votes
          FROM graph_neighbours e
          JOIN {fq}.`{current_label}` l ON e.neighbour = l.node
          GROUP BY e.node, l.label
        ), choices AS (
          SELECT node, label,
                 row_number() OVER (PARTITION BY node ORDER BY votes DESC, label) AS choice
          FROM votes
        )
        SELECT n.cliente_id AS node, coalesce(c.label, n.cliente_id) AS label
        FROM graph_nodes n LEFT JOIN choices c ON n.cliente_id = c.node AND c.choice = 1
        """)
        current_label, next_label = next_label, current_label
    sql(f"""
    CREATE OR REPLACE TEMP VIEW graph_communities AS
    SELECT node, concat('COM-', substring(sha2(label, 256), 1, 10)) AS community_id
    FROM {fq}.`{current_label}`
    """)

    # Exact local triangles; the approved graph has a bounded average degree,
    # keeping this self-join predictable on manual serverless compute.
    sql("""
    CREATE OR REPLACE TEMP VIEW graph_triangles AS
    SELECT l.node, count(*) AS triangle_count
    FROM graph_neighbours l
    JOIN graph_neighbours r
      ON l.node = r.node AND l.neighbour < r.neighbour
    JOIN graph_undirected edge
      ON l.neighbour = edge.node_a AND r.neighbour = edge.node_b
    GROUP BY l.node
    """)

    # Feature snapshot. All scores retain their underlying components so the
    # application and Quetzal IQ can explain why a customer was prioritized.
    sql(f"""
    CREATE OR REPLACE TABLE {fq}.`{tmp_features}`
    USING DELTA
    TBLPROPERTIES (
      'delta.enableChangeDataFeed' = 'true',
      'comment' = 'Governed relationship features for Quetzal customer intelligence'
    ) AS
    WITH latest_churn AS (
      SELECT customer_id AS cliente_id, churn_probability, gasto_mensual_total, scored_at
      FROM graph_latest_churn
    ), outbound AS (
      SELECT source_customer_id AS customer_id, count(*) AS out_degree,
             sum(calls) AS outbound_calls,
             round(sum(minutes), 1) AS outbound_minutes,
             round(100 * sum(CASE WHEN international THEN calls ELSE 0 END) / sum(calls), 1) AS international_call_pct
      FROM graph_directed GROUP BY source_customer_id
    ), inbound AS (
      SELECT destination_customer_id AS customer_id, count(*) AS in_degree,
             sum(calls) AS inbound_calls, round(sum(minutes), 1) AS inbound_minutes
      FROM graph_directed GROUP BY destination_customer_id
    ), contacts AS (
      SELECT node_a AS customer_id, node_b AS peer_id, calls, minutes, dropped_pct, international, affinity,
             reciprocal, last_contact_at, qualification_reason, recency_weight, relationship_weight
      FROM graph_undirected
      UNION ALL
      SELECT node_b AS customer_id, node_a AS peer_id, calls, minutes, dropped_pct, international, affinity,
             reciprocal, last_contact_at, qualification_reason, recency_weight, relationship_weight
      FROM graph_undirected
    ), contact_stats AS (
      SELECT c.customer_id,
             count(*) AS unique_contacts,
             sum(c.calls) AS total_calls,
             round(sum(c.minutes), 1) AS total_minutes,
             round(sum(c.dropped_pct * c.calls) / sum(c.calls), 1) AS dropped_call_pct,
             count(DISTINCT p.pais_codigo) AS countries_reached,
             round(sum(coalesce(pc.churn_probability, 0) * c.relationship_weight)
                   / sum(c.relationship_weight), 4) AS neighbour_avg_churn_probability,
             round(100 * sum(CASE WHEN pc.churn_probability >= 0.65 THEN c.relationship_weight ELSE 0 END)
                   / sum(c.relationship_weight), 1) AS high_risk_neighbour_pct,
             round(sum(coalesce(pc.gasto_mensual_total, 0)), 2) AS influenced_revenue_usd
      FROM contacts c
      LEFT JOIN latest_churn pc ON c.peer_id = pc.cliente_id
      LEFT JOIN {fq}.silver_clientes p ON c.peer_id = p.cliente_id
      GROUP BY c.customer_id
    ), reciprocal AS (
      SELECT a.source_customer_id AS customer_id, count(*) AS reciprocal_contacts
      FROM graph_directed a JOIN graph_directed b
        ON a.source_customer_id = b.destination_customer_id
       AND a.destination_customer_id = b.source_customer_id
      GROUP BY a.source_customer_id
    ), base AS (
      SELECT n.cliente_id AS customer_id,
             n.pais_codigo AS country,
             n.segmento_id AS segment_id,
             coalesce(i.in_degree, 0) + coalesce(o.out_degree, 0) AS degree,
             coalesce(i.in_degree, 0) AS in_degree,
             coalesce(o.out_degree, 0) AS out_degree,
             coalesce(c.unique_contacts, 0) AS unique_contacts,
             coalesce(r.reciprocal_contacts, 0) AS reciprocal_contacts,
             coalesce(c.countries_reached, 0) AS countries_reached,
             coalesce(o.international_call_pct, 0) AS international_call_pct,
             coalesce(c.total_calls, 0) AS total_calls,
             coalesce(c.total_minutes, 0) AS total_minutes,
             coalesce(c.dropped_call_pct, 0) AS dropped_call_pct,
             coalesce(p.weighted_pagerank, 0) AS weighted_pagerank,
             coalesce(rd.risk_diffusion, 0) AS risk_diffusion,
             coalesce(t.triangle_count, 0) AS triangle_count,
             CASE WHEN coalesce(c.unique_contacts, 0) >= 2
                  THEN round(2D * coalesce(t.triangle_count, 0) / (c.unique_contacts * (c.unique_contacts - 1)), 4)
                  ELSE 0D END AS clustering_coefficient,
             m.community_id,
             coalesce(c.neighbour_avg_churn_probability, 0) AS neighbour_avg_churn_probability,
             coalesce(c.high_risk_neighbour_pct, 0) AS high_risk_neighbour_pct,
             coalesce(c.influenced_revenue_usd, 0) AS influenced_revenue_usd,
             coalesce(bc.churn_probability, 0) AS baseline_churn_probability,
             bc.scored_at AS baseline_scored_at
      FROM graph_nodes n
      LEFT JOIN inbound i ON n.cliente_id = i.customer_id
      LEFT JOIN outbound o ON n.cliente_id = o.customer_id
      LEFT JOIN contact_stats c ON n.cliente_id = c.customer_id
      LEFT JOIN reciprocal r ON n.cliente_id = r.customer_id
      LEFT JOIN graph_pagerank p ON n.cliente_id = p.customer_id
      LEFT JOIN graph_risk_diffusion rd ON n.cliente_id = rd.customer_id
      LEFT JOIN graph_triangles t ON n.cliente_id = t.node
      LEFT JOIN graph_communities m ON n.cliente_id = m.node
      LEFT JOIN latest_churn bc ON n.cliente_id = bc.cliente_id
    ), normalized AS (
      SELECT *,
             percent_rank() OVER (ORDER BY weighted_pagerank) AS pagerank_rank,
             percent_rank() OVER (ORDER BY risk_diffusion) AS risk_diffusion_rank,
             percent_rank() OVER (ORDER BY degree) AS degree_rank,
             percent_rank() OVER (ORDER BY influenced_revenue_usd) AS revenue_rank,
             percent_rank() OVER (ORDER BY international_call_pct) AS international_rank,
             count(*) OVER (PARTITION BY community_id) AS community_size
      FROM base
    )
    SELECT customer_id, country, segment_id, degree, in_degree, out_degree,
           unique_contacts, reciprocal_contacts, countries_reached,
           international_call_pct, total_calls, total_minutes, dropped_call_pct,
           weighted_pagerank, weighted_pagerank AS pagerank,
           risk_diffusion, round(100 * risk_diffusion_rank, 1) AS risk_diffusion_score,
           triangle_count, clustering_coefficient,
           community_id, community_size,
           neighbour_avg_churn_probability, high_risk_neighbour_pct,
           influenced_revenue_usd,
           round(100 * (0.50 * pagerank_rank + 0.30 * degree_rank + 0.20 * revenue_rank), 1) AS reach_score,
           round(100 * (0.50 * high_risk_neighbour_pct / 100
                      + 0.35 * neighbour_avg_churn_probability
                      + 0.15 * risk_diffusion_rank), 1) AS network_exposure_score,
           round(100 * (0.45 * degree_rank + 0.35 * (1D - clustering_coefficient)
                      + 0.20 * international_rank), 1) AS bridge_score,
           round(100 * (0.50 * pagerank_rank + 0.30 * degree_rank + 0.20 * revenue_rank), 1) AS influence_score,
           round(100 * (0.50 * high_risk_neighbour_pct / 100
                      + 0.35 * neighbour_avg_churn_probability
                      + 0.15 * risk_diffusion_rank), 1) AS contagion_risk_score,
           baseline_churn_probability, baseline_scored_at,
           current_timestamp() - INTERVAL {window_days} DAYS AS window_start,
           current_timestamp() AS window_end,
           current_timestamp() AS computed_at,
           '{run_id}' AS run_id
    FROM normalized
    """)

    sql(f"""
    CREATE OR REPLACE TABLE {fq}.`{tmp_predictions}`
    USING DELTA
    TBLPROPERTIES (
      'delta.enableChangeDataFeed' = 'true',
      'comment' = 'Operational retention priority with baseline churn kept unchanged'
    ) AS
    WITH scored AS (
      SELECT customer_id, baseline_churn_probability,
             round(least(100D, greatest(0D,
               55D * baseline_churn_probability
               + 20D * network_exposure_score / 100D
               + 15D * reach_score / 100D
               + 10D * least(1D, influenced_revenue_usd / 1000D)
             )), 1) AS retention_priority_score,
             reach_score, network_exposure_score, risk_diffusion_score, bridge_score,
             influence_score, contagion_risk_score, community_id,
             high_risk_neighbour_pct, countries_reached, influenced_revenue_usd,
             baseline_scored_at
      FROM {fq}.`{tmp_features}`
    )
    SELECT customer_id,
           round(baseline_churn_probability, 4) AS baseline_churn_probability,
           round(baseline_churn_probability, 4) AS graph_churn_probability,
           0D AS graph_lift,
           retention_priority_score,
           CASE WHEN baseline_churn_probability >= 0.85 THEN 'CRITICAL'
                WHEN baseline_churn_probability >= 0.65 THEN 'HIGH'
                WHEN baseline_churn_probability >= 0.40 THEN 'MEDIUM' ELSE 'LOW' END AS risk_tier,
           reach_score, network_exposure_score, risk_diffusion_score, bridge_score,
           influence_score, contagion_risk_score, community_id,
           high_risk_neighbour_pct, countries_reached, influenced_revenue_usd,
           CASE WHEN baseline_churn_probability >= 0.80 AND retention_priority_score >= 70 THEN 'PRIORITY_RETENTION'
                WHEN network_exposure_score >= 65 THEN 'NETWORK_EXPOSURE_REVIEW'
                WHEN reach_score >= 80 THEN 'HIGH_REACH_CARE'
                WHEN baseline_churn_probability >= 0.65 THEN 'PROACTIVE_CONTACT' ELSE 'MONITOR' END AS recommended_action,
           filter(array(
             CASE WHEN high_risk_neighbour_pct >= 40 THEN 'HIGH_RISK_NETWORK_EXPOSURE' END,
             CASE WHEN reach_score >= 70 THEN 'HIGH_NETWORK_REACH' END,
             CASE WHEN risk_diffusion_score >= 70 THEN 'HIGH_RISK_DIFFUSION' END,
             CASE WHEN countries_reached >= 3 THEN 'CROSS_BORDER_REACH' END,
             CASE WHEN bridge_score >= 75 THEN 'RELATIONSHIP_BRIDGE' END
           ), x -> x IS NOT NULL) AS explanation_codes,
           'graph-intelligence-v3-ontobricks' AS model_version,
           baseline_scored_at,
           current_timestamp() AS scored_at,
           '{run_id}' AS run_id
    FROM scored
    """)

    sql(f"""
    CREATE OR REPLACE TABLE {fq}.`{tmp_communities}`
    USING DELTA
    TBLPROPERTIES ('comment' = 'Bounded community aggregates for the Quetzal graph explorer') AS
    SELECT f.community_id,
           concat_ws(',', sort_array(collect_set(f.country))) AS countries,
           count(*) AS customer_count,
           round(avg(p.graph_churn_probability), 4) AS avg_graph_churn_probability,
           sum(CASE WHEN p.risk_tier IN ('CRITICAL', 'HIGH') THEN 1 ELSE 0 END) AS high_risk_customers,
           round(avg(p.retention_priority_score), 1) AS avg_retention_priority_score,
           round(avg(f.reach_score), 1) AS avg_reach_score,
           round(avg(f.network_exposure_score), 1) AS avg_network_exposure_score,
           round(avg(f.influence_score), 1) AS avg_influence_score,
           round(max(f.influence_score), 1) AS max_influence_score,
           round(avg(f.contagion_risk_score), 1) AS avg_contagion_risk_score,
           round(sum(f.influenced_revenue_usd), 2) AS influenced_revenue_usd,
           round(avg(f.international_call_pct), 1) AS international_call_pct,
           round(15 + pmod(xxhash64(f.community_id, {seed + 50}), 7000) / 100D, 2) AS graph_x,
           round(15 + pmod(xxhash64(f.community_id, {seed + 60}), 7000) / 100D, 2) AS graph_y,
           max(f.computed_at) AS computed_at,
           '{run_id}' AS run_id
    FROM {fq}.`{tmp_features}` f
    JOIN {fq}.`{tmp_predictions}` p USING (customer_id, community_id)
    GROUP BY f.community_id
    """)

    # OntoBricks-compatible semantic projection. Raw CDR events remain in
    # Delta; the knowledge graph receives qualified relationships and business
    # entities only. Relationship reification preserves the attributes that a
    # plain (subject, predicate, object) edge would otherwise discard.
    sql(f"""
    CREATE OR REPLACE TABLE {fq}.`{tmp_triples}`
    USING DELTA
    TBLPROPERTIES (
      'delta.enableChangeDataFeed' = 'true',
      'comment' = 'OntoBricks-compatible Quetzal telecom knowledge graph triples'
    ) AS
    WITH customer_triples AS (
      SELECT concat('https://quetzal.demo/knowledge/customer/', customer_id) AS subject,
             'http://www.w3.org/1999/02/22-rdf-syntax-ns#type' AS predicate,
             'https://quetzal.demo/ontology/Customer' AS object,
             true AS object_is_iri, cast(NULL AS STRING) AS datatype,
             'gold_customer_graph_features' AS source_table
      FROM {fq}.`{tmp_features}`
      UNION ALL
      SELECT concat('https://quetzal.demo/knowledge/customer/', f.customer_id),
             'http://www.w3.org/2000/01/rdf-schema#label',
             concat(left(c.nombre_completo, 1), '•••', right(f.customer_id, 4)),
             false, 'http://www.w3.org/2001/XMLSchema#string', 'silver_clientes'
      FROM {fq}.`{tmp_features}` f
      JOIN {fq}.silver_clientes c ON f.customer_id = c.cliente_id
      UNION ALL
      SELECT concat('https://quetzal.demo/knowledge/customer/', customer_id),
             'https://quetzal.demo/ontology/locatedIn',
             concat('https://quetzal.demo/knowledge/country/', country),
             true, cast(NULL AS STRING), 'gold_customer_graph_features'
      FROM {fq}.`{tmp_features}`
      UNION ALL
      SELECT concat('https://quetzal.demo/knowledge/customer/', customer_id),
             'https://quetzal.demo/ontology/memberOfRelationshipGroup',
             concat('https://quetzal.demo/knowledge/group/', community_id),
             true, cast(NULL AS STRING), 'gold_customer_graph_features'
      FROM {fq}.`{tmp_features}` WHERE community_id IS NOT NULL
      UNION ALL
      SELECT DISTINCT concat('https://quetzal.demo/knowledge/country/', country),
             'http://www.w3.org/1999/02/22-rdf-syntax-ns#type',
             'https://quetzal.demo/ontology/Country',
             true, cast(NULL AS STRING), 'gold_customer_graph_features'
      FROM {fq}.`{tmp_features}`
      WHERE country IS NOT NULL
      UNION ALL
      SELECT DISTINCT concat('https://quetzal.demo/knowledge/country/', country),
             'http://www.w3.org/2000/01/rdf-schema#label', country,
             false, 'http://www.w3.org/2001/XMLSchema#string', 'gold_customer_graph_features'
      FROM {fq}.`{tmp_features}`
      WHERE country IS NOT NULL
      UNION ALL
      SELECT concat('https://quetzal.demo/knowledge/group/', community_id),
             'http://www.w3.org/1999/02/22-rdf-syntax-ns#type',
             'https://quetzal.demo/ontology/RelationshipGroup',
             true, cast(NULL AS STRING), 'gold_graph_community_summary'
      FROM {fq}.`{tmp_communities}`
      UNION ALL
      SELECT concat('https://quetzal.demo/knowledge/group/', community_id),
             'http://www.w3.org/2000/01/rdf-schema#label',
             concat('Grupo de relaciones ', community_id, ' · ', countries),
             false, 'http://www.w3.org/2001/XMLSchema#string', 'gold_graph_community_summary'
      FROM {fq}.`{tmp_communities}`
      UNION ALL
      SELECT concat('https://quetzal.demo/knowledge/customer/', customer_id),
             'https://quetzal.demo/ontology/baselineChurnProbability',
             cast(baseline_churn_probability AS STRING), false,
             'http://www.w3.org/2001/XMLSchema#double', 'gold_churn_predictions'
      FROM {fq}.`{tmp_predictions}`
      UNION ALL
      SELECT concat('https://quetzal.demo/knowledge/customer/', customer_id),
             'https://quetzal.demo/ontology/retentionPriorityScore',
             cast(retention_priority_score AS STRING), false,
             'http://www.w3.org/2001/XMLSchema#double', 'gold_churn_graph_predictions'
      FROM {fq}.`{tmp_predictions}`
      UNION ALL
      SELECT concat('https://quetzal.demo/knowledge/customer/', customer_id),
             'https://quetzal.demo/ontology/networkReachScore',
             cast(reach_score AS STRING), false,
             'http://www.w3.org/2001/XMLSchema#double', 'gold_customer_graph_features'
      FROM {fq}.`{tmp_features}`
      UNION ALL
      SELECT concat('https://quetzal.demo/knowledge/customer/', customer_id),
             'https://quetzal.demo/ontology/networkExposureScore',
             cast(network_exposure_score AS STRING), false,
             'http://www.w3.org/2001/XMLSchema#double', 'gold_customer_graph_features'
      FROM {fq}.`{tmp_features}`
    ), relationship_triples AS (
      SELECT concat('https://quetzal.demo/knowledge/customer/', node_a) AS subject,
             'https://quetzal.demo/ontology/qualifiedContact' AS predicate,
             concat('https://quetzal.demo/knowledge/customer/', node_b) AS object,
             true AS object_is_iri, cast(NULL AS STRING) AS datatype,
             'silver_customer_call_edges' AS source_table
      FROM graph_undirected
      UNION ALL
      SELECT concat('https://quetzal.demo/knowledge/relationship/', sha2(concat(node_a, '|', node_b), 256)),
             'http://www.w3.org/1999/02/22-rdf-syntax-ns#type',
             'https://quetzal.demo/ontology/QualifiedContact',
             true, cast(NULL AS STRING), 'silver_customer_call_edges'
      FROM graph_undirected
      UNION ALL
      SELECT concat('https://quetzal.demo/knowledge/relationship/', sha2(concat(node_a, '|', node_b), 256)),
             'https://quetzal.demo/ontology/contactSource',
             concat('https://quetzal.demo/knowledge/customer/', node_a),
             true, cast(NULL AS STRING), 'silver_customer_call_edges'
      FROM graph_undirected
      UNION ALL
      SELECT concat('https://quetzal.demo/knowledge/relationship/', sha2(concat(node_a, '|', node_b), 256)),
             'https://quetzal.demo/ontology/contactTarget',
             concat('https://quetzal.demo/knowledge/customer/', node_b),
             true, cast(NULL AS STRING), 'silver_customer_call_edges'
      FROM graph_undirected
      UNION ALL
      SELECT concat('https://quetzal.demo/knowledge/relationship/', sha2(concat(node_a, '|', node_b), 256)),
             'https://quetzal.demo/ontology/callCount', cast(calls AS STRING), false,
             'http://www.w3.org/2001/XMLSchema#long', 'silver_customer_call_edges'
      FROM graph_undirected
      UNION ALL
      SELECT concat('https://quetzal.demo/knowledge/relationship/', sha2(concat(node_a, '|', node_b), 256)),
             'https://quetzal.demo/ontology/contactMinutes', cast(minutes AS STRING), false,
             'http://www.w3.org/2001/XMLSchema#double', 'silver_customer_call_edges'
      FROM graph_undirected
      UNION ALL
      SELECT concat('https://quetzal.demo/knowledge/relationship/', sha2(concat(node_a, '|', node_b), 256)),
             'https://quetzal.demo/ontology/relationshipWeight', cast(relationship_weight AS STRING), false,
             'http://www.w3.org/2001/XMLSchema#double', 'silver_customer_call_edges'
      FROM graph_undirected
      UNION ALL
      SELECT concat('https://quetzal.demo/knowledge/relationship/', sha2(concat(node_a, '|', node_b), 256)),
             'https://quetzal.demo/ontology/isReciprocal', cast(reciprocal AS STRING), false,
             'http://www.w3.org/2001/XMLSchema#boolean', 'silver_customer_call_edges'
      FROM graph_undirected
      UNION ALL
      SELECT concat('https://quetzal.demo/knowledge/relationship/', sha2(concat(node_a, '|', node_b), 256)),
             'https://quetzal.demo/ontology/qualificationReason', qualification_reason, false,
             'http://www.w3.org/2001/XMLSchema#string', 'silver_customer_call_edges'
      FROM graph_undirected
    ), business_triples AS (
      SELECT concat('https://quetzal.demo/knowledge/customer/', s.cliente_id) AS subject,
             'https://quetzal.demo/ontology/subscribedTo' AS predicate,
             concat('https://quetzal.demo/knowledge/plan/', s.plan_id) AS object,
             true AS object_is_iri, cast(NULL AS STRING) AS datatype,
             'silver_suscripciones' AS source_table
      FROM {fq}.silver_suscripciones s
      JOIN {fq}.`{tmp_features}` f ON s.cliente_id = f.customer_id
      WHERE upper(s.estado) IN ('ACTIVA', 'ACTIVE')
      UNION ALL
      SELECT DISTINCT concat('https://quetzal.demo/knowledge/plan/', s.plan_id),
             'http://www.w3.org/1999/02/22-rdf-syntax-ns#type',
             'https://quetzal.demo/ontology/Plan', true, cast(NULL AS STRING), 'silver_suscripciones'
      FROM {fq}.silver_suscripciones s
      JOIN {fq}.`{tmp_features}` f ON s.cliente_id = f.customer_id
      WHERE upper(s.estado) IN ('ACTIVA', 'ACTIVE')
      UNION ALL
      SELECT DISTINCT concat('https://quetzal.demo/knowledge/plan/', s.plan_id),
             'http://www.w3.org/2000/01/rdf-schema#label',
             coalesce(p.nombre, s.plan_id), false,
             'http://www.w3.org/2001/XMLSchema#string', 'bronze_planes'
      FROM {fq}.silver_suscripciones s
      JOIN {fq}.`{tmp_features}` f ON s.cliente_id = f.customer_id
      LEFT JOIN {fq}.bronze_planes p ON s.plan_id = p.plan_id
      WHERE upper(s.estado) IN ('ACTIVA', 'ACTIVE')
      UNION ALL
      SELECT concat('https://quetzal.demo/knowledge/ticket/', t.ticket_id),
             'https://quetzal.demo/ontology/openedBy',
             concat('https://quetzal.demo/knowledge/customer/', t.cliente_id),
             true, cast(NULL AS STRING), 'silver_tickets'
      FROM {fq}.silver_tickets t
      JOIN {fq}.`{tmp_features}` f ON t.cliente_id = f.customer_id
      WHERE upper(t.estado) NOT IN ('CERRADO', 'CLOSED', 'RESUELTO', 'RESOLVED')
      UNION ALL
      SELECT concat('https://quetzal.demo/knowledge/ticket/', t.ticket_id),
             'http://www.w3.org/1999/02/22-rdf-syntax-ns#type',
             'https://quetzal.demo/ontology/Ticket',
             true, cast(NULL AS STRING), 'silver_tickets'
      FROM {fq}.silver_tickets t
      JOIN {fq}.`{tmp_features}` f ON t.cliente_id = f.customer_id
      WHERE upper(t.estado) NOT IN ('CERRADO', 'CLOSED', 'RESUELTO', 'RESOLVED')
      UNION ALL
      SELECT concat('https://quetzal.demo/knowledge/ticket/', t.ticket_id),
             'http://www.w3.org/2000/01/rdf-schema#label',
             concat('Ticket ', t.ticket_id), false,
             'http://www.w3.org/2001/XMLSchema#string', 'silver_tickets'
      FROM {fq}.silver_tickets t
      JOIN {fq}.`{tmp_features}` f ON t.cliente_id = f.customer_id
      WHERE upper(t.estado) NOT IN ('CERRADO', 'CLOSED', 'RESUELTO', 'RESOLVED')
      UNION ALL
      SELECT concat('https://quetzal.demo/knowledge/customer/', s.customer_id),
             'https://quetzal.demo/ontology/governedBySLA',
             concat('https://quetzal.demo/knowledge/sla/', sha2(s.policy_name, 256)),
             true, cast(NULL AS STRING), 'ops_customer_sla_effective'
      FROM {fq}.ops_customer_sla_effective s
      JOIN {fq}.`{tmp_features}` f ON s.customer_id = f.customer_id
      UNION ALL
      SELECT DISTINCT concat('https://quetzal.demo/knowledge/sla/', sha2(s.policy_name, 256)),
             'http://www.w3.org/1999/02/22-rdf-syntax-ns#type',
             'https://quetzal.demo/ontology/SLA',
             true, cast(NULL AS STRING), 'ops_customer_sla_effective'
      FROM {fq}.ops_customer_sla_effective s
      JOIN {fq}.`{tmp_features}` f ON s.customer_id = f.customer_id
      UNION ALL
      SELECT DISTINCT concat('https://quetzal.demo/knowledge/sla/', sha2(s.policy_name, 256)),
             'http://www.w3.org/2000/01/rdf-schema#label', s.policy_name,
             false, 'http://www.w3.org/2001/XMLSchema#string', 'ops_customer_sla_effective'
      FROM {fq}.ops_customer_sla_effective s
      JOIN {fq}.`{tmp_features}` f ON s.customer_id = f.customer_id
      UNION ALL
      SELECT concat('https://quetzal.demo/knowledge/recommendation/', r.recommendation_id),
             'https://quetzal.demo/ontology/proposedFor',
             concat('https://quetzal.demo/knowledge/customer/', r.customer_id),
             true, cast(NULL AS STRING), 'ops_recommendation_log'
      FROM {fq}.ops_recommendation_log r
      JOIN {fq}.`{tmp_features}` f ON r.customer_id = f.customer_id
      UNION ALL
      SELECT concat('https://quetzal.demo/knowledge/recommendation/', r.recommendation_id),
             'http://www.w3.org/1999/02/22-rdf-syntax-ns#type',
             'https://quetzal.demo/ontology/Recommendation',
             true, cast(NULL AS STRING), 'ops_recommendation_log'
      FROM {fq}.ops_recommendation_log r
      JOIN {fq}.`{tmp_features}` f ON r.customer_id = f.customer_id
      UNION ALL
      SELECT concat('https://quetzal.demo/knowledge/recommendation/', r.recommendation_id),
             'http://www.w3.org/2000/01/rdf-schema#label', r.title,
             false, 'http://www.w3.org/2001/XMLSchema#string', 'ops_recommendation_log'
      FROM {fq}.ops_recommendation_log r
      JOIN {fq}.`{tmp_features}` f ON r.customer_id = f.customer_id
      UNION ALL
      SELECT concat('https://quetzal.demo/knowledge/recommendation/', r.recommendation_id),
             'https://quetzal.demo/ontology/recommendsProduct',
             concat('https://quetzal.demo/knowledge/product/', r.product_id),
             true, cast(NULL AS STRING), 'ops_recommendation_log'
      FROM {fq}.ops_recommendation_log r
      JOIN {fq}.`{tmp_features}` f ON r.customer_id = f.customer_id
      WHERE r.product_id IS NOT NULL
      UNION ALL
      SELECT concat('https://quetzal.demo/knowledge/recommendation/offer-', sha2(concat(o.cliente_id, '|', o.plan_id), 256)),
             'https://quetzal.demo/ontology/proposedFor',
             concat('https://quetzal.demo/knowledge/customer/', o.cliente_id),
             true, cast(NULL AS STRING), 'ops_customer_next_best_offer'
      FROM {fq}.ops_customer_next_best_offer o
      JOIN {fq}.`{tmp_features}` f ON o.cliente_id = f.customer_id
      WHERE o.marketing_eligible = true
      QUALIFY row_number() OVER (PARTITION BY o.cliente_id ORDER BY o.recommendation_score DESC, o.plan_id) = 1
      UNION ALL
      SELECT concat('https://quetzal.demo/knowledge/recommendation/offer-', sha2(concat(o.cliente_id, '|', o.plan_id), 256)),
             'http://www.w3.org/1999/02/22-rdf-syntax-ns#type',
             'https://quetzal.demo/ontology/Recommendation',
             true, cast(NULL AS STRING), 'ops_customer_next_best_offer'
      FROM {fq}.ops_customer_next_best_offer o
      JOIN {fq}.`{tmp_features}` f ON o.cliente_id = f.customer_id
      WHERE o.marketing_eligible = true
      QUALIFY row_number() OVER (PARTITION BY o.cliente_id ORDER BY o.recommendation_score DESC, o.plan_id) = 1
      UNION ALL
      SELECT concat('https://quetzal.demo/knowledge/recommendation/offer-', sha2(concat(o.cliente_id, '|', o.plan_id), 256)),
             'http://www.w3.org/2000/01/rdf-schema#label',
             concat('Oferta recomendada · ', o.product_name),
             false, 'http://www.w3.org/2001/XMLSchema#string', 'ops_customer_next_best_offer'
      FROM {fq}.ops_customer_next_best_offer o
      JOIN {fq}.`{tmp_features}` f ON o.cliente_id = f.customer_id
      WHERE o.marketing_eligible = true
      QUALIFY row_number() OVER (PARTITION BY o.cliente_id ORDER BY o.recommendation_score DESC, o.plan_id) = 1
      UNION ALL
      SELECT concat('https://quetzal.demo/knowledge/recommendation/offer-', sha2(concat(o.cliente_id, '|', o.plan_id), 256)),
             'https://quetzal.demo/ontology/recommendsProduct',
             concat('https://quetzal.demo/knowledge/product/', o.plan_id),
             true, cast(NULL AS STRING), 'ops_customer_next_best_offer'
      FROM {fq}.ops_customer_next_best_offer o
      JOIN {fq}.`{tmp_features}` f ON o.cliente_id = f.customer_id
      WHERE o.marketing_eligible = true
      QUALIFY row_number() OVER (PARTITION BY o.cliente_id ORDER BY o.recommendation_score DESC, o.plan_id) = 1
      UNION ALL
      SELECT concat('https://quetzal.demo/knowledge/customer/', o.cliente_id),
             'https://quetzal.demo/ontology/recommendedProduct',
             concat('https://quetzal.demo/knowledge/product/', o.plan_id),
             true, cast(NULL AS STRING), 'ops_customer_next_best_offer'
      FROM {fq}.ops_customer_next_best_offer o
      JOIN {fq}.`{tmp_features}` f ON o.cliente_id = f.customer_id
      WHERE o.marketing_eligible = true
      QUALIFY row_number() OVER (PARTITION BY o.cliente_id ORDER BY o.recommendation_score DESC, o.plan_id) = 1
      UNION ALL
      SELECT DISTINCT concat('https://quetzal.demo/knowledge/product/', o.plan_id),
             'http://www.w3.org/1999/02/22-rdf-syntax-ns#type',
             'https://quetzal.demo/ontology/Product',
             true, cast(NULL AS STRING), 'ops_customer_next_best_offer'
      FROM {fq}.ops_customer_next_best_offer o
      JOIN {fq}.`{tmp_features}` f ON o.cliente_id = f.customer_id
      WHERE o.marketing_eligible = true
      UNION ALL
      SELECT DISTINCT concat('https://quetzal.demo/knowledge/product/', o.plan_id),
             'http://www.w3.org/2000/01/rdf-schema#label', o.product_name,
             false, 'http://www.w3.org/2001/XMLSchema#string', 'ops_customer_next_best_offer'
      FROM {fq}.ops_customer_next_best_offer o
      JOIN {fq}.`{tmp_features}` f ON o.cliente_id = f.customer_id
      WHERE o.marketing_eligible = true
    )
    SELECT subject, predicate, object, object_is_iri, datatype, source_table,
           '{run_id}' AS run_id, current_timestamp() AS generated_at
    FROM customer_triples
    UNION ALL
    SELECT subject, predicate, object, object_is_iri, datatype, source_table,
           '{run_id}', current_timestamp() FROM relationship_triples
    UNION ALL
    SELECT subject, predicate, object, object_is_iri, datatype, source_table,
           '{run_id}', current_timestamp() FROM business_triples
    """)

    feature_count = sql(f"SELECT count(*) AS n FROM {fq}.`{tmp_features}`").first()["n"]
    prediction_count = sql(f"SELECT count(*) AS n FROM {fq}.`{tmp_predictions}`").first()["n"]
    community_count = sql(f"SELECT count(*) AS n FROM {fq}.`{tmp_communities}`").first()["n"]
    qualified_relationship_count = sql("SELECT count(*) AS n FROM graph_undirected").first()["n"]
    triple_count = sql(f"SELECT count(*) AS n FROM {fq}.`{tmp_triples}`").first()["n"]
    semantic_type_count = sql(f"""
      SELECT count(DISTINCT object) AS n
      FROM {fq}.`{tmp_triples}`
      WHERE predicate = 'http://www.w3.org/1999/02/22-rdf-syntax-ns#type'
    """).first()["n"]
    semantic_predicate_count = sql(f"""
      SELECT count(DISTINCT predicate) AS n
      FROM {fq}.`{tmp_triples}`
    """).first()["n"]
    qualified_event_count = sql(f"""
      SELECT count(*) AS n
      FROM {fq}.`{tmp_edges}` e
      JOIN graph_undirected q
        ON least(e.source_customer_id, e.destination_customer_id) = q.node_a
       AND greatest(e.source_customer_id, e.destination_customer_id) = q.node_b
    """).first()["n"]
    if (feature_count != node_count or prediction_count != node_count or community_count < 1
            or qualified_relationship_count < 1 or qualified_event_count < 1
            or triple_count < node_count or semantic_type_count < 5
            or semantic_predicate_count < 12):
        raise RuntimeError(
            f"Invalid staged snapshot: features={feature_count}, predictions={prediction_count}, "
            f"communities={community_count}, relationships={qualified_relationship_count}, "
            f"qualified_calls={qualified_event_count}, triples={triple_count}, "
            f"semantic_types={semantic_type_count}, predicates={semantic_predicate_count}"
        )

    # Publish only after the complete snapshot passed validation. Expensive work
    # never replaces the last known-good tables while it is still running.
    sql(f"CREATE OR REPLACE TABLE {fq}.gold_customer_graph_features USING DELTA "
        f"TBLPROPERTIES ('delta.enableChangeDataFeed' = 'true', 'comment' = 'Governed relationship features for Quetzal customer intelligence') "
        f"AS SELECT * FROM {fq}.`{tmp_features}`")
    sql(f"CREATE OR REPLACE TABLE {fq}.gold_churn_graph_predictions USING DELTA "
        f"TBLPROPERTIES ('delta.enableChangeDataFeed' = 'true', 'comment' = 'Retention priority signals; graph_churn_probability is a compatibility alias of the unchanged baseline') "
        f"AS SELECT * FROM {fq}.`{tmp_predictions}`")
    sql(f"CREATE OR REPLACE TABLE {fq}.gold_graph_community_summary USING DELTA "
        f"TBLPROPERTIES ('comment' = 'Bounded community aggregates for the Quetzal graph explorer') "
        f"AS SELECT * FROM {fq}.`{tmp_communities}`")
    sql(f"CREATE OR REPLACE TABLE {fq}.gold_quetzal_knowledge_graph_triples USING DELTA "
        f"TBLPROPERTIES ('delta.enableChangeDataFeed' = 'true', 'comment' = 'OntoBricks-compatible semantic projection; subject/predicate/object form the standard triple contract') "
        f"AS SELECT * FROM {fq}.`{tmp_triples}`")
    sql(f"CREATE OR REPLACE TABLE {fq}.silver_customer_call_edges USING DELTA "
        f"TBLPROPERTIES ('delta.enableChangeDataFeed' = 'true', 'comment' = 'Calls belonging to qualified subscriber relationships for Quetzal Graph Intelligence') "
        f"AS SELECT e.*, q.qualification_reason, q.reciprocal, q.last_contact_at, "
        f"q.recency_weight, q.relationship_weight "
        f"FROM {fq}.`{tmp_edges}` e JOIN graph_undirected q "
        f"ON least(e.source_customer_id, e.destination_customer_id) = q.node_a "
        f"AND greatest(e.source_customer_id, e.destination_customer_id) = q.node_b")

    sql(f"""
    CREATE OR REPLACE VIEW {fq}.ops_customer_graph_360 AS
    SELECT c.*,
           f.degree AS graph_degree,
           f.unique_contacts AS graph_unique_contacts,
           f.reciprocal_contacts AS graph_reciprocal_contacts,
           f.countries_reached AS graph_countries_reached,
           f.international_call_pct AS graph_international_call_pct,
           f.pagerank AS graph_pagerank,
           f.clustering_coefficient AS graph_clustering_coefficient,
           f.community_id AS graph_community_id,
           f.community_size AS graph_community_size,
           f.neighbour_avg_churn_probability,
           f.high_risk_neighbour_pct,
           f.influenced_revenue_usd,
           f.reach_score,
           f.network_exposure_score,
           f.risk_diffusion_score,
           f.bridge_score,
           f.influence_score,
           f.contagion_risk_score,
           p.retention_priority_score,
           p.graph_churn_probability,
           p.graph_lift,
           p.risk_tier AS graph_risk_tier,
           p.recommended_action AS graph_recommended_action,
           p.explanation_codes AS graph_explanation_codes,
           p.model_version AS graph_model_version,
           p.scored_at AS graph_scored_at
    FROM {fq}.ops_customer_360 c
    LEFT JOIN {fq}.gold_customer_graph_features f ON c.cliente_id = f.customer_id
    LEFT JOIN {fq}.gold_churn_graph_predictions p
      ON c.cliente_id = p.customer_id AND f.run_id = p.run_id
    """)
    drop_intermediate_tables()

    from databricks.sdk import WorkspaceClient

    app = WorkspaceClient().apps.get(app_name)
    app_principal = app.service_principal_client_id
    if app_principal:
        principal = f"`{app_principal}`"
        sql(f"GRANT USE CATALOG ON CATALOG `{catalog}` TO {principal}")
        sql(f"GRANT USE SCHEMA ON SCHEMA {fq} TO {principal}")
        for table in (
            "silver_customer_call_edges",
            "gold_customer_graph_features",
            "gold_churn_graph_predictions",
            "gold_graph_community_summary",
            "gold_quetzal_knowledge_graph_triples",
            "ops_graph_run_log",
        ):
            sql(f"GRANT SELECT ON TABLE {fq}.`{table}` TO {principal}")
        sql(f"GRANT SELECT ON VIEW {fq}.ops_customer_graph_360 TO {principal}")

    sql(f"""
    UPDATE {fq}.ops_graph_run_log
    SET status = 'SUCCEEDED', completed_at = current_timestamp(),
        node_count = {node_count}, edge_count = {qualified_event_count},
        feature_count = {feature_count}, prediction_count = {prediction_count},
        community_count = {community_count}, triple_count = {triple_count},
        model_version = 'graph-intelligence-v3-ontobricks',
        workflow_run_id = {workflow_run_id}, published_at = current_timestamp(),
        error_message = NULL
    WHERE run_id = '{run_id}'
    """)

    result = {
        "run_id": run_id,
        "status": "SUCCEEDED",
        "nodes": node_count,
        "source_calls": generated_call_count,
        "qualified_calls": qualified_event_count,
        "relationships": qualified_relationship_count,
        "features": feature_count,
        "predictions": prediction_count,
        "communities": community_count,
        "triples": triple_count,
        "model_version": "graph-intelligence-v3-ontobricks",
        "algorithms": {
            "reach": "WEIGHTED_PAGERANK",
            "risk_diffusion": "WEIGHTED_PERSONALIZED_PAGERANK",
            "groups": "WEIGHTED_LABEL_PROPAGATION",
            "exposure": "WEIGHTED_NEIGHBOUR_RISK",
        },
        "relationship_policy": {
            "min_calls": min_contact_calls,
            "min_minutes": min_contact_minutes,
            "reciprocal_qualifies": True,
            "max_recency_days": max_contact_recency_days,
        },
        "scheduled": False,
    }
    print(result)
except Exception as exc:
    error = str(exc).replace("'", "''")[:4000]
    sql(f"""
    UPDATE {fq}.ops_graph_run_log
    SET status = 'FAILED', completed_at = current_timestamp(),
        model_version = 'graph-intelligence-v3-ontobricks',
        workflow_run_id = {workflow_run_id}, error_message = '{error}'
    WHERE run_id = '{run_id}'
    """)
    drop_intermediate_tables()
    raise

# dbutils.notebook.exit raises an internal exception; keeping it outside the
# guarded build prevents a successful publication from being marked FAILED.
dbutils.notebook.exit(str(result))
