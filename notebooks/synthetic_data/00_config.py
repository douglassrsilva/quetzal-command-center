# Databricks notebook source
# ruff: noqa: F821 -- `dbutils` is injected by the notebook runtime.
# DBTITLE 1,Quetzal Telecom — Configuração Central
# =============================================================================
# QUETZAL TELECOM — CONFIGURAÇÃO CENTRAL DO PROJETO
# =============================================================================
# Este notebook define todas as constantes, caminhos e parâmetros reutilizados
# pelos demais notebooks de geração de dados sintéticos.
# Seed fixa garante reprodutibilidade total para DABs.
# =============================================================================

from typing import Any

dbutils: Any  # Injected by the Databricks notebook runtime.

# ---- Parâmetros recebidos pelo job DAB ou definidos para execução isolada ----
def _param(name, default):
    try:
        return dbutils.widgets.get(name)
    except Exception:  # noqa: BLE001 -- widget absence is surfaced as a runtime-specific exception
        dbutils.widgets.text(name, str(default))
        return dbutils.widgets.get(name)


# ---- Unity Catalog ----
CATALOG = _param("catalog", "quetzal_catalog")
SCHEMA = _param("schema", "quetzal_telecom")
VOLUME = _param("raw_volume", "raw_data")
VOLUME_PATH = f"/Volumes/{CATALOG}/{SCHEMA}/{VOLUME}"

# ---- Reprodutibilidade ----
SEED = int(_param("seed", "42"))
REFERENCE_DATE = _param("reference_date", "2026-09-01")

# ---- Escala dos dados sintéticos ----
NUM_CUSTOMERS = int(_param("num_customers", "1000000"))
MONTHS_HISTORY = int(_param("months_history", "12"))
CDR_PER_CUSTOMER = int(_param("cdr_per_customer", "50"))
TICKETS_PER_1000 = int(_param("tickets_per_1000", "120"))
NPS_SAMPLE_RATE = float(_param("nps_sample_rate", "0.10"))
CHURN_LABEL_HORIZON_DAYS = int(_param("churn_label_horizon_days", "30"))
TORRES_POR_CIUDAD   = (20, 60)    # range de torres por cidade

# ---- Países (12) ----
PAISES = [
    {"codigo": "PA", "nombre": "Panamá",       "moneda": "USD", "prefijo": "+507", "peso_clientes": 0.08, "timezone": "America/Panama"},
    {"codigo": "CO", "nombre": "Colombia",     "moneda": "COP", "prefijo": "+57",  "peso_clientes": 0.18, "timezone": "America/Bogota"},
    {"codigo": "MX", "nombre": "México",       "moneda": "MXN", "prefijo": "+52",  "peso_clientes": 0.20, "timezone": "America/Mexico_City"},
    {"codigo": "BR", "nombre": "Brasil",       "moneda": "BRL", "prefijo": "+55",  "peso_clientes": 0.15, "timezone": "America/Sao_Paulo"},
    {"codigo": "AR", "nombre": "Argentina",    "moneda": "ARS", "prefijo": "+54",  "peso_clientes": 0.10, "timezone": "America/Buenos_Aires"},
    {"codigo": "CL", "nombre": "Chile",        "moneda": "CLP", "prefijo": "+56",  "peso_clientes": 0.07, "timezone": "America/Santiago"},
    {"codigo": "PE", "nombre": "Perú",         "moneda": "PEN", "prefijo": "+51",  "peso_clientes": 0.06, "timezone": "America/Lima"},
    {"codigo": "EC", "nombre": "Ecuador",      "moneda": "USD", "prefijo": "+593", "peso_clientes": 0.04, "timezone": "America/Guayaquil"},
    {"codigo": "CR", "nombre": "Costa Rica",   "moneda": "CRC", "prefijo": "+506", "peso_clientes": 0.03, "timezone": "America/Costa_Rica"},
    {"codigo": "GT", "nombre": "Guatemala",    "moneda": "GTQ", "prefijo": "+502", "peso_clientes": 0.03, "timezone": "America/Guatemala"},
    {"codigo": "DO", "nombre": "Rep. Dominicana", "moneda": "DOP", "prefijo": "+1809", "peso_clientes": 0.03, "timezone": "America/Santo_Domingo"},
    {"codigo": "UY", "nombre": "Uruguay",      "moneda": "UYU", "prefijo": "+598", "peso_clientes": 0.03, "timezone": "America/Montevideo"},
]

# ---- Segmentos ----
SEGMENTOS = [
    {"id": "PER", "nombre": "Personal",    "marca": "Quetzal Life",       "peso": 0.70},
    {"id": "BIZ", "nombre": "Comercial",   "marca": "Quetzal Biz",        "peso": 0.22},
    {"id": "ENT", "nombre": "Empresarial", "marca": "Quetzal Enterprise", "peso": 0.08},
]

