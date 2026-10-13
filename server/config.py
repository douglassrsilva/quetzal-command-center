"""Environment-driven configuration for Quetzal.

Databricks Apps injects authentication variables at runtime. Product resource
identifiers remain configurable so the same source can be promoted without
editing Python code.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

COUNTRIES = ("PA", "MX", "CO", "BR", "AR", "CL", "PE", "EC", "CR", "GT", "DO", "UY")


def _host(value: str) -> str:
    value = value.strip().rstrip("/")
    if value and not value.startswith(("http://", "https://")):
        value = f"https://{value}"
    return value


def _optional_url(value: str) -> str:
    return "" if value.strip().upper() in {"", "DISABLED", "NONE"} else _host(value)


def _positive_int(name: str, default: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise RuntimeError(f"{name} must be an integer") from exc
    if value <= 0:
        raise RuntimeError(f"{name} must be greater than zero")
    return value


@dataclass(frozen=True)
class Settings:
    catalog: str
    schema: str
    host: str
    warehouse_id: str
    workspace_id: str
    dashboard_id: str
    ai_model: str
    ai_url: str
    genie_ingresos_id: str
    genie_clientes_id: str
    genie_red_id: str
    graph_job_id: str
    ontobricks_url: str
    ontobricks_mcp_url: str
    ontobricks_domain: str
    ontobricks_version: str
    sql_timeout_seconds: int
    sql_cache_ttl_seconds: int

    @classmethod
    def from_env(cls) -> Settings:
        catalog = os.getenv("QUETZAL_CATALOG", "classic_stable_douglas_s_catalog")
        schema = os.getenv("QUETZAL_SCHEMA", "quetzal_telecom")
        host = _host(
            os.getenv("DATABRICKS_HOST")
            or os.getenv("APP_HOST")
            or "https://fevm-classic-stable-douglas-s.cloud.databricks.com"
        )
        ai_model = os.getenv("QUETZAL_AI_MODEL", f"{catalog}.{schema}.quetzal-telecom-asistente")
        return cls(
            catalog=catalog,
            schema=schema,
            host=host,
            warehouse_id=os.getenv("DATABRICKS_WAREHOUSE_ID", "032931930451e566"),
            workspace_id=os.getenv("DATABRICKS_WORKSPACE_ID", os.getenv("WORKSPACE_ID", "7474654097678606")),
            dashboard_id=os.getenv("QUETZAL_DASHBOARD_ID", "01f1a73df38b1c91b35a5f7ca8c8d732"),
            ai_model=ai_model,
            ai_url=os.getenv("QUETZAL_AI_URL", f"{host}/ai-gateway/mlflow/v1/responses"),
            genie_ingresos_id=os.getenv("QUETZAL_GENIE_INGRESOS_ID", "01f1a73aa3281f5c815254ce86ca7408"),
            genie_clientes_id=os.getenv("QUETZAL_GENIE_CLIENTES_ID", "01f1a73ad42a198b8b9d29e9a3d081c8"),
            genie_red_id=os.getenv("QUETZAL_GENIE_RED_ID", "01f1a73ad42a1a72b2a813a1a9198e82"),
            graph_job_id=os.getenv("QUETZAL_GRAPH_JOB_ID", ""),
            ontobricks_url=_optional_url(os.getenv("QUETZAL_ONTOBRICKS_URL", "DISABLED")),
            ontobricks_mcp_url=_optional_url(
                os.getenv("QUETZAL_ONTOBRICKS_MCP_URL", "DISABLED")
            ),
            ontobricks_domain=os.getenv("QUETZAL_ONTOBRICKS_DOMAIN", "quetzal_telecom"),
            ontobricks_version=os.getenv(
                "QUETZAL_ONTOBRICKS_VERSION",
                "0.8.1+b7dc8798dee5351ccc146cb32f90976d13287535",
            ),
            sql_timeout_seconds=_positive_int("QUETZAL_SQL_TIMEOUT_SECONDS", 60),
            sql_cache_ttl_seconds=_positive_int("QUETZAL_SQL_CACHE_TTL_SECONDS", 30),
        )

    @property
    def dashboard_url(self) -> str:
        return f"{self.host}/embed/dashboardsv3/{self.dashboard_id}?o={self.workspace_id}"

    @property
    def genie_spaces(self) -> dict[str, dict[str, str]]:
        return {
            "ingresos": {"id": self.genie_ingresos_id, "name": "Ingresos y Facturación", "icon": "dollar-sign"},
            "clientes": {"id": self.genie_clientes_id, "name": "Inteligencia de Clientes", "icon": "users"},
            "red": {"id": self.genie_red_id, "name": "Operaciones de Red", "icon": "radio-tower"},
        }


settings = Settings.from_env()
