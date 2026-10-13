# ruff: noqa: F821 -- `spark` is injected by the Lakeflow runtime.
# =============================================================================
# GOLD — KPIs de Negocio y Agregaciones Estratégicas
# =============================================================================
# Quetzal Telecom — Lakehouse Pipeline
# Capa: Gold (business-ready aggregations)
# Todas las vistas materializadas leen batch desde Silver
# =============================================================================

from typing import Any

from pyspark import pipelines as dp
from pyspark.sql import functions as F

spark: Any  # Injected by the Lakeflow runtime.


# =============================================================================
# 1. INGRESOS POR PAÍS Y VERTICAL
# =============================================================================

@dp.materialized_view(
    name="gold_revenue_by_country_service",
    comment="Ingresos mensuales agregados por país y vertical de servicio"
)
def gold_revenue_by_country_service():
    facturas = spark.read.table("silver_facturas")
    suscripciones = spark.read.table("silver_suscripciones").select("suscripcion_id", "plan_id")
    planes = spark.read.table("bronze_planes").select("plan_id", "vertical")
    clientes = spark.read.table("silver_clientes").select("cliente_id", "pais_codigo")

    return (
        facturas
        .join(clientes, "cliente_id")
        .join(suscripciones, "suscripcion_id")
        .join(planes, "plan_id")
        .withColumn("mes", F.date_trunc("month", "fecha_emision"))
        .groupBy("pais_codigo", "vertical", "mes")
        .agg(
            F.sum("monto_total_usd").alias("ingresos_totales_usd"),
            F.count("factura_id").alias("num_facturas"),
            F.round(F.avg("monto_total_usd"), 2).alias("ticket_promedio_usd"),
            F.sum(F.when(F.col("estado_pago") == "pagada", F.col("monto_total_usd")).otherwise(0)).alias("ingresos_cobrados_usd")
        )
    )


# =============================================================================
# 2. MÉTRICAS DE SUSCRIPTORES
# =============================================================================

@dp.materialized_view(
    name="gold_subscriber_metrics",
    comment="Métricas mensuales de suscriptores: activos, nuevos, cancelados por país y segmento"
)
def gold_subscriber_metrics():
    suscripciones = spark.read.table("silver_suscripciones")
    clientes = spark.read.table("silver_clientes").select("cliente_id", "pais_codigo", "segmento_id")

    subs_with_country = suscripciones.join(clientes, "cliente_id")

    # Generar meses de análisis
    meses = (
        subs_with_country
        .select(
            F.date_trunc("month", "fecha_inicio").alias("mes_ref")
        )
        .union(
            subs_with_country
            .filter(F.col("fecha_fin").isNotNull())
            .select(F.date_trunc("month", "fecha_fin").alias("mes_ref"))
        )
        .distinct()
    )

    activos = (
        subs_with_country
        .crossJoin(meses)
        .filter(
            (F.col("fecha_inicio") <= F.last_day(F.col("mes_ref"))) &
            ((F.col("fecha_fin").isNull()) | (F.col("fecha_fin") >= F.col("mes_ref")))
        )
        .groupBy("pais_codigo", "segmento_id", "mes_ref")
        .agg(
            F.countDistinct("suscripcion_id").alias("suscripciones_activas"),
            F.countDistinct("cliente_id").alias("clientes_activos")
        )
    )

    nuevos = (
        subs_with_country
        .withColumn("mes_alta", F.date_trunc("month", "fecha_inicio"))
        .groupBy("pais_codigo", "segmento_id", F.col("mes_alta").alias("mes_ref"))
        .agg(F.countDistinct("suscripcion_id").alias("suscripciones_nuevas"))
    )

    cancelados = (
        subs_with_country
        .filter(F.col("estado") == "cancelada")
        .withColumn("mes_baja", F.date_trunc("month", "fecha_fin"))
        .groupBy("pais_codigo", "segmento_id", F.col("mes_baja").alias("mes_ref"))
        .agg(F.countDistinct("suscripcion_id").alias("suscripciones_canceladas"))
    )

    return (
        activos
        .join(nuevos, ["pais_codigo", "segmento_id", "mes_ref"], "left")
        .join(cancelados, ["pais_codigo", "segmento_id", "mes_ref"], "left")
        .fillna(0, ["suscripciones_nuevas", "suscripciones_canceladas"])
        .withColumn("tasa_churn_pct",
            F.round(
                F.col("suscripciones_canceladas") / F.greatest(F.col("suscripciones_activas"), F.lit(1)) * 100, 2
            )
        )
        .withColumnRenamed("mes_ref", "mes")
    )


