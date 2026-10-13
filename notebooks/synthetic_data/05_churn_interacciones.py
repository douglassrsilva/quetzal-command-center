# Databricks notebook source
# DBTITLE 1,Run Config
# MAGIC %run ./00_config

# COMMAND ----------

# DBTITLE 1,Gerar tickets de suporte — 100% Spark nativo
from pyspark.sql import functions as F
from pyspark.sql.types import *

df_clientes = spark.read.parquet(f"{VOLUME_PATH}/fact_clientes")

# =============================================================================
# TICKETS — 100% Spark nativo (~120K tickets para 1M clientes)
# Amostra 12% dos clientes, cada um gera 1 ticket
# =============================================================================
num_tickets = int(NUM_CUSTOMERS * TICKETS_PER_1000 / 1000)
sample_rate = num_tickets / NUM_CUSTOMERS

# Categorias e motivos como expressões Spark
categoria_expr = (
    F.when(F.col("_rc") < 0.25, "facturacion")
     .when(F.col("_rc") < 0.47, "servicio_tecnico")
     .when(F.col("_rc") < 0.65, "planes")
     .when(F.col("_rc") < 0.77, "cancelacion")
     .when(F.col("_rc") < 0.87, "cobertura")
     .when(F.col("_rc") < 0.92, "fraude")
     .otherwise("otro")
)

motivos_map = {
    "facturacion": ["Cobro incorrecto","Doble cobro","Factura no recibida","Disputa de cargo","Reembolso pendiente"],
    "servicio_tecnico": ["Sin señal","Internet lento","Caídas frecuentes","Config equipo","TV sin imagen"],
    "planes": ["Cambio de plan","Info de planes","Upgrade solicitado","Downgrade","Activar roaming"],
    "cancelacion": ["Solicitud de baja","Retención exitosa","Portabilidad saliente","Penalización"],
    "cobertura": ["Sin cobertura","Cobertura degradada","Nueva torre","Problemas indoor"],
    "fraude": ["SIM clonada","Uso no autorizado","Robo equipo","Suplantación"],
    "otro": ["Consulta general","Felicitación","Sugerencia","Reclamo formal"],
}

# Construir motivo_expr dinâmico
motivo_cases = F.lit("Consulta general")
for cat, motivos in motivos_map.items():
    arr = F.array(*[F.lit(m) for m in motivos])
    motivo_cases = F.when(F.col("categoria") == cat, arr[(F.col("_rm") * len(motivos)).cast("int")]).otherwise(motivo_cases)

canal_expr = (
    F.when(F.col("_rch") < 0.30, "call_center")
     .when(F.col("_rch") < 0.55, "app")
     .when(F.col("_rch") < 0.75, "chat")
     .when(F.col("_rch") < 0.85, "tienda")
     .when(F.col("_rch") < 0.95, "redes_sociales")
     .otherwise("email")
)

estado_expr = (
    F.when(F.col("_re") < 0.55, "resuelto")
     .when(F.col("_re") < 0.80, "cerrado")
     .when(F.col("_re") < 0.92, "abierto")
     .otherwise("escalado")
)

df_tickets = (
    df_clientes
    .select("cliente_id", "pais_codigo")
    .withColumn("_sample", F.rand(SEED + 40))
    .filter(F.col("_sample") < sample_rate)
    .withColumn("_rc", F.rand(SEED + 41))
    .withColumn("_rm", F.rand(SEED + 42))
    .withColumn("_rch", F.rand(SEED + 43))
    .withColumn("_re", F.rand(SEED + 44))
    .withColumn("_rp", F.rand(SEED + 45))
    .withColumn("_rd", F.rand(SEED + 46))
    .withColumn("_rcsat", F.rand(SEED + 47))
    .withColumn("_rres", F.rand(SEED + 48))
    # Campos
    .withColumn("ticket_id", F.concat(F.lit("TKT-"), F.monotonically_increasing_id()))
    .withColumn("fecha_creacion",
        F.from_unixtime(F.unix_timestamp(F.date_sub(F.to_date(F.lit(REFERENCE_DATE)), 365)) + (F.col("_rd") * 365 * 86400).cast("long")).cast("timestamp")
    )
    .withColumn("categoria", categoria_expr)
    .withColumn("motivo", motivo_cases)
    .withColumn("canal", canal_expr)
    .withColumn("prioridad",
        F.when(F.col("_rp") < 0.30, "baja")
         .when(F.col("_rp") < 0.70, "media")
         .when(F.col("_rp") < 0.90, "alta")
         .otherwise("critica")
    )
    .withColumn("estado", estado_expr)
    .withColumn("tiempo_resolucion_horas",
        F.when(F.col("estado").isin("resuelto", "cerrado"), F.round(0.5 + F.col("_rres") * 72, 1))
    )
    .withColumn("csat_score",
        F.when(F.col("estado").isin("resuelto", "cerrado"),
            F.when(F.col("_rcsat") < 0.05, 1)
             .when(F.col("_rcsat") < 0.15, 2)
             .when(F.col("_rcsat") < 0.35, 3)
             .when(F.col("_rcsat") < 0.70, 4)
             .otherwise(5)
        )
    )
    .withColumn("recontacto", F.rand(SEED + 49) < 0.15)
    .select("ticket_id", "cliente_id", "pais_codigo", "fecha_creacion",
            "categoria", "motivo", "canal", "prioridad", "estado",
            "tiempo_resolucion_horas", "csat_score", "recontacto")
)

