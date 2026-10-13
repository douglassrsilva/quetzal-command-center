# Databricks notebook source
# ruff: noqa: F821 -- `%run`, `dbutils` and `spark` are notebook-runtime globals.
# DBTITLE 1,Quetzal Telecom — Data Generation Orchestrator
# =============================================================================
# QUETZAL TELECOM — ORQUESTRADOR DE GERAÇÃO DE DADOS SINTÉTICOS
# =============================================================================
# Executa todos os notebooks na ordem correta.
# Ideal para DABs: um único entry point reproduzível.
# =============================================================================

# DBTITLE 1,Configuração parametrizada
# MAGIC %run ./00_config

# COMMAND ----------

import os
from datetime import UTC, datetime
from typing import Any

dbutils: Any  # Injected by the Databricks notebook runtime.
spark: Any  # Injected by the Databricks notebook runtime.
CATALOG: str  # Defined by %run ./00_config.
SCHEMA: str
VOLUME: str
VOLUME_PATH: str
SEED: int
REFERENCE_DATE: str
NUM_CUSTOMERS: int
MONTHS_HISTORY: int
CDR_PER_CUSTOMER: int
TICKETS_PER_1000: int
NPS_SAMPLE_RATE: float
CHURN_LABEL_HORIZON_DAYS: int

NOTEBOOK_ARGUMENTS = {
    "catalog": CATALOG,
    "schema": SCHEMA,
    "raw_volume": VOLUME,
    "seed": str(SEED),
    "reference_date": REFERENCE_DATE,
    "num_customers": str(NUM_CUSTOMERS),
    "months_history": str(MONTHS_HISTORY),
    "cdr_per_customer": str(CDR_PER_CUSTOMER),
    "tickets_per_1000": str(TICKETS_PER_1000),
    "nps_sample_rate": str(NPS_SAMPLE_RATE),
    "churn_label_horizon_days": str(CHURN_LABEL_HORIZON_DAYS),
}

start = datetime.now(UTC)
print(f"\n{'='*60}")
print("  QUETZAL TELECOM — Data Generation")
print(f"  Iniciado: {start.strftime('%Y-%m-%d %H:%M:%S')}")
print(f"{'='*60}\n")

# COMMAND ----------

# DBTITLE 1,Step 1: Dimensões base
print("[1/5] Gerando dimensões base...")
dbutils.notebook.run("./01_dimensiones", timeout_seconds=600, arguments=NOTEBOOK_ARGUMENTS)
print("✓ Dimensões completas\n")

# COMMAND ----------

# DBTITLE 1,Step 2: Clientes
print(f"[2/5] Gerando {NUM_CUSTOMERS:,} clientes sintéticos...")
dbutils.notebook.run("./02_clientes", timeout_seconds=600, arguments=NOTEBOOK_ARGUMENTS)
print("✓ Clientes completos\n")

# COMMAND ----------

# DBTITLE 1,Step 3: Subscrições e Billing
print("[3/5] Gerando subscrições e faturas...")
dbutils.notebook.run("./03_suscripciones_billing", timeout_seconds=900, arguments=NOTEBOOK_ARGUMENTS)
print("✓ Subscrições e billing completos\n")

# COMMAND ----------

# DBTITLE 1,Step 4: CDRs e Telemetria de Rede
print("[4/5] Gerando CDRs e telemetria de rede...")
dbutils.notebook.run("./04_red_cdrs", timeout_seconds=1200, arguments=NOTEBOOK_ARGUMENTS)
print("✓ CDRs e telemetria completos\n")

# COMMAND ----------

# DBTITLE 1,Step 5: Churn, Tickets e NPS
print("[5/5] Gerando churn features, tickets e NPS...")
dbutils.notebook.run("./05_churn_interacciones", timeout_seconds=900, arguments=NOTEBOOK_ARGUMENTS)
print("✓ Churn e interações completos\n")

# COMMAND ----------

# DBTITLE 1,Validação final
end = datetime.now(UTC)
print(f"\n{'='*60}")
print("  QUETZAL TELECOM — Geração Completa")
print(f"  Finalizado: {end.strftime('%Y-%m-%d %H:%M:%S')}")
print(f"  Duração: {end - start}")
print(f"{'='*60}\n")

# Listar todos os parquets gerados
print("Datasets gerados:")
for item in os.listdir(VOLUME_PATH):
    full = f"{VOLUME_PATH}/{item}"
    if os.path.isdir(full):
        # Contar registros
        df = spark.read.parquet(full)
        count = df.count()
        print(f"  ✓ {item:30s} {count:>12,} registros")

print(f"\n✓ Todos os dados estão em: {VOLUME_PATH}")
print("✓ Prontos para ingestão via Delta Lake / DABs")
