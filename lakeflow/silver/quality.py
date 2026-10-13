# ruff: noqa: F821 -- `spark` is injected by the Lakeflow runtime.
# =============================================================================
# SILVER — Calidad de Datos (DQX) + Deduplicación
# =============================================================================
# Quetzal Telecom — Lakehouse Pipeline
# Capa: Silver (validated & deduplicated)
# Validaciones: Expectations con DROP ROW para registros inválidos
# Deduplicación: dropDuplicatesWithinWatermark sobre claves de negocio
# =============================================================================

from typing import Any

from pyspark import pipelines as dp

spark: Any  # Injected by the Lakeflow runtime.

PAISES_VALIDOS = "pais_codigo IN ('PA','CO','MX','BR','AR','CL','PE','EC','CR','GT','DO','UY')"
SEGMENTOS_VALIDOS = "segmento_id IN ('PER','BIZ','ENT')"


# =============================================================================
# CLIENTES — Validación completa + deduplicación por cliente_id
# =============================================================================

@dp.table(
    name="silver_clientes",
    comment="Clientes validados y deduplicados con reglas DQX enterprise"
)
@dp.expect_or_fail("pk_cliente_id", "cliente_id IS NOT NULL")
@dp.expect_or_drop("email_formato_valido", "email LIKE '%@%.%'")
@dp.expect_or_drop("pais_codigo_valido", PAISES_VALIDOS)
@dp.expect_or_drop("segmento_valido", SEGMENTOS_VALIDOS)
@dp.expect_or_drop("edad_rango_razonable", "edad BETWEEN 18 AND 100")
@dp.expect("credit_score_rango", "credit_score BETWEEN 300 AND 850")
@dp.expect("nps_rango", "nps_ultimo BETWEEN 0 AND 10")
@dp.expect("estado_valido", "estado IN ('activo','inactivo')")
def silver_clientes():
    return (
        spark.readStream.table("bronze_clientes")
        .withWatermark("_ingested_at", "1 day")
        .dropDuplicatesWithinWatermark(["cliente_id"])
    )


# =============================================================================
# SUSCRIPCIONES (CONTRATOS) — DQX reforzado + deduplicación estricta
# Énfasis especial: validación de contratos es crítica para billing
# =============================================================================

@dp.table(
    name="silver_suscripciones",
    comment="Contratos validados con DQX reforzado: integridad referencial, precios, estados, deduplicación"
)
@dp.expect_or_fail("pk_suscripcion_id", "suscripcion_id IS NOT NULL")
@dp.expect_or_fail("fk_cliente_id", "cliente_id IS NOT NULL")
@dp.expect_or_fail("fk_plan_id", "plan_id IS NOT NULL")
@dp.expect_or_drop("precio_positivo", "precio_mensual_usd > 0")
@dp.expect_or_drop("estado_contrato_valido", "estado IN ('activa','cancelada','suspendida')")
@dp.expect_or_drop("fecha_inicio_presente", "fecha_inicio IS NOT NULL")
@dp.expect("fecha_coherente", "fecha_fin IS NULL OR fecha_fin >= fecha_inicio")
@dp.expect("metodo_pago_valido", "metodo_pago IN ('tarjeta_credito','tarjeta_debito','transferencia','efectivo','wallet_digital')")
@dp.expect("facturacion_dia_valido", "facturacion_dia IN (1,5,10,15,20,25)")
def silver_suscripciones():
    return (
        spark.readStream.table("bronze_suscripciones")
        .withWatermark("_ingested_at", "1 day")
        .dropDuplicatesWithinWatermark(["suscripcion_id"])
    )


# =============================================================================
# FACTURAS — Validación de integridad financiera
# =============================================================================

@dp.table(
    name="silver_facturas",
    comment="Facturas validadas: montos, estados de pago, coherencia de fechas"
)
@dp.expect_or_fail("pk_factura_id", "factura_id IS NOT NULL")
@dp.expect_or_fail("fk_suscripcion_id", "suscripcion_id IS NOT NULL")
@dp.expect_or_fail("fk_cliente_id", "cliente_id IS NOT NULL")
@dp.expect_or_drop("monto_base_no_negativo", "monto_base_usd >= 0")
@dp.expect_or_drop("monto_total_presente", "monto_total_usd IS NOT NULL")
@dp.expect_or_drop("estado_pago_valido", "estado_pago IN ('pagada','pendiente','vencida')")
@dp.expect("dias_atraso_no_negativo", "dias_atraso >= 0")
@dp.expect("fecha_emision_presente", "fecha_emision IS NOT NULL")
@dp.expect("coherencia_pago", "estado_pago = 'vencida' OR fecha_pago IS NOT NULL")
def silver_facturas():
    return (
        spark.readStream.table("bronze_facturas")
        .withWatermark("_ingested_at", "1 day")
        .dropDuplicatesWithinWatermark(["factura_id"])
    )


# =============================================================================
# CDRs — Validación de registros de llamadas/datos
# =============================================================================

