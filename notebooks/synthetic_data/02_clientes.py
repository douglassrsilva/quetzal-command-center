# Databricks notebook source
# DBTITLE 1,Run Config
# MAGIC %run ./00_config

# COMMAND ----------

# DBTITLE 1,Gerar 1M clientes — 100% Spark nativo
from pyspark.sql import functions as F
from pyspark.sql.types import *

# =============================================================================
# GERAÇÃO 100% SPARK NATIVO — 0 loops Python, escala a milhões
# =============================================================================

# Arrays de nomes broadcast como arrays Spark
nombres_m = F.array(*[F.lit(n) for n in [
    "Carlos","Juan","Luis","José","Miguel","Pedro","Andrés","Diego","Santiago","Sebastián",
    "Mateo","Daniel","Alejandro","Gabriel","Rafael","Fernando","Ricardo","Eduardo","Marcos",
    "Héctor","Pablo","Tomás","Nicolás","Emilio","Rodrigo","Javier","Oscar","Enrique","Mario","Hugo"]])

nombres_f = F.array(*[F.lit(n) for n in [
    "María","Ana","Luisa","Carmen","Laura","Sofía","Valentina","Camila","Isabella","Gabriela",
    "Andrea","Paula","Daniela","Fernanda","Catalina","Mariana","Natalia","Alejandra","Elena","Rosa",
    "Lucía","Jimena","Renata","Victoria","Julia","Florencia","Martina","Carla","Diana","Paola"]])

apellidos_arr = F.array(*[F.lit(a) for a in [
    "García","Rodríguez","Martínez","López","González","Hernández","Pérez","Sánchez","Ramírez",
    "Torres","Flores","Rivera","Gómez","Díaz","Cruz","Morales","Reyes","Gutiérrez","Ortiz","Ramos",
    "Mendoza","Castillo","Vargas","Chávez","Romero","Herrera","Medina","Aguilar","Vega","Castro",
    "Silva","Santos","Oliveira","Souza","Costa","Ferreira","Almeida","Pereira","Nascimento",
    "Cardoso","Ribeiro","Barros","Montoya","Suárez","Delgado"]])

dominios_arr = F.array(*[F.lit(d) for d in ["gmail.com","hotmail.com","yahoo.com","outlook.com","icloud.com","live.com","protonmail.com"]])

# País: distribuição por faixas acumuladas de rand()
pais_expr = (
    F.when(F.col("_rp") < 0.08, F.lit("PA"))
     .when(F.col("_rp") < 0.26, F.lit("CO"))
     .when(F.col("_rp") < 0.46, F.lit("MX"))
     .when(F.col("_rp") < 0.61, F.lit("BR"))
     .when(F.col("_rp") < 0.71, F.lit("AR"))
     .when(F.col("_rp") < 0.78, F.lit("CL"))
     .when(F.col("_rp") < 0.84, F.lit("PE"))
     .when(F.col("_rp") < 0.88, F.lit("EC"))
     .when(F.col("_rp") < 0.91, F.lit("CR"))
     .when(F.col("_rp") < 0.94, F.lit("GT"))
     .when(F.col("_rp") < 0.97, F.lit("DO"))
     .otherwise(F.lit("UY"))
)

seg_expr = (
    F.when(F.col("_rs") < 0.70, F.lit("PER"))
     .when(F.col("_rs") < 0.92, F.lit("BIZ"))
     .otherwise(F.lit("ENT"))
)

canal_expr = (
    F.when(F.col("_rc") < 0.30, F.lit("tienda"))
     .when(F.col("_rc") < 0.55, F.lit("web"))
     .when(F.col("_rc") < 0.70, F.lit("call_center"))
     .when(F.col("_rc") < 0.85, F.lit("dealer"))
     .otherwise(F.lit("app"))
)

prefijos = F.create_map(*[
    x for pair in [
        (F.lit("PA"), F.lit("+507")), (F.lit("CO"), F.lit("+57")), (F.lit("MX"), F.lit("+52")),
        (F.lit("BR"), F.lit("+55")), (F.lit("AR"), F.lit("+54")), (F.lit("CL"), F.lit("+56")),
        (F.lit("PE"), F.lit("+51")), (F.lit("EC"), F.lit("+593")), (F.lit("CR"), F.lit("+506")),
        (F.lit("GT"), F.lit("+502")), (F.lit("DO"), F.lit("+1809")), (F.lit("UY"), F.lit("+598"))
    ] for x in pair
])