# =============================================================================
# 3. ARPU POR SEGMENTO
# =============================================================================

@dp.materialized_view(
    name="gold_arpu_by_segment",
    comment="ARPU (Average Revenue Per User) mensual por segmento y país"
)
def gold_arpu_by_segment():
    facturas = spark.read.table("silver_facturas")
    clientes = spark.read.table("silver_clientes").select("cliente_id", "pais_codigo", "segmento_id")

    return (
        facturas
        .join(clientes, "cliente_id")
        .withColumn("mes", F.date_trunc("month", "fecha_emision"))
        .groupBy("pais_codigo", "segmento_id", "mes")
        .agg(
            F.sum("monto_total_usd").alias("ingresos_totales_usd"),
            F.countDistinct("cliente_id").alias("clientes_unicos"),
            F.round(
                F.sum("monto_total_usd") / F.greatest(F.countDistinct("cliente_id"), F.lit(1)), 2
            ).alias("arpu_usd")
        )
    )


# =============================================================================
# 4. RESUMEN DE RIESGO DE CHURN
# =============================================================================

@dp.materialized_view(
    name="gold_churn_risk_summary",
    comment="Distribución de propensión sintética demostrativa; no representa probabilidad de un modelo"
)
def gold_churn_risk_summary():
    churn = spark.read.table("silver_churn_features")

    return (
        churn
        .withColumn("riesgo_bucket",
            F.when(F.col("synthetic_churn_propensity") >= 0.7, "alto")
             .when(F.col("synthetic_churn_propensity") >= 0.4, "medio")
             .otherwise("bajo")
        )
        .groupBy("pais_codigo", "segmento_id", "riesgo_bucket")
        .agg(
            F.count("*").alias("num_clientes"),
            F.round(F.avg("synthetic_churn_propensity"), 3).alias("avg_synthetic_propensity"),
            F.round(F.avg("synthetic_churn_propensity"), 3).alias("avg_risk_score"),
            F.round(F.avg("gasto_mensual_total"), 2).alias("avg_gasto_mensual"),
            F.sum("churned").alias("ya_churned"),
            F.sum("churned").alias("synthetic_future_churn_events"),
            F.round(F.avg("avg_dias_atraso"), 1).alias("avg_dias_atraso"),
            F.round(F.avg("total_tickets"), 1).alias("avg_tickets")
        )
        .withColumn("score_source", F.lit("synthetic_rule"))
    )


# =============================================================================
# 5. SALUD DE RED
# =============================================================================

@dp.materialized_view(
    name="gold_network_health",
    comment="KPIs de salud de red por país: latencia, throughput, alertas, capacidad"
)
def gold_network_health():
    telemetria = spark.read.table("silver_telemetria_red")

    return (
        telemetria
        .withColumn("hora", F.date_trunc("hour", "timestamp"))
        .groupBy("pais_codigo", "hora")
        .agg(
            F.round(F.avg("latencia_ms"), 1).alias("avg_latencia_ms"),
            F.round(F.avg("throughput_mbps"), 1).alias("avg_throughput_mbps"),
            F.round(F.avg("packet_loss_pct"), 3).alias("avg_packet_loss_pct"),
            F.round(F.avg("uso_capacidad_pct"), 1).alias("avg_uso_capacidad_pct"),
            F.sum(F.when(F.col("alerta") != "normal", 1).otherwise(0)).alias("torres_en_alerta"),
            F.count("*").alias("total_mediciones"),
            F.round(
                F.sum(F.when(F.col("alerta") == "normal", 1).otherwise(0)) / F.count("*") * 100, 2
            ).alias("uptime_pct")
        )
    )


