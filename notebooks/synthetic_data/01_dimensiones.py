# Databricks notebook source
# DBTITLE 1,Run Config
# MAGIC %run ./00_config

# COMMAND ----------

# DBTITLE 1,Gerar tabela dim_paises
from pyspark.sql import functions as F
from pyspark.sql.types import *

# ---- dim_paises ----
df_paises = spark.createDataFrame(PAISES)
df_paises = (
    df_paises
    .withColumnRenamed("codigo", "pais_codigo")
    .withColumnRenamed("nombre", "pais_nombre")
    .withColumnRenamed("moneda", "moneda_local")
    .withColumnRenamed("prefijo", "prefijo_telefonico")
    .withColumnRenamed("peso_clientes", "distribucion_clientes")
    .withColumn("region", 
        F.when(F.col("pais_codigo").isin("MX", "GT", "CR", "PA", "DO"), "Centroamérica y Caribe")
         .when(F.col("pais_codigo").isin("CO", "EC", "PE"), "Andina")
         .when(F.col("pais_codigo").isin("BR"), "Brasil")
         .otherwise("Cono Sur")
    )
    .withColumn("pais_origen", F.col("pais_codigo") == "PA")
)

df_paises.write.mode("overwrite").parquet(f"{VOLUME_PATH}/dim_paises")
print(f"✓ dim_paises: {df_paises.count()} registros")
df_paises.show(truncate=False)

# COMMAND ----------

# DBTITLE 1,Gerar tabela dim_segmentos
# ---- dim_segmentos ----
df_segmentos = spark.createDataFrame(SEGMENTOS)
df_segmentos = (
    df_segmentos
    .withColumnRenamed("id", "segmento_id")
    .withColumnRenamed("nombre", "segmento_nombre")
    .withColumnRenamed("marca", "marca_comercial")
    .withColumnRenamed("peso", "distribucion")
)

df_segmentos.write.mode("overwrite").parquet(f"{VOLUME_PATH}/dim_segmentos")
print(f"✓ dim_segmentos: {df_segmentos.count()} registros")
df_segmentos.show(truncate=False)

# COMMAND ----------

# DBTITLE 1,Gerar tabela dim_planes
# ---- dim_planes ----
df_planes = spark.createDataFrame(PLANES)
df_planes = (
    df_planes
    .withColumn("es_bundle", F.col("vertical") == "Bundle")
    .withColumn("es_prepago", F.col("plan_id").contains("PRE"))
    .withColumn("tier", 
        F.when(F.col("precio_usd") < 20, "Básico")
         .when(F.col("precio_usd") < 60, "Estándar")
         .when(F.col("precio_usd") < 200, "Premium")
         .otherwise("Enterprise")
    )
)

df_planes.write.mode("overwrite").parquet(f"{VOLUME_PATH}/dim_planes")
print(f"✓ dim_planes: {df_planes.count()} registros")
df_planes.show(truncate=False)

# COMMAND ----------

# DBTITLE 1,Gerar tabela dim_torres_red
import random

random.seed(SEED)

# ---- dim_torres_red (cell towers) ----
# Gerar torres proporcionais à distribuição de clientes por país
CIDADES = {
    "PA": [("Ciudad de Panamá", 8.98, -79.52), ("Colón", 9.36, -79.90), ("David", 8.43, -82.43)],
    "CO": [("Bogotá", 4.71, -74.07), ("Medellín", 6.25, -75.56), ("Cali", 3.45, -76.53), ("Barranquilla", 10.96, -74.78)],
    "MX": [("CDMX", 19.43, -99.13), ("Guadalajara", 20.67, -103.35), ("Monterrey", 25.67, -100.31), ("Cancún", 21.16, -86.85)],
    "BR": [("São Paulo", -23.55, -46.63), ("Rio de Janeiro", -22.91, -43.17), ("Brasília", -15.79, -47.88), ("Recife", -8.05, -34.87)],
    "AR": [("Buenos Aires", -34.60, -58.38), ("Córdoba", -31.42, -64.18), ("Rosario", -32.95, -60.65)],
    "CL": [("Santiago", -33.45, -70.67), ("Valparaíso", -33.05, -71.62), ("Concepción", -36.83, -73.05)],
    "PE": [("Lima", -12.05, -77.03), ("Arequipa", -16.41, -71.54), ("Trujillo", -8.11, -79.04)],
    "EC": [("Quito", -0.18, -78.47), ("Guayaquil", -2.17, -79.92)],
    "CR": [("San José", 9.93, -84.08), ("Heredia", 10.00, -84.12)],
    "GT": [("Ciudad de Guatemala", 14.63, -90.51), ("Quetzaltenango", 14.83, -91.52)],
    "DO": [("Santo Domingo", 18.49, -69.93), ("Santiago", 19.45, -70.70)],
    "UY": [("Montevideo", -34.88, -56.17), ("Punta del Este", -34.97, -54.95)],
}

torres = []
torre_id = 1
for pais_code, ciudades in CIDADES.items():
    for ciudad, lat_base, lon_base in ciudades:
        # 15-40 torres por cidade
        n_torres = random.randint(15, 40)
        for _ in range(n_torres):
            torres.append({
                "torre_id": f"TWR-{pais_code}-{torre_id:05d}",
                "pais_codigo": pais_code,
                "ciudad": ciudad,
                "latitud": round(lat_base + random.uniform(-0.15, 0.15), 6),
                "longitud": round(lon_base + random.uniform(-0.15, 0.15), 6),
                "tecnologia": random.choices(["4G", "5G", "4G/5G"], weights=[0.4, 0.25, 0.35])[0],
                "capacidad_usuarios": random.choice([500, 1000, 2000, 5000]),
                "estado": random.choices(["activa", "mantenimiento", "degradada"], weights=[0.92, 0.05, 0.03])[0],
                "fecha_instalacion": f"{random.randint(2018, 2025)}-{random.randint(1,12):02d}-01",
            })
            torre_id += 1

df_torres = spark.createDataFrame(torres)
df_torres.write.mode("overwrite").parquet(f"{VOLUME_PATH}/dim_torres_red")
print(f"✓ dim_torres_red: {df_torres.count()} torres geradas")
df_torres.groupBy("pais_codigo").count().orderBy("pais_codigo").show()
