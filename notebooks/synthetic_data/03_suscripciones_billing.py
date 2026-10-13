# Databricks notebook source
# DBTITLE 1,Run Config
# MAGIC %run ./00_config

# COMMAND ----------

# DBTITLE 1,Carregar dados base
from pyspark.sql import functions as F
from pyspark.sql.types import *
from pyspark.sql.window import Window

df_clientes = spark.read.parquet(f"{VOLUME_PATH}/fact_clientes")
df_planes_raw = spark.read.parquet(f"{VOLUME_PATH}/dim_planes")

# Indexar planos dentro de cada segmento para seleção determinística
df_planes = (
    df_planes_raw
    .withColumn("_plan_rn", F.row_number().over(Window.partitionBy("segmento").orderBy("plan_id")))
    .withColumn("_plan_count", F.count("*").over(Window.partitionBy("segmento")))
)

print(f"✓ Clientes: {df_clientes.count():,}")
print(f"✓ Planos: {df_planes.count()} ({df_planes_raw.select('segmento').distinct().count()} segmentos)")

# COMMAND ----------

# DBTITLE 1,Gerar subscrições — 100% Spark nativo
# =============================================================================
# SUBSCRIÇÕES — 100% Spark nativo, sem loops Python
# Estratégia: explodir clientes em N linhas, join com planos por segmento
# =============================================================================

# 1) Determinar número de subs por cliente e explodir
df_cli = (
    df_clientes
    .select("cliente_id", "segmento_id", "fecha_alta", "estado")
    .withColumn("num_subs",
        F.when(F.col("segmento_id") == "ENT", 3)
         .when(F.col("segmento_id") == "BIZ", 2)
         .otherwise(F.when(F.rand(SEED + 20) < 0.6, 1).otherwise(2))
    )
    .withColumn("sub_seq", F.explode(F.sequence(F.lit(1), F.col("num_subs"))))
)

# 2) Atribuir um plano a cada sub_seq usando index determinístico
#    plan_rn = ((sub_seq - 1 + offset_random) % plans_in_segment) + 1
df_cli = (
    df_cli
    .withColumn("_plan_offset", (F.rand(SEED + 21) * 100).cast("int"))
    .join(
        df_planes.select(
            F.col("segmento").alias("_seg"),
            F.col("_plan_count"),
        ).distinct(),
        F.col("segmento_id") == F.col("_seg"), "inner"
    )
    .withColumn("_target_rn",
        ((F.col("sub_seq") - 1 + F.col("_plan_offset")) % F.col("_plan_count")) + 1
    )
    .drop("_seg")
)

# 3) Join com planos indexados
df_subs_raw = (
    df_cli
    .join(
        df_planes.select(
            F.col("segmento").alias("_seg2"),
            F.col("plan_id"),
            F.col("precio_usd"),
            F.col("_plan_rn")
        ),
        (F.col("segmento_id") == F.col("_seg2")) & (F.col("_target_rn") == F.col("_plan_rn")),
        "inner"
    )
)

# 4) Gerar campos da subscrição
metodo_expr = (
    F.when(F.col("_rm") < 0.35, "tarjeta_credito")
     .when(F.col("_rm") < 0.60, "tarjeta_debito")
     .when(F.col("_rm") < 0.75, "transferencia")
     .when(F.col("_rm") < 0.90, "efectivo")
     .otherwise("wallet_digital")
)

dias_facturacion = F.array(*[F.lit(d) for d in [1, 5, 10, 15, 20, 25]])

df_subs = (
    df_subs_raw
    .withColumn("_rm", F.rand(SEED + 22))
    .withColumn("_rpr", F.rand(SEED + 23))
    .withColumn("_rdia", F.rand(SEED + 24))
    .withColumn("_rest2", F.rand(SEED + 25))
    .withColumn("_rstart", F.rand(SEED + 26))
    .withColumn("_rfin", F.rand(SEED + 27))
    # Subscription ID
    .withColumn("suscripcion_id", F.concat(F.lit("SUB-"), F.monotonically_increasing_id()))
    # Fecha inicio: entre fecha_alta y la fecha de referencia parametrizada
    .withColumn("_dias_posibles", F.greatest(F.lit(1), F.datediff(F.to_date(F.lit(REFERENCE_DATE)), F.col("fecha_alta")) - 30))
    .withColumn("fecha_inicio", F.date_add(F.col("fecha_alta"), (F.col("_rstart") * F.col("_dias_posibles")).cast("int")))
    # Estado: inactivo -> cancelada, activo -> 95% activa / 5% suspendida
    .withColumn("estado_sub",
        F.when(F.col("estado") == "inactivo", "cancelada")
         .when(F.col("_rest2") < 0.95, "activa")
         .otherwise("suspendida")
    )
    .withColumn("fecha_fin",
        F.when(F.col("estado_sub") == "cancelada",
            F.date_add(F.col("fecha_inicio"), (30 + F.col("_rfin") * 335).cast("int"))
        )
    )
    # Preço com variação ±15%
    .withColumn("precio_mensual_usd", F.round(F.col("precio_usd") * (0.85 + F.col("_rpr") * 0.30), 2))
    .withColumn("metodo_pago", metodo_expr)
    .withColumn("facturacion_dia", dias_facturacion[(F.col("_rdia") * 6).cast("int")])
    .withColumn("auto_renovacion", F.rand(SEED + 28) > 0.1)
    .select(
        "suscripcion_id", "cliente_id", "plan_id", "fecha_inicio", "fecha_fin",
        F.col("estado_sub").alias("estado"), "precio_mensual_usd",
        "metodo_pago", "facturacion_dia", "auto_renovacion"
    )
)