df_tickets.write.mode("overwrite").parquet(f"{VOLUME_PATH}/fact_tickets")
print(f"✓ fact_tickets: {spark.read.parquet(f'{VOLUME_PATH}/fact_tickets').count():,} registros")
spark.read.parquet(f"{VOLUME_PATH}/fact_tickets").groupBy("categoria").count().orderBy(F.desc("count")).show()

# COMMAND ----------

# DBTITLE 1,Gerar eventos de churn e features para ML
# Para cada cliente, gerar features de churn prediction
# Combina dados de billing, CDRs e tickets

df_clientes = spark.read.parquet(f"{VOLUME_PATH}/fact_clientes")
df_facturas = spark.read.parquet(f"{VOLUME_PATH}/fact_facturas")
df_subs = spark.read.parquet(f"{VOLUME_PATH}/fact_suscripciones")
df_tickets = spark.read.parquet(f"{VOLUME_PATH}/fact_tickets")

# --- Features de billing ---
df_billing_feat = (
    df_facturas
    .groupBy("cliente_id")
    .agg(
        F.count("*").alias("total_facturas"),
        F.avg("monto_total_usd").alias("avg_monto_factura"),
        F.sum(F.when(F.col("estado_pago") == "vencida", 1).otherwise(0)).alias("facturas_vencidas"),
        F.avg("dias_atraso").alias("avg_dias_atraso"),
        F.max("dias_atraso").alias("max_dias_atraso"),
    )
)

# --- Features de tickets ---
df_ticket_feat = (
    df_tickets
    .groupBy("cliente_id")
    .agg(
        F.count("*").alias("total_tickets"),
        F.sum(F.when(F.col("categoria") == "cancelacion", 1).otherwise(0)).alias("tickets_cancelacion"),
        F.avg("csat_score").alias("avg_csat"),
        F.sum(F.when(F.col("recontacto"), 1).otherwise(0)).alias("total_recontactos"),
    )
)

# --- Features de subscrição ---
df_sub_feat = (
    df_subs
    .groupBy("cliente_id")
    .agg(
        F.count("*").alias("total_suscripciones"),
        F.sum("precio_mensual_usd").alias("gasto_mensual_total"),
        F.sum(F.when(F.col("estado") == "activa", 1).otherwise(0)).alias("suscripciones_activas"),
    )
)

# --- Combinar tudo ---
df_churn = (
    df_clientes
    .select("cliente_id", "pais_codigo", "segmento_id", "edad", "antiguedad_dias",
            "credit_score", "nps_ultimo", "canal_adquisicion", "estado")
    .join(df_billing_feat, "cliente_id", "left")
    .join(df_ticket_feat, "cliente_id", "left")
    .join(df_sub_feat, "cliente_id", "left")
    .fillna(0)
    # Regla demostrativa separada de cualquier probabilidad generada por un modelo.
    .withColumn("synthetic_churn_propensity",
        F.round(
            F.greatest(F.lit(0.0), F.least(F.lit(1.0),
                F.lit(0.1)
                + F.when(F.col("facturas_vencidas") > 2, 0.2).otherwise(0)
                + F.when(F.col("tickets_cancelacion") > 0, 0.25).otherwise(0)
                + F.when(F.col("nps_ultimo") < 5, 0.15).otherwise(0)
                + F.when(F.col("avg_dias_atraso") > 15, 0.1).otherwise(0)
                + F.when(F.col("antiguedad_dias") < 180, 0.1).otherwise(0)
                + F.when(F.col("credit_score") < 500, 0.1).otherwise(0)
                + (F.rand(SEED + 99) * 0.15)  # noise
            )), 3
        )
    )
    # Alias legado preservado para consumidores existentes. Nunca copiar este campo
    # a churn_probability: solo el scoring del modelo puede producir esa coluna.
    .withColumn("churn_risk_score", F.col("synthetic_churn_propensity"))
    .withColumn("synthetic_score_source", F.lit("deterministic_demo_rule_v1"))
    # Label futuro sintético. La regla define la tasa del evento, mas nunca
    # entra como feature en el entrenamiento do modelo.
    .withColumn(
        "_synthetic_event_probability",
        F.least(F.lit(0.35), F.lit(0.02) + F.col("synthetic_churn_propensity") * F.lit(0.25)),
    )
    .withColumn(
        "churned",
        F.when(
            (F.col("estado") == "activo")
            & (F.rand(SEED + 100) < F.col("_synthetic_event_probability")),
            1,
        ).otherwise(0),
    )
    .withColumn("feature_snapshot_at", F.to_timestamp(F.lit(REFERENCE_DATE)))
    .withColumn("label_observed_at", F.date_add(F.to_date(F.lit(REFERENCE_DATE)), CHURN_LABEL_HORIZON_DAYS))
    .withColumn("label_horizon_days", F.lit(CHURN_LABEL_HORIZON_DAYS))
    .withColumn("target_definition", F.lit("synthetic cancellation event after feature snapshot"))
    .withColumn("data_origin", F.lit("synthetic_demo"))
    .drop("_synthetic_event_probability")
)

