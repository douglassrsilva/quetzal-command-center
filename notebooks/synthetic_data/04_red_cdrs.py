# Databricks notebook source
# DBTITLE 1,Run Config
# MAGIC %run ./00_config

# COMMAND ----------

# DBTITLE 1,Gerar CDRs via Spark nativo (escalável)
from pyspark.sql import functions as F
from pyspark.sql.types import *

# Usar Spark nativo para gerar CDRs em escala (evita loop Python)
# ~50 CDRs por cliente = ~5M registros

df_clientes = spark.read.parquet(f"{VOLUME_PATH}/fact_clientes")
df_torres = spark.read.parquet(f"{VOLUME_PATH}/dim_torres_red")

# Clientes ativos com subscrição móvel
df_subs = spark.read.parquet(f"{VOLUME_PATH}/fact_suscripciones")
df_movil_subs = (
    df_subs
    .filter(F.col("estado") == "activa")
    .filter(F.col("plan_id").startswith("MOV") | F.col("plan_id").startswith("BND"))
    .select("cliente_id", "suscripcion_id", "plan_id")
    .join(df_clientes.select("cliente_id", "pais_codigo"), "cliente_id")
)

print(f"✓ Subscrições móveis/bundle ativas: {df_movil_subs.count():,}")

# COMMAND ----------

# DBTITLE 1,Gerar CDRs com Spark (explosão + randomização)
# Explodir cada subscrição em ~50 CDRs distribuídos nos últimos 30 dias
df_cdrs = (
    df_movil_subs
    # Repetir cada linha ~50 vezes
    .withColumn("repeat", F.explode(F.sequence(F.lit(1), F.lit(CDR_PER_CUSTOMER))))
    # Timestamp aleatório nos últimos 30 dias
    .withColumn("timestamp_epoch",
        F.unix_timestamp(F.date_sub(F.to_date(F.lit(REFERENCE_DATE)), 30)) + 
        (F.rand(SEED) * 30 * 24 * 3600).cast("long")
    )
    .withColumn("fecha_hora", F.from_unixtime("timestamp_epoch").cast("timestamp"))
    .withColumn("fecha", F.to_date("fecha_hora"))
    # Tipo de evento
    .withColumn("tipo_evento",
        F.when(F.rand(SEED+1) < 0.35, "voz_saliente")
         .when(F.rand(SEED+2) < 0.55, "voz_entrante")
         .when(F.rand(SEED+3) < 0.75, "datos")
         .when(F.rand(SEED+4) < 0.90, "sms_saliente")
         .otherwise("sms_entrante")
    )
    # Duração (voz) ou volume (dados)
    .withColumn("duracion_seg",
        F.when(F.col("tipo_evento").contains("voz"), (F.rand(SEED+5) * 600 + 10).cast("int"))
         .otherwise(F.lit(0))
    )
    .withColumn("datos_mb",
        F.when(F.col("tipo_evento") == "datos", (F.rand(SEED+6) * 500 + 1).cast("double"))
         .otherwise(F.lit(0.0))
    )
    # Qualidade
    .withColumn("calidad_señal_dbm", (-40 - F.rand(SEED+7) * 80).cast("int"))
    .withColumn("tecnologia_red",
        F.when(F.rand(SEED+8) < 0.30, "5G")
         .when(F.rand(SEED+9) < 0.75, "4G")
         .otherwise("3G")
    )
    .withColumn("llamada_caida",
        F.when(F.col("tipo_evento").contains("voz"), F.rand(SEED+10) < 0.02)
         .otherwise(F.lit(False))
    )
    # CDR ID determinístico
    .withColumn("cdr_id", F.concat(F.lit("CDR-"), F.md5(F.concat("cliente_id", F.col("repeat").cast("string"), F.col("timestamp_epoch").cast("string")))))
    .drop("repeat", "timestamp_epoch")
)

print(f"✓ CDRs gerados: {df_cdrs.count():,}")

# COMMAND ----------

# DBTITLE 1,Salvar CDRs particionados por fecha
df_cdrs_final = df_cdrs.select(
    "cdr_id", "cliente_id", "suscripcion_id", "plan_id", "pais_codigo",
    "fecha_hora", "fecha", "tipo_evento", "duracion_seg", "datos_mb",
    "calidad_señal_dbm", "tecnologia_red", "llamada_caida"
)

df_cdrs_final.write.mode("overwrite").partitionBy("fecha").parquet(f"{VOLUME_PATH}/fact_cdrs")
print("✓ fact_cdrs salvo (particionado por fecha)")
print(f"  Registros: {df_cdrs_final.count():,}")
df_cdrs_final.groupBy("tipo_evento").count().orderBy(F.desc("count")).show()
df_cdrs_final.groupBy("tecnologia_red").count().orderBy(F.desc("count")).show()

# COMMAND ----------

# DBTITLE 1,Gerar eventos de rede (telemetria de torres)
# Telemetria: métricas de desempenho por torre a cada hora nos últimos 30 dias
df_torres = spark.read.parquet(f"{VOLUME_PATH}/dim_torres_red")

df_telemetria = (
    df_torres.select("torre_id", "pais_codigo", "ciudad", "tecnologia", "capacidad_usuarios")
    # 720 horas (30 dias)
    .withColumn("hora_offset", F.explode(F.sequence(F.lit(0), F.lit(719))))
    .withColumn("timestamp",
        F.from_unixtime(
            F.unix_timestamp(F.date_sub(F.to_date(F.lit(REFERENCE_DATE)), 30)) + F.col("hora_offset") * 3600
        ).cast("timestamp")
    )
    # Métricas de rede
    .withColumn("usuarios_conectados",
        (F.col("capacidad_usuarios") * (0.3 + F.rand(SEED+20) * 0.5)).cast("int")
    )
    .withColumn("uso_capacidad_pct",
        F.round(F.col("usuarios_conectados") / F.col("capacidad_usuarios") * 100, 1)
    )
    .withColumn("throughput_mbps",
        F.round(50 + F.rand(SEED+21) * 450, 1)
    )
    .withColumn("latencia_ms",
        F.round(5 + F.rand(SEED+22) * 45, 1)
    )
    .withColumn("packet_loss_pct",
        F.round(F.rand(SEED+23) * 2, 3)
    )
    .withColumn("temperatura_equipo_c",
        F.round(25 + F.rand(SEED+24) * 40, 1)
    )
    .withColumn("alerta",
        F.when(F.col("uso_capacidad_pct") > 85, "capacidad_alta")
         .when(F.col("latencia_ms") > 40, "latencia_alta")
         .when(F.col("packet_loss_pct") > 1.5, "packet_loss_alto")
         .when(F.col("temperatura_equipo_c") > 55, "temperatura_alta")
         .otherwise("normal")
    )
    .drop("hora_offset")
)

df_telemetria.write.mode("overwrite").parquet(f"{VOLUME_PATH}/fact_telemetria_red")
print(f"✓ fact_telemetria_red salvo: {df_telemetria.count():,} registros")
df_telemetria.groupBy("alerta").count().orderBy(F.desc("count")).show()