df_subs.write.mode("overwrite").parquet(f"{VOLUME_PATH}/fact_suscripciones")
count_subs = spark.read.parquet(f"{VOLUME_PATH}/fact_suscripciones").count()
print(f"✓ fact_suscripciones: {count_subs:,} registros")
spark.read.parquet(f"{VOLUME_PATH}/fact_suscripciones").groupBy("estado").count().show()

# COMMAND ----------

# DBTITLE 1,Salvar subscrições (removido — integrado acima)
# Cell integrada acima — subscrições já salvas
print("✓ Subscrições salvas no step anterior")

# COMMAND ----------

# DBTITLE 1,Gerar faturas — 100% Spark nativo
# =============================================================================
# FATURAS — 100% Spark nativo
# Cada subscrição gera até 12 faturas mensais via explode(sequence)
# =============================================================================

df_subs = spark.read.parquet(f"{VOLUME_PATH}/fact_suscripciones")

# Calcular quantos meses de fatura cada sub tem (max 12)
df_subs_billing = (
    df_subs
    .withColumn(
        "_fecha_limite",
        F.least(
            F.coalesce(F.col("fecha_fin"), F.to_date(F.lit(REFERENCE_DATE))),
            F.to_date(F.lit(REFERENCE_DATE)),
        ),
    )
    .withColumn(
        "_fecha_inicio_billing",
        F.greatest(
            F.col("fecha_inicio"),
            F.add_months(F.to_date(F.lit(REFERENCE_DATE)), -MONTHS_HISTORY),
        ),
    )
    .withColumn("_meses",
        F.greatest(F.lit(0),
            F.least(F.lit(12),
                F.months_between(F.col("_fecha_limite"), F.col("_fecha_inicio_billing")).cast("int")
            )
        )
    )
    .filter(F.col("_meses") > 0)
)

# Explodir em faturas mensais
df_facturas = (
    df_subs_billing
    .withColumn("_mes_offset", F.explode(F.sequence(F.lit(0), F.col("_meses") - 1)))
    .withColumn("fecha_emision", F.add_months(F.col("_fecha_inicio_billing"), F.col("_mes_offset")))
    .withColumn("fecha_vencimiento", F.date_add(F.col("fecha_emision"), 15))
    # Randoms por fatura
    .withColumn("_raj", F.rand(SEED + 30))   # ajuste
    .withColumn("_ratr", F.rand(SEED + 31))  # atraso
    .withColumn("_rpag", F.rand(SEED + 32))  # dias pago
    # Ajustes (70% nenhum, 20% excedente, 10% desconto)
    .withColumn("ajustes_usd",
        F.when(F.col("_raj") < 0.70, 0.0)
         .when(F.col("_raj") < 0.90, F.round(F.col("precio_mensual_usd") * F.col("_raj") * 0.25, 2))
         .otherwise(F.round(-F.col("precio_mensual_usd") * F.col("_raj") * 0.10, 2))
    )
    .withColumn("monto_base_usd", F.col("precio_mensual_usd"))
    .withColumn("monto_total_usd", F.round(F.col("monto_base_usd") + F.col("ajustes_usd"), 2))
    # Atraso: 8% chance
    .withColumn("dias_atraso",
        F.when(F.col("_ratr") < 0.92, 0)
         .when(F.col("_ratr") < 0.953, 7)
         .when(F.col("_ratr") < 0.973, 15)
         .when(F.col("_ratr") < 0.989, 30)
         .when(F.col("_ratr") < 0.997, 60)
         .otherwise(90)
    )
    .withColumn("estado_pago",
        F.when(F.col("dias_atraso") == 0, "pagada")
         .when(F.col("dias_atraso") > 30, "vencida")
         .otherwise("pendiente")
    )
    .withColumn("fecha_pago",
        F.when(F.col("estado_pago") != "vencida",
            F.date_add(F.col("fecha_emision"), F.col("dias_atraso") + (F.col("_rpag") * 10).cast("int"))
        )
    )
    .withColumn("factura_id", F.concat(F.lit("INV-"), F.monotonically_increasing_id()))
    .select(
        "factura_id", "suscripcion_id", "cliente_id",
        "fecha_emision", "fecha_vencimiento",
        "monto_base_usd", "ajustes_usd", "monto_total_usd",
        "estado_pago", "dias_atraso", "fecha_pago"
    )
)

df_facturas.write.mode("overwrite").parquet(f"{VOLUME_PATH}/fact_facturas")
count_fact = spark.read.parquet(f"{VOLUME_PATH}/fact_facturas").count()
print(f"✓ fact_facturas: {count_fact:,} registros")
spark.read.parquet(f"{VOLUME_PATH}/fact_facturas").groupBy("estado_pago").count().orderBy(F.desc("count")).show()