@dp.table(
    name="silver_cdrs",
    comment="CDRs validados: tipos de evento, duraciones, consumos de datos"
)
@dp.expect_or_fail("pk_cdr_id", "cdr_id IS NOT NULL")
@dp.expect_or_drop("tipo_evento_valido", "tipo_evento IN ('voz_saliente','voz_entrante','datos','sms_saliente','sms_entrante')")
@dp.expect_or_drop("duracion_no_negativa", "duracion_seg >= 0")
@dp.expect_or_drop("datos_no_negativos", "datos_mb >= 0")
@dp.expect("pais_valido", PAISES_VALIDOS)
@dp.expect("senal_rango", "`calidad_señal_dbm` BETWEEN -120 AND -20")
@dp.expect("tecnologia_valida", "tecnologia_red IN ('3G','4G','5G')")
def silver_cdrs():
    return (
        spark.readStream.table("bronze_cdrs")
        .withWatermark("_ingested_at", "1 day")
        .dropDuplicatesWithinWatermark(["cdr_id"])
    )


# =============================================================================
# TELEMETRÍA DE RED — Validación de métricas operacionales
# =============================================================================

@dp.table(
    name="silver_telemetria_red",
    comment="Telemetría validada: capacidad, latencia, pérdida de paquetes"
)
@dp.expect_or_fail("pk_torre_id", "torre_id IS NOT NULL")
@dp.expect_or_drop("capacidad_rango", "uso_capacidad_pct BETWEEN 0 AND 100")
@dp.expect_or_drop("latencia_no_negativa", "latencia_ms >= 0")
@dp.expect("throughput_positivo", "throughput_mbps > 0")
@dp.expect("packet_loss_rango", "packet_loss_pct BETWEEN 0 AND 100")
@dp.expect("temperatura_rango", "temperatura_equipo_c BETWEEN -10 AND 80")
@dp.expect("alerta_valida", "alerta IN ('normal','capacidad_alta','latencia_alta','packet_loss_alto','temperatura_alta')")
def silver_telemetria_red():
    return (
        spark.readStream.table("bronze_telemetria_red")
        .withWatermark("_ingested_at", "1 day")
        .dropDuplicatesWithinWatermark(["torre_id", "timestamp"])
    )


# =============================================================================
# TICKETS — Validación de atención al cliente
# =============================================================================

@dp.table(
    name="silver_tickets",
    comment="Tickets validados: categorías, estados, tiempos de resolución"
)
@dp.expect_or_fail("pk_ticket_id", "ticket_id IS NOT NULL")
@dp.expect_or_fail("fk_cliente_id", "cliente_id IS NOT NULL")
@dp.expect_or_drop("categoria_presente", "categoria IS NOT NULL")
@dp.expect_or_drop("estado_valido", "estado IN ('resuelto','cerrado','abierto','escalado')")
@dp.expect("pais_valido", PAISES_VALIDOS)
@dp.expect("prioridad_valida", "prioridad IN ('baja','media','alta','critica')")
@dp.expect("csat_rango", "csat_score IS NULL OR csat_score BETWEEN 1 AND 5")
@dp.expect("resolucion_coherente", "estado IN ('abierto','escalado') OR tiempo_resolucion_horas IS NOT NULL")
def silver_tickets():
    return (
        spark.readStream.table("bronze_tickets")
        .withWatermark("_ingested_at", "1 day")
        .dropDuplicatesWithinWatermark(["ticket_id"])
    )


# =============================================================================
# NPS — Validación de encuestas
# =============================================================================

@dp.table(
    name="silver_nps",
    comment="Encuestas NPS validadas: scores, categorías, canales"
)
@dp.expect_or_fail("pk_nps_id", "nps_id IS NOT NULL")
@dp.expect_or_fail("fk_cliente_id", "cliente_id IS NOT NULL")
@dp.expect_or_drop("score_rango", "score BETWEEN 0 AND 10")
@dp.expect_or_drop("categoria_nps_valida", "categoria_nps IN ('promotor','neutral','detractor')")
@dp.expect("canal_valido", "canal_encuesta IN ('email','sms','app','ivr')")
@dp.expect("fecha_presente", "fecha_encuesta IS NOT NULL")
def silver_nps():
    return (
        spark.readStream.table("bronze_nps")
        .withWatermark("_ingested_at", "1 day")
        .dropDuplicatesWithinWatermark(["nps_id"])
    )


# =============================================================================
# CHURN FEATURES — Validación de features ML
# =============================================================================

@dp.table(
    name="silver_churn_features",
    comment="Features de churn validadas; synthetic_churn_propensity es una regla demostrativa, no una predicción ML"
)
@dp.expect_or_fail("pk_cliente_id", "cliente_id IS NOT NULL")
@dp.expect_or_drop("propension_sintetica_rango", "synthetic_churn_propensity BETWEEN 0 AND 1")
@dp.expect("alias_legacy_coherente", "churn_risk_score = synthetic_churn_propensity")
@dp.expect("pais_valido", PAISES_VALIDOS)
@dp.expect("segmento_valido", SEGMENTOS_VALIDOS)
@dp.expect("gasto_no_negativo", "gasto_mensual_total >= 0")
@dp.expect("origen_sintetico_explicito", "data_origin = 'synthetic_demo'")
@dp.expect_or_fail("horizonte_futuro_explicito", "label_horizon_days > 0")
@dp.expect_or_fail("label_posterior_al_snapshot", "label_observed_at > TO_DATE(feature_snapshot_at)")
def silver_churn_features():
    return (
        spark.readStream.table("bronze_churn_features")
        .withWatermark("_ingested_at", "1 day")
        .dropDuplicatesWithinWatermark(["cliente_id"])
    )