# ---------- Geração do DataFrame ----------
df_clientes = (
    spark.range(0, NUM_CUSTOMERS)
    .withColumnRenamed("id", "_idx")
    # Randoms determinísticos (seed fixa por coluna)
    .withColumn("_rp", F.rand(SEED))        # país
    .withColumn("_rs", F.rand(SEED + 1))    # segmento
    .withColumn("_rc", F.rand(SEED + 2))    # canal
    .withColumn("_rn", F.rand(SEED + 3))    # nome
    .withColumn("_ra1", F.rand(SEED + 4))   # apellido1
    .withColumn("_ra2", F.rand(SEED + 5))   # apellido2
    .withColumn("_rd", F.rand(SEED + 6))    # domínio email
    .withColumn("_re", F.rand(SEED + 7))    # idade
    .withColumn("_rant", F.rand(SEED + 8))  # antiguidade
    .withColumn("_rcs", F.rand(SEED + 9))   # credit score
    .withColumn("_rnps", F.rand(SEED + 10)) # nps
    .withColumn("_rest", F.rand(SEED + 11)) # estado
    .withColumn("_rmkt", F.rand(SEED + 12)) # marketing
    .withColumn("_rsex", F.rand(SEED + 13)) # sexo
    .withColumn("_rtel", F.rand(SEED + 14)) # telefone
    
    # ID determinístico
    .withColumn("cliente_id", F.concat(F.lit("CLI-"), F.upper(F.substring(F.md5(F.concat(F.lit(f"QUETZAL-{SEED}-"), F.col("_idx").cast("string"))), 1, 12))))
    
    # Sexo
    .withColumn("sexo", F.when(F.col("_rsex") < 0.5, "M").otherwise("F"))
    
    # Nomes
    .withColumn("nombre",
        F.when(F.col("sexo") == "M", nombres_m[(F.col("_rn") * 30).cast("int")])
         .otherwise(nombres_f[(F.col("_rn") * 30).cast("int")]))
    .withColumn("apellido_1", apellidos_arr[(F.col("_ra1") * 45).cast("int")])
    .withColumn("apellido_2", apellidos_arr[(F.col("_ra2") * 45).cast("int")])
    .withColumn("nombre_completo", F.concat_ws(" ", "nombre", "apellido_1", "apellido_2"))
    
    # País, segmento, canal
    .withColumn("pais_codigo", pais_expr)
    .withColumn("segmento_id", seg_expr)
    .withColumn("canal_adquisicion", canal_expr)
    
    # Datas
    .withColumn("edad", (18 + F.col("_re") * 57).cast("int"))  # 18-75
    .withColumn("fecha_nacimiento", F.date_sub(F.lit(REFERENCE_DATE), F.col("edad") * 365 + (F.col("_rn") * 365).cast("int")))
    .withColumn("antiguedad_dias", (1 + F.col("_rant") * 2399).cast("int"))
    .withColumn("fecha_alta", F.date_sub(F.lit(REFERENCE_DATE), F.col("antiguedad_dias")))
    
    # Contato
    .withColumn("_email_name",
        F.lower(F.regexp_replace(F.concat_ws(".", "nombre", "apellido_1"),
            "[áéíóúñÁÉÍÓÚÑ]",
            F.when(F.lit(True), "x")  # placeholder — ver replace chain abaixo
        ))
    )
    .withColumn("_email_clean",
        F.regexp_replace(
        F.regexp_replace(
        F.regexp_replace(
        F.regexp_replace(
        F.regexp_replace(
        F.regexp_replace(
            F.lower(F.concat_ws(".", "nombre", "apellido_1")),
            "á", "a"), "é", "e"), "í", "i"), "ó", "o"), "ú", "u"), "ñ", "n")
    )
    .withColumn("email", F.concat(
        F.col("_email_clean"),
        (F.col("_rd") * 999 + 1).cast("int").cast("string"),
        F.lit("@"),
        dominios_arr[(F.col("_rd") * 7).cast("int")]
    ))
    .withColumn("telefono", F.concat(
        prefijos[F.col("pais_codigo")],
        (F.col("_rtel") * 89999999 + 10000000).cast("long").cast("string")
    ))
    
    # Scores e estado
    .withColumn("credit_score", F.greatest(F.lit(300), F.least(F.lit(850), (650 + (F.col("_rcs") - 0.5) * 300).cast("int"))))
    .withColumn("nps_ultimo", (F.col("_rnps") * 11).cast("int"))
    .withColumn("estado", F.when(F.col("_rest") < 0.05, "inactivo").otherwise("activo"))
    .withColumn("acepta_marketing", F.col("_rmkt") > 0.3)
    
    # Selecionar colunas finais
    .select(
        "cliente_id", "nombre", "apellido_1", "apellido_2", "nombre_completo",
        "sexo", "fecha_nacimiento", "edad", "email", "telefono",
        "pais_codigo", "segmento_id", "fecha_alta", "antiguedad_dias",
        "credit_score", "nps_ultimo", "canal_adquisicion", "estado", "acepta_marketing"
    )
)

print(f"✓ DataFrame Spark criado para {NUM_CUSTOMERS:,} clientes (lazy — 0 loops Python)")

# COMMAND ----------

# DBTITLE 1,Salvar 1M clientes em Parquet no Volume
# Materializar e salvar — Spark distribui automaticamente pelos workers
df_clientes.write.mode("overwrite").parquet(f"{VOLUME_PATH}/fact_clientes")

count = spark.read.parquet(f"{VOLUME_PATH}/fact_clientes").count()
print(f"✓ fact_clientes salvo: {count:,} registros")

# Validação de distribuições
df = spark.read.parquet(f"{VOLUME_PATH}/fact_clientes")
print("\nDistribuição por país:")
df.groupBy("pais_codigo").count().orderBy(F.desc("count")).show(12)
print("Distribuição por segmento:")
df.groupBy("segmento_id").count().orderBy(F.desc("count")).show()
print("Distribuição por estado:")
df.groupBy("estado").count().show()
print("Sample:")
df.show(5, truncate=False)