# ---- Planos ----
PLANES = [
    # Móvil
    {"plan_id": "MOV-PRE-01", "nombre": "Móvil Prepago Básico",  "vertical": "Movil",    "segmento": "PER", "precio_usd": 8.0,   "data_gb": 3,   "minutos": 100,  "tv_canales": 0,  "internet_mbps": 0},
    {"plan_id": "MOV-PRE-02", "nombre": "Móvil Prepago Plus",    "vertical": "Movil",    "segmento": "PER", "precio_usd": 15.0,  "data_gb": 10,  "minutos": 500,  "tv_canales": 0,  "internet_mbps": 0},
    {"plan_id": "MOV-POS-01", "nombre": "Móvil Postpago Pro",    "vertical": "Movil",    "segmento": "PER", "precio_usd": 35.0,  "data_gb": 50,  "minutos": 9999, "tv_canales": 0,  "internet_mbps": 0},
    {"plan_id": "MOV-POS-02", "nombre": "Móvil Postpago Ultra",  "vertical": "Movil",    "segmento": "PER", "precio_usd": 55.0,  "data_gb": 100, "minutos": 9999, "tv_canales": 0,  "internet_mbps": 0},
    {"plan_id": "MOV-BIZ-01", "nombre": "Biz Móvil Fleet",       "vertical": "Movil",    "segmento": "BIZ", "precio_usd": 28.0,  "data_gb": 30,  "minutos": 9999, "tv_canales": 0,  "internet_mbps": 0},
    {"plan_id": "MOV-ENT-01", "nombre": "Enterprise Mobile",     "vertical": "Movil",    "segmento": "ENT", "precio_usd": 45.0,  "data_gb": 200, "minutos": 9999, "tv_canales": 0,  "internet_mbps": 0},
    # Internet
    {"plan_id": "INT-100",    "nombre": "Fibra Hogar 100",       "vertical": "Internet", "segmento": "PER", "precio_usd": 25.0,  "data_gb": 0,   "minutos": 0,    "tv_canales": 0,  "internet_mbps": 100},
    {"plan_id": "INT-300",    "nombre": "Fibra Hogar 300",       "vertical": "Internet", "segmento": "PER", "precio_usd": 40.0,  "data_gb": 0,   "minutos": 0,    "tv_canales": 0,  "internet_mbps": 300},
    {"plan_id": "INT-500",    "nombre": "Fibra Hogar 500",       "vertical": "Internet", "segmento": "PER", "precio_usd": 55.0,  "data_gb": 0,   "minutos": 0,    "tv_canales": 0,  "internet_mbps": 500},
    {"plan_id": "INT-BIZ-01", "nombre": "Biz Internet Pro",      "vertical": "Internet", "segmento": "BIZ", "precio_usd": 80.0,  "data_gb": 0,   "minutos": 0,    "tv_canales": 0,  "internet_mbps": 500},
    {"plan_id": "INT-ENT-01", "nombre": "Enterprise Fiber",      "vertical": "Internet", "segmento": "ENT", "precio_usd": 250.0, "data_gb": 0,   "minutos": 0,    "tv_canales": 0,  "internet_mbps": 1000},
    # TV
    {"plan_id": "TV-BAS-01",  "nombre": "TV Esencial",           "vertical": "TV",       "segmento": "PER", "precio_usd": 12.0,  "data_gb": 0,   "minutos": 0,    "tv_canales": 80,  "internet_mbps": 0},
    {"plan_id": "TV-TOT-01",  "nombre": "Quetzal TV Total",      "vertical": "TV",       "segmento": "PER", "precio_usd": 30.0,  "data_gb": 0,   "minutos": 0,    "tv_canales": 280, "internet_mbps": 0},
    {"plan_id": "TV-BIZ-01",  "nombre": "Biz TV Hospitality",    "vertical": "TV",       "segmento": "BIZ", "precio_usd": 65.0,  "data_gb": 0,   "minutos": 0,    "tv_canales": 200, "internet_mbps": 0},
    # Fija
    {"plan_id": "FIJ-PER-01", "nombre": "Línea Hogar",           "vertical": "Fija",     "segmento": "PER", "precio_usd": 10.0,  "data_gb": 0,   "minutos": 500,  "tv_canales": 0,  "internet_mbps": 0},
    {"plan_id": "FIJ-BIZ-01", "nombre": "Biz SIP Trunk",         "vertical": "Fija",     "segmento": "BIZ", "precio_usd": 45.0,  "data_gb": 0,   "minutos": 9999, "tv_canales": 0,  "internet_mbps": 0},
    {"plan_id": "FIJ-ENT-01", "nombre": "Enterprise PBX Cloud",  "vertical": "Fija",     "segmento": "ENT", "precio_usd": 180.0, "data_gb": 0,   "minutos": 9999, "tv_canales": 0,  "internet_mbps": 0},
    # Bundles
    {"plan_id": "BND-FAM-01", "nombre": "Paquete Familia",       "vertical": "Bundle",   "segmento": "PER", "precio_usd": 75.0,  "data_gb": 50,  "minutos": 9999, "tv_canales": 200, "internet_mbps": 300},
    {"plan_id": "BND-BIZ-01", "nombre": "Paquete Negocio Total", "vertical": "Bundle",   "segmento": "BIZ", "precio_usd": 150.0, "data_gb": 100, "minutos": 9999, "tv_canales": 100, "internet_mbps": 500},
    {"plan_id": "BND-ENT-01", "nombre": "Enterprise Full Stack", "vertical": "Bundle",   "segmento": "ENT", "precio_usd": 500.0, "data_gb": 500, "minutos": 9999, "tv_canales": 280, "internet_mbps": 1000},
]

print("✓ Configuração carregada")
print(f"  Catálogo:  {CATALOG}")
print(f"  Schema:    {SCHEMA}")
print(f"  Volume:    {VOLUME_PATH}")
print(f"  Países:    {len(PAISES)}")
print(f"  Segmentos: {len(SEGMENTOS)}")
print(f"  Planos:    {len(PLANES)}")
print(f"  Clientes:  {NUM_CUSTOMERS:,}")
print(f"  Seed:      {SEED}")
print(f"  Data ref.: {REFERENCE_DATE}")
print(f"  Horizonte churn: {CHURN_LABEL_HORIZON_DAYS} dias")
print("  Origem:    synthetic_demo")