df_churn.write.mode("overwrite").parquet(f"{VOLUME_PATH}/ml_churn_features")
print(f"✓ ml_churn_features salvo: {df_churn.count():,} registros")
print("\nDistribuição de churn:")
df_churn.groupBy("churned").count().show()
print("Estatísticas de synthetic_churn_propensity (regla, no modelo):")
df_churn.select(
    F.mean("synthetic_churn_propensity").alias("media"),
    F.stddev("synthetic_churn_propensity").alias("desvio"),
    F.min("synthetic_churn_propensity").alias("min"),
    F.max("synthetic_churn_propensity").alias("max")
).show()

# COMMAND ----------

# DBTITLE 1,Gerar NPS — 100% Spark nativo
# =============================================================================
# NPS — 100% Spark nativo. 10% amostra x 12 meses = ~1.2M registros
# =============================================================================

# Criar 12 meses de surveys
df_meses = spark.range(0, MONTHS_HISTORY).withColumnRenamed("id", "mes_offset")

# Cross join: clientes x meses, depois sample 10%
df_nps = (
    df_clientes.select("cliente_id")
    .crossJoin(df_meses)
    .withColumn("_sample", F.rand(SEED + 50))
    .filter(F.col("_sample") < NPS_SAMPLE_RATE)  # 10%
    .withColumn("fecha_encuesta",
        F.add_months(F.add_months(F.lit(REFERENCE_DATE), -MONTHS_HISTORY), F.col("mes_offset")).cast("date")
    )
    .withColumn("_rs", F.rand(SEED + 51))
    .withColumn("_rcan", F.rand(SEED + 52))
    # Score NPS (0-10) com distribuição realista
    .withColumn("score",
        F.when(F.col("_rs") < 0.02, 0)
         .when(F.col("_rs") < 0.04, 1)
         .when(F.col("_rs") < 0.07, 2)
         .when(F.col("_rs") < 0.11, 3)
         .when(F.col("_rs") < 0.16, 4)
         .when(F.col("_rs") < 0.24, 5)
         .when(F.col("_rs") < 0.34, 6)
         .when(F.col("_rs") < 0.49, 7)
         .when(F.col("_rs") < 0.69, 8)
         .when(F.col("_rs") < 0.87, 9)
         .otherwise(10)
    )
    .withColumn("categoria_nps",
        F.when(F.col("score") >= 9, "promotor")
         .when(F.col("score") >= 7, "neutral")
         .otherwise("detractor")
    )
    .withColumn("canal_encuesta",
        F.when(F.col("_rcan") < 0.35, "email")
         .when(F.col("_rcan") < 0.60, "sms")
         .when(F.col("_rcan") < 0.90, "app")
         .otherwise("ivr")
    )
    .withColumn("nps_id", F.concat(F.lit("NPS-"), F.monotonically_increasing_id()))
    .withColumn("respondida", F.lit(True))
    .select("nps_id", "cliente_id", "fecha_encuesta", "score",
            "categoria_nps", "canal_encuesta", "respondida")
)

df_nps.write.mode("overwrite").parquet(f"{VOLUME_PATH}/fact_nps")
print(f"✓ fact_nps: {spark.read.parquet(f'{VOLUME_PATH}/fact_nps').count():,} registros")
spark.read.parquet(f"{VOLUME_PATH}/fact_nps").groupBy("categoria_nps").count().orderBy(F.desc("count")).show()