# =============================================================================
# 6. SATISFACCIÓN DEL CLIENTE
# =============================================================================

@dp.materialized_view(
    name="gold_customer_satisfaction",
    comment="NPS mensual y CSAT promedio por país"
)
def gold_customer_satisfaction():
    nps = spark.read.table("silver_nps")
    tickets = spark.read.table("silver_tickets")
    clientes = spark.read.table("silver_clientes").select("cliente_id", "pais_codigo")

    # NPS por país y mes
    nps_agg = (
        nps
        .join(clientes, "cliente_id")
        .withColumn("mes", F.date_trunc("month", "fecha_encuesta"))
        .groupBy("pais_codigo", "mes")
        .agg(
            F.count("*").alias("total_encuestas"),
            F.sum(F.when(F.col("categoria_nps") == "promotor", 1).otherwise(0)).alias("promotores"),
            F.sum(F.when(F.col("categoria_nps") == "detractor", 1).otherwise(0)).alias("detractores"),
            F.round(F.avg("score"), 2).alias("avg_nps_score")
        )
        .withColumn("nps_index",
            F.round((F.col("promotores") - F.col("detractores")) / F.col("total_encuestas") * 100, 1)
        )
    )

    # CSAT por país y mes
    csat_agg = (
        tickets
        .filter(F.col("csat_score").isNotNull())
        .withColumn("mes", F.date_trunc("month", F.col("fecha_creacion")))
        .groupBy("pais_codigo", "mes")
        .agg(
            F.round(F.avg("csat_score"), 2).alias("avg_csat"),
            F.count("*").alias("total_evaluaciones_csat"),
            F.round(
                F.sum(F.when(F.col("csat_score") >= 4, 1).otherwise(0)) / F.count("*") * 100, 1
            ).alias("csat_top2_pct")
        )
    )

    return nps_agg.join(csat_agg, ["pais_codigo", "mes"], "full")


# =============================================================================
# 7. SALUD DE BILLING
# =============================================================================

@dp.materialized_view(
    name="gold_billing_health",
    comment="KPIs mensuales de facturación: morosidad, cobro, atrasos por país"
)
def gold_billing_health():
    facturas = spark.read.table("silver_facturas")
    clientes = spark.read.table("silver_clientes").select("cliente_id", "pais_codigo")

    return (
        facturas
        .join(clientes, "cliente_id")
        .withColumn("mes", F.date_trunc("month", "fecha_emision"))
        .groupBy("pais_codigo", "mes")
        .agg(
            F.count("*").alias("total_facturas"),
            F.round(F.sum("monto_total_usd"), 2).alias("facturacion_total_usd"),
            # Distribución por estado de pago
            F.round(
                F.sum(F.when(F.col("estado_pago") == "pagada", 1).otherwise(0)) / F.count("*") * 100, 1
            ).alias("pct_pagada"),
            F.round(
                F.sum(F.when(F.col("estado_pago") == "pendiente", 1).otherwise(0)) / F.count("*") * 100, 1
            ).alias("pct_pendiente"),
            F.round(
                F.sum(F.when(F.col("estado_pago") == "vencida", 1).otherwise(0)) / F.count("*") * 100, 1
            ).alias("pct_vencida"),
            # Morosidad
            F.round(F.avg("dias_atraso"), 1).alias("avg_dias_atraso"),
            F.max("dias_atraso").alias("max_dias_atraso"),
            # Ingresos cobrados vs facturados
            F.round(
                F.sum(F.when(F.col("estado_pago") == "pagada", F.col("monto_total_usd")).otherwise(0)), 2
            ).alias("ingresos_cobrados_usd"),
            F.round(
                F.sum(F.when(F.col("estado_pago") == "vencida", F.col("monto_total_usd")).otherwise(0)), 2
            ).alias("cartera_vencida_usd"),
            # Tasa de cobro
            F.round(
                F.sum(F.when(F.col("estado_pago") == "pagada", F.col("monto_total_usd")).otherwise(0)) /
                F.greatest(F.sum("monto_total_usd"), F.lit(1)) * 100, 1
            ).alias("tasa_cobro_pct")
        )
    )
