# ruff: noqa: F821 -- `spark` is injected by the Lakeflow runtime.
# =============================================================================
# BRONZE — Ingesta de datos crudos desde Volumen UC (Auto Loader / Parquet)
# =============================================================================
# Quetzal Telecom — Lakehouse Pipeline
# Capa: Bronze (raw ingestion)
# Fuente: volumen UC parametrizado por DAB (`quetzal.volume_path`)
# =============================================================================

from typing import Any

from pyspark import pipelines as dp
from pyspark.sql import functions as F

spark: Any  # Injected by the Lakeflow runtime.

VOLUME_PATH = spark.conf.get("quetzal.volume_path")


# =============================================================================
# DIMENSIONES
# =============================================================================

@dp.table(
    name="bronze_paises",
    comment="Dimensión de países LATAM donde opera Quetzal Telecom"
)
def bronze_paises():
    return (
        spark.readStream.format("cloudFiles")
        .option("cloudFiles.format", "parquet")
        .load(f"{VOLUME_PATH}/dim_paises")
        .withColumn("_ingested_at", F.current_timestamp())
    )


@dp.table(
    name="bronze_segmentos",
    comment="Dimensión de segmentos comerciales: Personal, Comercial, Empresarial"
)
def bronze_segmentos():
    return (
        spark.readStream.format("cloudFiles")
        .option("cloudFiles.format", "parquet")
        .load(f"{VOLUME_PATH}/dim_segmentos")
        .withColumn("_ingested_at", F.current_timestamp())
    )


@dp.table(
    name="bronze_planes",
    comment="Dimensión de planes comerciales: Móvil, Internet, TV, Fija, Bundles"
)
def bronze_planes():
    return (
        spark.readStream.format("cloudFiles")
        .option("cloudFiles.format", "parquet")
        .load(f"{VOLUME_PATH}/dim_planes")
        .withColumn("_ingested_at", F.current_timestamp())
    )


@dp.table(
    name="bronze_torres_red",
    comment="Dimensión de torres de red (infraestructura celular)"
)
def bronze_torres_red():
    return (
        spark.readStream.format("cloudFiles")
        .option("cloudFiles.format", "parquet")
        .load(f"{VOLUME_PATH}/dim_torres_red")
        .withColumn("_ingested_at", F.current_timestamp())
    )


# =============================================================================
# HECHOS — Clientes y Contratos
# =============================================================================

@dp.table(
    name="bronze_clientes",
    comment="Registro maestro de clientes — 1M clientes en 12 países"
)
def bronze_clientes():
    return (
        spark.readStream.format("cloudFiles")
        .option("cloudFiles.format", "parquet")
        .load(f"{VOLUME_PATH}/fact_clientes")
        .withColumn("_ingested_at", F.current_timestamp())
    )


@dp.table(
    name="bronze_suscripciones",
    comment="Contratos/suscripciones de servicios — ~1.6M registros"
)
def bronze_suscripciones():
    return (
        spark.readStream.format("cloudFiles")
        .option("cloudFiles.format", "parquet")
        .load(f"{VOLUME_PATH}/fact_suscripciones")
        .withColumn("_ingested_at", F.current_timestamp())
    )


@dp.table(
    name="bronze_facturas",
    comment="Facturas mensuales de billing — ~14M registros"
)
def bronze_facturas():
    return (
        spark.readStream.format("cloudFiles")
        .option("cloudFiles.format", "parquet")
        .load(f"{VOLUME_PATH}/fact_facturas")
        .withColumn("_ingested_at", F.current_timestamp())
    )


# =============================================================================
# HECHOS — Red y Comunicaciones
# =============================================================================

@dp.table(
    name="bronze_cdrs",
    comment="Call Detail Records (CDRs) — ~33M registros de eventos móviles"
)
def bronze_cdrs():
    return (
        spark.readStream.format("cloudFiles")
        .option("cloudFiles.format", "parquet")
        .load(f"{VOLUME_PATH}/fact_cdrs")
        .withColumn("_ingested_at", F.current_timestamp())
    )


@dp.table(
    name="bronze_telemetria_red",
    comment="Telemetría horaria de torres de red — ~1M registros"
)
def bronze_telemetria_red():
    return (
        spark.readStream.format("cloudFiles")
        .option("cloudFiles.format", "parquet")
        .load(f"{VOLUME_PATH}/fact_telemetria_red")
        .withColumn("_ingested_at", F.current_timestamp())
    )


# =============================================================================
# HECHOS — Experiencia del Cliente
# =============================================================================

@dp.table(
    name="bronze_tickets",
    comment="Tickets de atención al cliente — ~120K registros"
)
def bronze_tickets():
    return (
        spark.readStream.format("cloudFiles")
        .option("cloudFiles.format", "parquet")
        .load(f"{VOLUME_PATH}/fact_tickets")
        .withColumn("_ingested_at", F.current_timestamp())
    )


@dp.table(
    name="bronze_nps",
    comment="Encuestas Net Promoter Score — ~1.2M registros"
)
def bronze_nps():
    return (
        spark.readStream.format("cloudFiles")
        .option("cloudFiles.format", "parquet")
        .load(f"{VOLUME_PATH}/fact_nps")
        .withColumn("_ingested_at", F.current_timestamp())
    )


# =============================================================================
# HECHOS — ML Features
# =============================================================================

@dp.table(
    name="bronze_churn_features",
    comment="Features pre-calculadas para modelo de churn — 1M registros"
)
def bronze_churn_features():
    return (
        spark.readStream.format("cloudFiles")
        .option("cloudFiles.format", "parquet")
        .load(f"{VOLUME_PATH}/ml_churn_features")
        .withColumn("_ingested_at", F.current_timestamp())
    )
