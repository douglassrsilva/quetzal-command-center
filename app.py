"""Quetzal Command Center — FastAPI Backend.

Enterprise telco dashboard with Genie Spaces, AI Gateway, Dashboard embedding,
and hyper-personalised reports via Databricks SQL.
"""

import json as _json
import logging
import os
import re as _re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from uuid import uuid4

import requests as http_requests
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from server.access import (
    assert_country_access,
    bind_access,
    country_predicate,
    identify_request,
    require_any_role,
    require_unrestricted_service,
    reset_access,
    resolve_access,
    submit_with_context,
)
from server.config import COUNTRIES, settings
from server.managed_memory import managed_agent_memory
from server.memory import conversation_store
from server.models import ChatRequest, GenieQueryRequest, GenieSpace, ReportRequest
from server.ontobricks import OntoBricksError, ontobricks_mcp
from server.operations import router as operations_router
from server.platform import (
    SqlExecutionError,
    SqlExecutionTimeout,
    auth_headers,
    execute_sql,
    run_sql,
)
from server.retention_cases import retention_case_store

logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"), format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("quetzal")
sql_fanout = ThreadPoolExecutor(max_workers=5, thread_name_prefix="quetzal-sql")

try:
    from ddgs import DDGS
    _HAS_DDGS = True
except ImportError:
    try:
        # Compatibility with installations created before the package rename.
        from duckduckgo_search import DDGS
        _HAS_DDGS = True
    except ImportError:
        _HAS_DDGS = False

_WEB_SEARCH_TOOL = {
    "type": "function",
    "name": "web_search",
    "description": (
        "Search the web for current real-time information. "
        "Use for weather, news, current events, prices, sports results, "
        "and any question that requires up-to-date data."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Search query"}
        },
        "required": ["query"],
    },
}

_TELECOM_SNAPSHOT_TOOL = {
    "type": "function",
    "name": "telecom_snapshot",
    "description": (
        "Obtiene métricas internas gobernadas de Quetzal Telecom. "
        "Usa esta función para preguntas sobre ingresos, clientes, churn, NPS, red, anomalías o Graph Intelligence de Quetzal."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "scope": {
                "type": "string",
                "enum": ["executive", "revenue", "customers", "network", "retention", "graph"],
                "description": "Dominio operativo requerido",
            },
            "customer_id": {
                "type": "string",
                "description": "Identificador opcional del cliente para consultar sus casos de retención",
                "pattern": "^[A-Za-z0-9_-]{1,128}$",
            },
        },
        "required": ["scope"],
    },
}

_ONTOBRICKS_SEMANTIC_TOOL = {
    "type": "function",
    "name": "ontobricks_semantic_query",
    "description": (
        "Consulta el grafo semántico gobernado de Quetzal mediante OntoBricks MCP. "
        "Usa esta función para relaciones entre clientes, clases ontológicas, planes, SLA, "
        "recomendaciones, productos y contexto conectado. Nunca generes GraphQL."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "intent": {
                "type": "string",
                "enum": [
                    "CUSTOMER_RELATIONSHIPS", "CLASS_MEMBERS",
                    "CUSTOMER_CONTEXT", "PLAN_ELIGIBILITY", "SLA_CONTEXT",
                    "RECOMMENDATION_CONTEXT",
                ],
            },
            "class_name": {
                "type": "string",
                "enum": [
                    "Customer", "QualifiedContact", "RelationshipGroup", "Country",
                    "Plan", "Product", "Ticket", "SLA", "Recommendation",
                ],
            },
            "customer_id": {"type": "string", "pattern": "^[A-Za-z0-9_-]{1,128}$"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 50},
        },
        "required": ["intent"],
    },
}

_INTERNAL_CHAT_TOOLS = [_TELECOM_SNAPSHOT_TOOL, _ONTOBRICKS_SEMANTIC_TOOL]
_CHAT_TOOLS = [*_INTERNAL_CHAT_TOOLS, _WEB_SEARCH_TOOL]


def _execute_search(query: str) -> str:
    """Execute web search via DDGS, fallback to DDG API. Returns JSON string."""
    if _HAS_DDGS:
        for backend in ("auto", "lite", "html"):
            try:
                results = list(DDGS().text(query, max_results=5, backend=backend))
                if results:
                    log.info(f"Search OK via DDGS/{backend}: {len(results)} results")
                    return _json.dumps(
                        [{"title": r["title"], "url": r["href"], "snippet": r["body"]} for r in results],
                        ensure_ascii=False,
                    )
            except Exception as e:  # noqa: BLE001 - DDGS backends expose heterogeneous transport errors
                log.warning(f"DDGS/{backend} failed: {e}")
    try:
        resp = http_requests.get(
            "https://api.duckduckgo.com/",
            params={"q": query, "format": "json", "no_html": "1", "skip_disambig": "1"},
            headers={"User-Agent": "QuetzalCC/1.0"}, timeout=8,
        )
        if resp.status_code == 200:
            data = resp.json()
            items = []
            if data.get("AbstractText"):
                items.append({"title": data.get("AbstractSource", ""), "snippet": data["AbstractText"], "url": data.get("AbstractURL", "")})
            for t in data.get("RelatedTopics", [])[:5]:
                if isinstance(t, dict) and t.get("Text"):
                    items.append({"title": "", "snippet": t["Text"][:250], "url": t.get("FirstURL", "")})
            if items:
                return _json.dumps(items, ensure_ascii=False)
    except (http_requests.RequestException, ValueError) as e:
        log.warning(f"DDG API failed: {e}")
    return '[]'


def _execute_telecom_snapshot(scope: str, customer_id: str | None = None) -> str:
    """Return allowlisted internal data; the model never receives arbitrary SQL access."""
    access = _authorized_access()
    if scope == "revenue":
        payload = {
            "scope": scope,
            "period": "trailing_12_months",
            "by_country": revenue_by_country(),
            "by_service": service_mix(),
        }
    elif scope == "customers":
        kpis = get_kpis()
        payload = {
            "scope": scope,
            "kpis": kpis.get("subscribers", {}),
            "satisfaction": kpis.get("satisfaction", {}),
            "churn_risk": churn_risk(),
            "arpu_by_segment": arpu_segment(),
        }
    elif scope == "network":
        payload = {
            "scope": scope,
            "kpis": get_kpis().get("network", {}),
            "by_country": network_detail(),
            "recent_anomalies": network_anomalies(),
            "freshness": data_freshness(),
            "important_semantics": (
                "health_score is the percentage of measurements without alerts; "
                "it is not service availability or contractual uptime"
            ),
        }
    elif scope == "graph":
        if access.countries:
            return _json.dumps({
                "scope": scope,
                "available": False,
                "reason": "Graph Intelligence global no está disponible para perfiles con alcance territorial.",
                "authorized_countries": list(access.countries),
            }, ensure_ascii=False)
        try:
            run = run_sql(
                "SELECT * FROM ops_graph_run_log WHERE status = 'SUCCEEDED' ORDER BY completed_at DESC LIMIT 1",
                cache_ttl=15,
            )
            portfolio = run_sql(
                """SELECT count(*) AS customers,
                          count(DISTINCT community_id) AS communities,
                          round(avg(influence_score), 1) AS avg_influence_score,
                          round(avg(contagion_risk_score), 1) AS avg_contagion_risk_score,
                          round(avg(international_call_pct), 1) AS international_call_pct,
                          round(sum(influenced_revenue_usd), 2) AS influenced_revenue_usd
                   FROM gold_customer_graph_features""",
                cache_ttl=15,
            )
            top_communities = run_sql(
                """SELECT community_id, countries, customer_count,
                          avg_graph_churn_probability, high_risk_customers,
                          avg_influence_score, avg_contagion_risk_score,
                          influenced_revenue_usd, international_call_pct
                   FROM gold_graph_community_summary
                   ORDER BY influenced_revenue_usd DESC LIMIT 10""",
                cache_ttl=15,
            )
            payload = {
                "scope": scope,
                "available": bool(run),
                "latest_run": run[0] if run else None,
                "portfolio": portfolio[0] if portfolio else {},
                "top_communities": top_communities,
                "methodology": (
                    "v3 target: weighted PageRank for reach, weighted Personalized PageRank for risk diffusion, "
                    "weighted neighbour exposure and weighted Label Propagation; OntoBricks supplies governed semantics"
                ),
                "important_semantics": (
                    "The individual churn probability is never replaced by graph analytics. Reach, exposure, diffusion "
                    "and retention priority are 0-100 operational scores, not probabilities and not causal evidence."
                ),
            }
        except SqlExecutionError:
            payload = {"scope": scope, "available": False, "reason": "Graph Intelligence has not completed its first manual run."}
    elif scope == "retention":
        try:
            if customer_id:
                if len(customer_id) > 128 or not all(char.isalnum() or char in "-_" for char in customer_id):
                    payload = {"scope": scope, "available": False, "reason": "customer_id inválido"}
                else:
                    countries = run_sql(
                        "SELECT pais_codigo FROM ops_customer_360 WHERE cliente_id = :customer_id",
                        parameters={"customer_id": customer_id},
                        cache_ttl=15,
                    )
                    if not countries:
                        payload = {"scope": scope, "available": False, "reason": "Cliente no encontrado"}
                    else:
                        assert_country_access(access, countries[0].get("pais_codigo"))
                        payload = {
                            "scope": scope,
                            "available": True,
                            "customer_id": customer_id,
                            "cases": retention_case_store.list_for_customer(customer_id),
                            "access": "READ_ONLY",
                            "source": "lakebase.quetzal_app.retention_cases",
                        }
            else:
                payload = {
                    "scope": scope,
                    "available": True,
                    "country_scope": list(access.countries) or ["ALL"],
                    "cases": retention_case_store.list_for_scope(tuple(access.countries), limit=25),
                    "access": "READ_ONLY",
                    "source": "lakebase.quetzal_app.retention_cases",
                }
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001 - SDK, OAuth and Postgres expose heterogeneous failures
            payload = {
                "scope": scope,
                "available": False,
                "status": "DEGRADED",
                "reason": f"Lakebase retention workflow unavailable: {type(exc).__name__}",
                "access": "READ_ONLY",
            }
    else:
        payload = {
            "scope": "executive",
            "kpis": get_kpis(),
            "churn_risk": churn_risk(),
            "recent_anomalies": network_anomalies(),
            "freshness": data_freshness(),
        }
    return _json.dumps(payload, ensure_ascii=False, default=str)


def _execute_ontobricks_semantic(
    intent: str,
    class_name: str | None = None,
    customer_id: str | None = None,
    limit: int = 20,
) -> str:
    """Execute a bounded MCP intent under the authenticated territorial scope."""
    access = _authorized_access()
    allowed_intents = {
        "CUSTOMER_RELATIONSHIPS", "CLASS_MEMBERS",
        "CUSTOMER_CONTEXT", "PLAN_ELIGIBILITY", "SLA_CONTEXT",
        "RECOMMENDATION_CONTEXT",
    }
    if intent not in allowed_intents:
        intent = "CUSTOMER_CONTEXT"
    try:
        if access.countries:
            if not customer_id:
                raise OntoBricksError(
                    "Indica un cliente para consultar OntoBricks dentro de tu alcance territorial."
                )
            rows = run_sql(
                "SELECT pais_codigo FROM ops_customer_360 WHERE cliente_id = :customer_id",
                parameters={"customer_id": customer_id}, cache_ttl=15,
            )
            if not rows:
                raise OntoBricksError("El cliente no existe dentro del dominio gobernado.")
            assert_country_access(access, rows[0].get("pais_codigo"))
        payload = ontobricks_mcp.query(
            intent=intent, class_name=class_name, customer_id=customer_id,
            limit=max(1, min(int(limit), 50)), countries=tuple(access.countries),
        )
    except (OntoBricksError, ValueError, TypeError) as exc:
        payload = {
            "available": False,
            "source_type": "ONTOBRICKS_MCP",
            "intent": intent,
            "territorial_scope": list(access.countries) or ["ALL"],
            "domain": settings.ontobricks_domain,
            "version": settings.ontobricks_version,
            "reason": str(exc),
        }
    return _json.dumps(payload, ensure_ascii=False, default=str)


# ---------------------------------------------------------------------------
# Environment-backed product resources
# ---------------------------------------------------------------------------
HOST = settings.host
AI_MODEL = settings.ai_model
AI_URL = settings.ai_url
GENIE = settings.genie_spaces


def _headers() -> dict[str, str]:
    return auth_headers()


def _authorized_access():
    """Return the governed request scope for non-router API handlers."""
    return require_any_role(resolve_access(None, run_sql))


def _scope_filter(column: str) -> tuple[str, dict[str, str]]:
    return country_predicate(_authorized_access(), column)


def _run_scoped_sql(
    query_template: str,
    *,
    country_column: str = "pais_codigo",
    parameters: dict[str, Any] | None = None,
    cache_ttl: int | None = None,
) -> list[dict[str, Any]]:
    scope, scope_parameters = _scope_filter(country_column)
    query = query_template.replace("__AUTHORIZED_SCOPE__", scope)
    return run_sql(
        query,
        parameters={**scope_parameters, **(parameters or {})},
        cache_ttl=cache_ttl,
    )


def _require_unrestricted_upstream(service: str):
    access = _authorized_access()
    require_unrestricted_service(access, service)
    return access


def _assert_genie_conversation_owner(conversation_id: str, access) -> None:
    if "ADMIN" in (access.roles or ()):
        return
    rows = run_sql(
        """SELECT actor FROM ops_audit_log
           WHERE resource_type = 'genie_conversation' AND resource_id = :conversation_id
           ORDER BY event_at ASC LIMIT 1""",
        parameters={"conversation_id": conversation_id},
        cache_ttl=0,
    )
    if not rows or str(rows[0].get("actor") or "").casefold() != access.actor.casefold():
        raise HTTPException(403, "La conversación de Genie no pertenece al usuario autenticado.")


def _record_genie_conversation_owner(conversation_id: str, access, space_key: str) -> None:
    if "ADMIN" in (access.roles or ()):
        return
    execute_sql(
        """INSERT INTO ops_audit_log
           VALUES (:event_id, 'GENIE_CONVERSATION_STARTED', 'genie_conversation',
                   :conversation_id, :actor, current_timestamp(), :detail_json)""",
        parameters={
            "event_id": uuid4().hex,
            "conversation_id": conversation_id,
            "actor": access.actor,
            "detail_json": _json.dumps({"space": space_key}, ensure_ascii=False),
        },
    )


def _raise_upstream(response: http_requests.Response, service: str) -> None:
    if response.status_code < 400:
        return
    log.error("%s upstream failure status=%s body=%s", service, response.status_code, response.text[:1000])
    if response.status_code in (401, 403):
        detail = f"{service} no está autorizado para esta operación."
    elif response.status_code == 429:
        detail = f"{service} alcanzó su límite temporal de solicitudes."
    else:
        detail = f"{service} no pudo completar la solicitud."
    raise HTTPException(status_code=502, detail=detail)


def _validate_resource_id(value: str, label: str) -> str:
    if not _re.fullmatch(r"[A-Za-z0-9_-]{1,128}", value):
        raise HTTPException(status_code=400, detail=f"{label} inválido.")
    return value

# ---------------------------------------------------------------------------
# FastAPI
# ---------------------------------------------------------------------------
docs_enabled = os.getenv("QUETZAL_ENABLE_DOCS", "false").lower() == "true"
app = FastAPI(
    title="Quetzal Command Center API",
    version="3.0.0",
    description="Governed operational intelligence for Quetzal Telecom.",
    docs_url="/docs" if docs_enabled else None,
    redoc_url=None,
)
app.include_router(operations_router)


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or uuid4().hex
    request.state.request_id = request_id
    started = time.monotonic()
    access_token = None
    try:
        if request.url.path.startswith("/api/") and request.url.path != "/api/health":
            identity = identify_request(request)
            access_token = bind_access(identity)
        response = await call_next(request)
    except HTTPException as exc:
        response = JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})
    except Exception:
        log.exception("Unhandled request error request_id=%s path=%s", request_id, request.url.path)
        raise
    finally:
        if access_token is not None:
            reset_access(access_token)
    duration_ms = round((time.monotonic() - started) * 1000)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    log.info("request_id=%s method=%s path=%s status=%s duration_ms=%s", request_id, request.method, request.url.path, response.status_code, duration_ms)
    return response


@app.exception_handler(SqlExecutionTimeout)
async def sql_timeout_handler(request: Request, exc: SqlExecutionTimeout):
    log.error("SQL timeout request_id=%s: %s", getattr(request.state, "request_id", "-"), exc)
    return JSONResponse(status_code=504, content={"detail": "La plataforma de datos excedió el tiempo de respuesta."})


@app.exception_handler(SqlExecutionError)
async def sql_error_handler(request: Request, exc: SqlExecutionError):
    log.error("SQL failure request_id=%s: %s", getattr(request.state, "request_id", "-"), exc)
    return JSONResponse(status_code=502, content={"detail": "No fue posible consultar la plataforma de datos."})


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    errors = [
        {"location": list(error["loc"]), "type": error["type"], "message": error["msg"]}
        for error in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content={"detail": "Solicitud inválida.", "errors": errors},
    )


@app.exception_handler(http_requests.exceptions.Timeout)
async def upstream_timeout_handler(request: Request, exc: http_requests.exceptions.Timeout):
    log.error("Upstream timeout request_id=%s: %s", getattr(request.state, "request_id", "-"), exc)
    return JSONResponse(status_code=504, content={"detail": "Un servicio dependiente excedió el tiempo de respuesta."})


@app.exception_handler(http_requests.exceptions.RequestException)
async def upstream_connection_handler(request: Request, exc: http_requests.exceptions.RequestException):
    log.error("Upstream request failure request_id=%s: %s", getattr(request.state, "request_id", "-"), exc)
    return JSONResponse(status_code=502, content={"detail": "No fue posible conectar con un servicio dependiente."})


@app.get("/api/health")
def health():
    return {"status": "ok", "service": "quetzal-command-center", "version": app.version}


@app.get("/api/health/ready")
def readiness():
    _authorized_access()
    run_sql("SELECT 1 AS ready", cache_ttl=0)
    return {"status": "ready", "dependency": "databricks_sql"}

# ---- Config endpoint (for frontend) ----
@app.get("/api/config")
def get_config():
    access = _authorized_access()
    unrestricted = not access.countries
    return {
        "dashboard_url": settings.dashboard_url if unrestricted else "",
        "genie_spaces": (
            {k: {"name": v["name"], "icon": v["icon"]} for k, v in GENIE.items()}
            if unrestricted else {}
        ),
        "countries": list(access.countries or COUNTRIES),
        "scope": {
            "countries": list(access.countries or ("ALL",)),
            "upstream_identity": "APP_SERVICE_PRINCIPAL",
            "territorial_upstreams_enabled": unrestricted,
        },
    }


@app.get("/api/operations/freshness")
def data_freshness():
    scope, parameters = _scope_filter("pais_codigo")
    rows = run_sql(f"""
        WITH sources AS (
          SELECT 'network' AS domain, 'hourly' AS cadence, CAST(MAX(hora) AS TIMESTAMP) AS as_of
          FROM gold_network_health WHERE {scope}
          UNION ALL
          SELECT 'revenue', 'monthly', CAST(MAX(mes) AS TIMESTAMP)
          FROM gold_revenue_by_country_service WHERE mes < DATE_TRUNC('MONTH', CURRENT_DATE()) AND {scope}
          UNION ALL
          SELECT 'subscribers', 'monthly', CAST(MAX(mes) AS TIMESTAMP)
          FROM gold_subscriber_metrics WHERE mes < DATE_TRUNC('MONTH', CURRENT_DATE()) AND {scope}
          UNION ALL
          SELECT 'billing', 'monthly', CAST(MAX(mes) AS TIMESTAMP)
          FROM gold_billing_health WHERE mes < DATE_TRUNC('MONTH', CURRENT_DATE()) AND {scope}
          UNION ALL
          SELECT 'satisfaction', 'monthly', CAST(MAX(mes) AS TIMESTAMP)
          FROM gold_customer_satisfaction WHERE mes < DATE_TRUNC('MONTH', CURRENT_DATE()) AND {scope}
          UNION ALL
          SELECT 'churn_model', 'daily', CAST(MAX(scored_at) AS TIMESTAMP)
          FROM gold_churn_predictions WHERE {scope}
          UNION ALL
          SELECT 'clv_model', 'daily', CAST(MAX(scored_at) AS TIMESTAMP)
          FROM gold_clv_segments WHERE {scope}
        )
        SELECT domain, cadence, as_of,
               ROUND((UNIX_TIMESTAMP(CURRENT_TIMESTAMP()) - UNIX_TIMESTAMP(as_of)) / 3600.0, 1) AS lag_hours,
               CASE
                 WHEN cadence = 'hourly' AND as_of >= CURRENT_TIMESTAMP() - INTERVAL 2 HOURS THEN 'fresh'
                 WHEN cadence = 'daily' AND as_of >= CURRENT_TIMESTAMP() - INTERVAL 48 HOURS THEN 'fresh'
                 WHEN cadence = 'monthly' AND as_of >= ADD_MONTHS(DATE_TRUNC('MONTH', CURRENT_DATE()), -1) THEN 'fresh'
                 ELSE 'stale'
               END AS status
        FROM sources
        ORDER BY domain
    """, parameters=parameters)
    return {"sources": rows, "policy": {"hourly_hours": 2, "daily_hours": 48, "monthly": "last_closed_month"}}

# ---- KPIs ----
@app.get("/api/kpis")
def get_kpis():
    scope, parameters = _scope_filter("pais_codigo")
    rows = run_sql(f"""
        WITH revenue_window AS (
          SELECT * FROM gold_revenue_by_country_service
          WHERE mes >= ADD_MONTHS((SELECT MAX(mes) FROM gold_revenue_by_country_service WHERE mes < DATE_TRUNC('MONTH', CURRENT_DATE())), -11)
            AND mes < DATE_TRUNC('MONTH', CURRENT_DATE())
            AND {scope}
        ), satisfaction_latest AS (
          SELECT * FROM gold_customer_satisfaction
          WHERE mes = (SELECT MAX(mes) FROM gold_customer_satisfaction WHERE mes < DATE_TRUNC('MONTH', CURRENT_DATE()))
            AND {scope}
        ), network_latest AS (
          SELECT * FROM gold_network_health
          WHERE hora = (SELECT MAX(hora) FROM gold_network_health)
            AND {scope}
        ), subscribers_latest AS (
          SELECT * FROM gold_subscriber_metrics
          WHERE mes = (SELECT MAX(mes) FROM gold_subscriber_metrics WHERE mes < DATE_TRUNC('MONTH', CURRENT_DATE()))
            AND {scope}
        )
        SELECT
          ROUND((SELECT SUM(ingresos_totales_usd) FROM revenue_window),0) AS total_revenue,
          ROUND((SELECT SUM(ingresos_totales_usd) / NULLIF(SUM(num_facturas),0) FROM revenue_window),2) AS avg_ticket,
          ROUND((SELECT SUM(ingresos_cobrados_usd) FROM revenue_window),0) AS collected,
          (SELECT MIN(DATE(mes)) FROM revenue_window) AS revenue_period_start,
          (SELECT MAX(DATE(mes)) FROM revenue_window) AS revenue_period_end,
          ROUND((SELECT SUM(nps_index * total_encuestas) / NULLIF(SUM(total_encuestas),0) FROM satisfaction_latest),1) AS nps,
          ROUND((SELECT SUM(avg_csat * total_evaluaciones_csat) / NULLIF(SUM(total_evaluaciones_csat),0) FROM satisfaction_latest),2) AS csat,
          (SELECT SUM(total_encuestas) FROM satisfaction_latest) AS surveys,
          (SELECT MAX(DATE(mes)) FROM satisfaction_latest) AS satisfaction_as_of,
          ROUND((SELECT SUM(uptime_pct * total_mediciones) / NULLIF(SUM(total_mediciones),0) FROM network_latest),2) AS network_health,
          (SELECT SUM(torres_en_alerta) FROM network_latest) AS towers_alert,
          ROUND((SELECT SUM(avg_latencia_ms * total_mediciones) / NULLIF(SUM(total_mediciones),0) FROM network_latest),1) AS latency,
          (SELECT MAX(hora) FROM network_latest) AS network_as_of,
          (SELECT SUM(clientes_activos) FROM subscribers_latest) AS active_subscribers,
          ROUND((SELECT SUM(tasa_churn_pct * clientes_activos) / NULLIF(SUM(clientes_activos),0) FROM subscribers_latest),2) AS churn_rate,
          (SELECT MAX(DATE(mes)) FROM subscribers_latest) AS subscribers_as_of
    """, parameters=parameters)
    row = rows[0] if rows else {}
    return {
        "revenue": {k: row.get(k) for k in ("total_revenue", "avg_ticket", "collected", "revenue_period_start", "revenue_period_end")},
        "satisfaction": {k: row.get(k) for k in ("nps", "csat", "surveys", "satisfaction_as_of")},
        "network": {
            "uptime": row.get("network_health"),  # compatibility alias; see metric_semantics
            "health_score": row.get("network_health"),
            "towers_alert": row.get("towers_alert"),
            "latency": row.get("latency"),
            "as_of": row.get("network_as_of"),
            "metric_semantics": "healthy_measurements_pct",
        },
        "subscribers": {k: row.get(k) for k in ("active_subscribers", "churn_rate", "subscribers_as_of")},
    }

# ---- Revenue by country ----
@app.get("/api/charts/revenue-by-country")
def revenue_by_country():
    rows = _run_scoped_sql("""
        SELECT pais_codigo, ROUND(SUM(ingresos_totales_usd),0) AS ingresos
        FROM gold_revenue_by_country_service
        WHERE mes >= ADD_MONTHS((SELECT MAX(mes) FROM gold_revenue_by_country_service WHERE mes < DATE_TRUNC('MONTH', CURRENT_DATE())), -11)
          AND mes < DATE_TRUNC('MONTH', CURRENT_DATE())
          AND __AUTHORIZED_SCOPE__
        GROUP BY pais_codigo ORDER BY ingresos DESC""")
    return rows

# ---- Revenue trend ----
@app.get("/api/charts/revenue-trend")
def revenue_trend():
    rows = _run_scoped_sql("""
        SELECT DATE(mes) AS mes, vertical,
               ROUND(SUM(ingresos_totales_usd),0) AS ingresos
        FROM gold_revenue_by_country_service
        WHERE mes >= ADD_MONTHS((SELECT MAX(mes) FROM gold_revenue_by_country_service WHERE mes < DATE_TRUNC('MONTH', CURRENT_DATE())), -11)
          AND mes < DATE_TRUNC('MONTH', CURRENT_DATE())
          AND __AUTHORIZED_SCOPE__
        GROUP BY DATE(mes), vertical ORDER BY mes""")
    return rows

# ---- Service mix ----
@app.get("/api/charts/service-mix")
def service_mix():
    rows = _run_scoped_sql("""
        SELECT vertical, ROUND(SUM(ingresos_totales_usd),0) AS ingresos
        FROM gold_revenue_by_country_service
        WHERE mes >= ADD_MONTHS((SELECT MAX(mes) FROM gold_revenue_by_country_service WHERE mes < DATE_TRUNC('MONTH', CURRENT_DATE())), -11)
          AND mes < DATE_TRUNC('MONTH', CURRENT_DATE())
          AND __AUTHORIZED_SCOPE__
        GROUP BY vertical ORDER BY ingresos DESC""")
    return rows

# ---- Subscribers trend ----
@app.get("/api/charts/subscribers")
def subscribers_trend():
    rows = _run_scoped_sql("""
        SELECT DATE(mes) AS mes, segmento_id,
               SUM(clientes_activos) AS clientes_activos,
               SUM(suscripciones_activas) AS suscripciones_activas,
               ROUND(AVG(tasa_churn_pct),2) AS churn_rate
        FROM gold_subscriber_metrics
        WHERE mes BETWEEN ADD_MONTHS(
            (SELECT MAX(mes) FROM gold_subscriber_metrics WHERE mes < DATE_TRUNC('MONTH', CURRENT_DATE())), -11
          ) AND (SELECT MAX(mes) FROM gold_subscriber_metrics WHERE mes < DATE_TRUNC('MONTH', CURRENT_DATE()))
          AND __AUTHORIZED_SCOPE__
        GROUP BY DATE(mes), segmento_id ORDER BY mes""")
    return rows

# ---- Network status ----
@app.get("/api/network/status")
def network_status():
    rows = _run_scoped_sql("""
        SELECT pais_codigo,
               ROUND(AVG(uptime_pct),2) AS uptime_pct,
               ROUND(AVG(uptime_pct),2) AS health_pct,
               CASE
                 WHEN AVG(uptime_pct) >= 42 THEN 'Óptimo'
                 WHEN AVG(uptime_pct) >= 38 THEN 'Normal'
                 ELSE 'Degradado'
               END AS status,
               MAX(hora) AS as_of,
               'healthy_measurements_pct' AS metric_semantics
        FROM gold_network_health
        WHERE hora = (SELECT MAX(hora) FROM gold_network_health)
          AND __AUTHORIZED_SCOPE__
        GROUP BY pais_codigo
        ORDER BY uptime_pct DESC""")
    return rows

# ---- ML: churn risk summary ----
@app.get("/api/ml/churn-risk")
def churn_risk():
    rows = _run_scoped_sql("""
        SELECT risk_tier AS risk_category,
               COUNT(*) AS clientes,
               ROUND(AVG(churn_probability),3) AS probabilidad_promedio
        FROM gold_churn_predictions
        WHERE scored_at = (SELECT MAX(scored_at) FROM gold_churn_predictions)
          AND __AUTHORIZED_SCOPE__
        GROUP BY risk_tier
        ORDER BY clientes DESC""")
    return rows

# ---- ML: CLV segments ----
@app.get("/api/ml/clv")
def clv_segments():
    rows = _run_scoped_sql("""
        SELECT segment_name,
               COUNT(*) AS clientes,
               ROUND(AVG(gasto_mensual_total),2) AS gasto_promedio_usd,
               ROUND(AVG(revenue_lifetime_est),0) AS clv_promedio_usd
        FROM gold_clv_segments
        WHERE scored_at = (SELECT MAX(scored_at) FROM gold_clv_segments)
          AND __AUTHORIZED_SCOPE__
        GROUP BY segment_name
        ORDER BY clv_promedio_usd DESC""")
    return rows

# ---- ML: network anomalies ----
@app.get("/api/ml/anomalies")
def network_anomalies():
    rows = _run_scoped_sql("""
        SELECT pais_codigo,
               ciudad,
               torre_id,
               ROUND(latencia_ms,1) AS latencia_ms,
               ROUND(throughput_mbps,1) AS throughput_mbps,
               ROUND(anomaly_score,3) AS anomaly_score,
               COALESCE(anomaly_severity, 'Media') AS anomaly_severity
        FROM gold_network_anomalies
        WHERE is_anomaly = 1
          AND __AUTHORIZED_SCOPE__
          AND timestamp >= (SELECT MAX(timestamp) - INTERVAL 24 HOURS FROM gold_network_anomalies)
        ORDER BY anomaly_score DESC
        LIMIT 8""")
    return rows

# ---- ARPU by segment ----
@app.get("/api/charts/arpu-segment")
def arpu_segment():
    return _run_scoped_sql("""
        SELECT segmento_id,
               ROUND(AVG(gasto_mensual_total),2) AS arpu,
               COUNT(*) AS clientes
        FROM gold_churn_predictions
        WHERE scored_at = (SELECT MAX(scored_at) FROM gold_churn_predictions)
          AND __AUTHORIZED_SCOPE__
        GROUP BY segmento_id
        ORDER BY arpu DESC""")

# ---- Billing health overview ----
@app.get("/api/charts/billing-health")
def billing_health():
    return _run_scoped_sql("""
        SELECT pais_codigo,
               ROUND(AVG(tasa_cobro_pct),1) AS tasa_cobro,
               ROUND(AVG(pct_vencida),1) AS morosidad,
               ROUND(SUM(cartera_vencida_usd),0) AS cartera_vencida
        FROM gold_billing_health
        WHERE mes = (SELECT MAX(mes) FROM gold_billing_health WHERE mes < DATE_TRUNC('MONTH', CURRENT_DATE()))
          AND __AUTHORIZED_SCOPE__
        GROUP BY pais_codigo
        ORDER BY tasa_cobro DESC""")

# ---- Satisfaction by country ----
@app.get("/api/charts/satisfaction")
def satisfaction_by_country():
    return _run_scoped_sql("""
        SELECT pais_codigo,
               ROUND(AVG(nps_index),1) AS nps,
               ROUND(AVG(avg_csat),2) AS csat,
               ROUND(AVG(csat_top2_pct),1) AS csat_top2
        FROM gold_customer_satisfaction
        WHERE mes = (SELECT MAX(mes) FROM gold_customer_satisfaction WHERE mes < DATE_TRUNC('MONTH', CURRENT_DATE()))
          AND __AUTHORIZED_SCOPE__
        GROUP BY pais_codigo
        ORDER BY nps DESC""")

# ---- Churn risk buckets (summary table) ----
@app.get("/api/charts/churn-buckets")
def churn_buckets():
    return _run_scoped_sql("""
        SELECT risk_tier AS riesgo_bucket,
               COUNT(*) AS clientes,
               ROUND(AVG(churn_probability),3) AS avg_score,
               ROUND(AVG(gasto_mensual_total),2) AS gasto_prom
        FROM gold_churn_predictions
        WHERE scored_at = (SELECT MAX(scored_at) FROM gold_churn_predictions)
          AND __AUTHORIZED_SCOPE__
        GROUP BY risk_tier
        ORDER BY avg_score DESC""")

# ---- Network detailed per country ----
@app.get("/api/charts/network-detail")
def network_detail():
    return _run_scoped_sql("""
        SELECT pais_codigo,
               ROUND(AVG(uptime_pct),2) AS uptime,
               ROUND(AVG(avg_latencia_ms),1) AS latencia,
               ROUND(AVG(avg_throughput_mbps),1) AS throughput,
               ROUND(AVG(avg_packet_loss_pct),2) AS packet_loss,
               SUM(torres_en_alerta) AS alertas,
               MAX(hora) AS as_of,
               'healthy_measurements_pct' AS metric_semantics
        FROM gold_network_health
        WHERE hora = (SELECT MAX(hora) FROM gold_network_health)
          AND __AUTHORIZED_SCOPE__
        GROUP BY pais_codigo
        ORDER BY uptime DESC""")

# ---- Reports (filtered) ----
@app.post("/api/reports")
def get_reports(payload: ReportRequest):
    access = _authorized_access()
    country = payload.country
    if country != "ALL":
        assert_country_access(access, country)
        report_scope = "pais_codigo = :report_country"
        parameters = {"report_country": country}
    else:
        report_scope, parameters = country_predicate(access, "pais_codigo")
    queries = {
        "revenue": f"""
        SELECT DATE(mes) AS mes, vertical,
               ROUND(SUM(ingresos_totales_usd),0) AS ingresos
        FROM gold_revenue_by_country_service
        WHERE {report_scope}
        GROUP BY DATE(mes), vertical ORDER BY mes""",
        "billing": f"""
        SELECT DATE(mes) AS mes,
               ROUND(AVG(pct_pagada),2) AS pct_pagada,
               ROUND(AVG(pct_vencida),2) AS pct_vencida,
               ROUND(SUM(facturacion_total_usd),0) AS facturacion
        FROM gold_billing_health
        WHERE {report_scope}
        GROUP BY DATE(mes) ORDER BY mes""",
        "nps": f"""
        SELECT DATE(mes) AS mes,
               ROUND(AVG(nps_index),1) AS nps,
               ROUND(AVG(avg_csat),2) AS csat
        FROM gold_customer_satisfaction
        WHERE {report_scope}
        GROUP BY DATE(mes) ORDER BY mes""",
        "churn": f"""
        SELECT risk_tier AS risk_category, COUNT(*) AS cnt,
               ROUND(AVG(churn_probability),3) AS avg_prob
        FROM gold_churn_predictions
        WHERE {report_scope}
          AND scored_at = (SELECT MAX(scored_at) FROM gold_churn_predictions)
        GROUP BY risk_tier""",
        "network": f"""
        SELECT DATE(hora) AS dia,
               ROUND(AVG(avg_latencia_ms),1) AS latencia,
               ROUND(AVG(uptime_pct),2) AS uptime,
               ROUND(AVG(uptime_pct),2) AS health_pct
        FROM gold_network_health
        WHERE {report_scope}
        GROUP BY DATE(hora) ORDER BY dia""",
    }
    futures = {
        name: submit_with_context(sql_fanout, run_sql, query, parameters=parameters)
        for name, query in queries.items()
    }
    result = {name: future.result() for name, future in futures.items()}
    result["metadata"] = {
        "country": country,
        "effective_countries": [country] if country != "ALL" else list(access.countries or ("ALL",)),
        "network_metric_semantics": "healthy_measurements_pct",
    }
    return result

# ---- Genie ----
@app.post("/api/genie/query")
def genie_query(payload: GenieQueryRequest):
    access = _require_unrestricted_upstream("Genie")
    trace_id = f"genie-{uuid4().hex[:12]}"
    space_key = payload.space
    question = payload.question
    space = GENIE.get(space_key)
    if not space:
        raise HTTPException(400, "Espacio inválido")

    log.info(
        "genie_start trace_id=%s space=%s deep=%s question=%r",
        trace_id, space_key, payload.deep, question[:240],
    )
    conversation_id = (
        _validate_resource_id(payload.conversation_id, "conversation_id")
        if payload.conversation_id else None
    )
    if conversation_id:
        _assert_genie_conversation_owner(conversation_id, access)
    if payload.deep:
        # Agent mode: SSE endpoint, returns full result directly
        result = _genie_agent_call(space, question, conversation_id)
        if not conversation_id and result.get("conversation_id"):
            _record_genie_conversation_owner(result["conversation_id"], access, space_key)
        result["trace_id"] = trace_id
        return result

    # Chat mode: continue the active conversation or start a new one.
    endpoint = (
        f"{HOST}/api/2.0/genie/spaces/{space['id']}/conversations/"
        f"{conversation_id}/messages"
        if conversation_id else
        f"{HOST}/api/2.0/genie/spaces/{space['id']}/start-conversation"
    )
    r = http_requests.post(
        endpoint,
        headers=_headers(), json={"content": question}, timeout=(5, 30),
    )
    _raise_upstream(r, "Genie")
    d = r.json()
    conversation_id = conversation_id or d.get("conversation_id") or (d.get("conversation") or {}).get("id")
    message_id = d.get("message_id") or d.get("id") or (d.get("message") or {}).get("id")
    if not conversation_id or not message_id:
        log.error("genie_invalid_start trace_id=%s response_keys=%s", trace_id, sorted(d))
        raise HTTPException(502, "Genie no devolvió identificadores de seguimiento.")
    if payload.conversation_id is None:
        _record_genie_conversation_owner(conversation_id, access, space_key)
    log.info(
        "genie_accepted trace_id=%s space=%s conversation_id=%s message_id=%s",
        trace_id, space_key, conversation_id, message_id,
    )
    return {
        "trace_id": trace_id,
        "conversation_id": conversation_id,
        "message_id": message_id,
        "space_key": space_key,
        "space_name": space["name"],
        "status": "SUBMITTED",
        "continued": payload.conversation_id is not None,
    }


def _parse_md_table(md_text: str):
    """Parse a markdown table into structured {title, columns, rows}."""
    lines = md_text.strip().split("\n")
    title = ""
    header_idx = -1
    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith("**") and s.endswith("**"):
            title = s.strip("* ")
        elif "|" in s and header_idx == -1 and s.replace("|", "").replace("-", "").replace(" ", "") != "":
            header_idx = i
            break
    if header_idx == -1:
        return None
    cols = [c.strip() for c in lines[header_idx].split("|") if c.strip()]
    if not cols:
        return None
    data_start = header_idx + 2  # skip separator
    rows = []
    for i in range(data_start, len(lines)):
        ln = lines[i].strip()
        if not ln or "|" not in ln:
            break
        vals = [v.strip() for v in ln.split("|") if v.strip() != ""]
        if len(vals) >= len(cols):
            rows.append(vals[:len(cols)])
    if not rows:
        return None
    # Detect numeric columns
    col_meta = []
    for ci in range(len(cols)):
        samples = [rows[ri][ci] for ri in range(min(5, len(rows)))]
        is_num = all(_is_num(v) for v in samples)
        col_meta.append({"name": cols[ci], "type": "DOUBLE" if is_num else "STRING"})
    return {"title": title, "columns": col_meta, "rows": rows}


def _is_num(s: str) -> bool:
    try:
        float(s)
        return True
    except (TypeError, ValueError):
        return False


def _strip_md_tables(text: str) -> str:
    """Remove markdown tables from text to avoid duplication with rendered charts."""
    return _re.sub(
        r'(\*\*[^*\n]+\*\*\s*\n+)?'
        r'\|[^\n]+\|\s*\n'
        r'\|[\s:|-]+\|\s*\n'
        r'(\|[^\n]+\|\s*\n)+',
        '', text
    )


def _genie_agent_call(space: dict, question: str, conversation_id: str | None = None) -> dict:
    """Call Genie Agent mode API (SSE), collect events, return structured result."""
    payload = {
        "input": [{
            "type": "message", "role": "user",
            "content": [{"type": "input_text", "text": question}],
        }]
    }
    if conversation_id:
        payload["conversation_id"] = conversation_id
    r = http_requests.post(
        f"{HOST}/api/2.0/genie/agents/{space['id']}/responses",
        headers=_headers(), json=payload, timeout=(5, 300),
    )
    _raise_upstream(r, "Genie Agent")

    # Decode raw bytes as UTF-8 (Content-Type text/event-stream lacks charset,
    # so requests defaults to ISO-8859-1 which corrupts accented chars).
    raw_text = r.content.decode("utf-8")

    # Parse SSE events
    queries: list[dict] = []
    texts: list[str] = []
    chart_data_list: list[dict] = []
    conv_id = conversation_id or ""
    for chunk in raw_text.split("\n\n"):
        data_line = None
        for line in chunk.strip().split("\n"):
            if line.startswith("data:"):
                data_line = line[5:].strip()
        if not data_line:
            continue
        try:
            evt = _json.loads(data_line)
        except _json.JSONDecodeError:
            log.debug("Ignoring malformed Genie SSE event")
            continue
        etype = evt.get("type", "")
        if etype == "response.created":
            conv_id = evt.get("response", {}).get("conversation_id", "")
        elif "output_item" in etype:
            item = evt.get("item", {})
            itype = item.get("type", "")
            status = item.get("status", "")
            if itype == "function_call" and status == "completed" and etype.endswith(".done"):
                try:
                    args = _json.loads(item.get("arguments", "{}"))
                    if args.get("sql"):
                        queries.append({"title": args.get("title", ""), "sql": args["sql"]})
                except _json.JSONDecodeError:
                    log.debug("Ignoring malformed Genie function arguments")
            elif itype == "function_call_output" and etype.endswith(".done"):
                output_md = item.get("output", "")
                parsed = _parse_md_table(output_md)
                if parsed and parsed["rows"]:
                    chart_data_list.append(parsed)
            elif itype == "message" and status == "completed" and etype.endswith(".done"):
                for c in item.get("content", []):
                    if c.get("type") == "output_text" and c.get("text"):
                        texts.append(c["text"])

    # Build attachments in same format as chat mode
    attachments: list[dict] = []
    for q in queries:
        attachments.append({"type": "query", "sql": q["sql"], "title": q["title"],
                            "attachment_id": "", "description": "", "statement_id": "",
                            "row_count": None, "thoughts": []})
    for chart_index, cd in enumerate(chart_data_list):
        str_cols = [i for i, c in enumerate(cd["columns"]) if c["type"] == "STRING"]
        num_cols = [i for i, c in enumerate(cd["columns"]) if c["type"] == "DOUBLE"]
        if not str_cols or not num_cols:
            continue  # Skip lookup tables (no numeric) or pure-numeric tables
        # Preserve all fields so the UI can choose the safest visual while keeping
        # the complete result available in the data table.
        attachments.append({"type": "chart_data", "title": cd["title"],
                            "query_index": chart_index,
                            "columns": cd["columns"], "rows": cd["rows"],
                            "row_count": len(cd["rows"]), "status": "SUCCEEDED"})
    if texts:
        answer = "\n\n".join(texts)
        if chart_data_list:
            answer = _strip_md_tables(answer)
        attachments.append({"type": "text", "content": answer,
                            "purpose": "TEXT_ATTACHMENT_PURPOSE_ANSWER"})

    return {
        "deep_result": True,
        "mode": "agent",
        "conversation_id": conv_id,
        "space_name": space["name"],
        "status": "COMPLETED",
        "attachments": attachments,
    }

@app.get("/api/genie/result/{space_key}/{conv_id}/{msg_id}")
def genie_result(space_key: GenieSpace, conv_id: str, msg_id: str):
    access = _require_unrestricted_upstream("Genie")
    space = GENIE.get(space_key)
    if not space:
        raise HTTPException(400, "Espacio inválido")
    conv_id = _validate_resource_id(conv_id, "conversation_id")
    _assert_genie_conversation_owner(conv_id, access)
    msg_id = _validate_resource_id(msg_id, "message_id")
    r = http_requests.get(
        f"{HOST}/api/2.0/genie/spaces/{space['id']}/conversations/{conv_id}/messages/{msg_id}",
        headers=_headers(), timeout=(5, 30),
    )
    _raise_upstream(r, "Genie")
    d = r.json()
    status = d.get("status", "UNKNOWN")
    result: dict[str, Any] = {
        "status": status,
        "space_key": space_key,
        "space_name": space["name"],
        "conversation_id": conv_id,
        "message_id": msg_id,
        "created_timestamp": d.get("created_timestamp"),
        "last_updated_timestamp": d.get("last_updated_timestamp"),
    }
    if status == "COMPLETED":
        attachments: list[dict] = []
        for att in d.get("attachments", []):
            if att.get("query"):
                q = att["query"]
                attachments.append({
                    "type": "query",
                    "attachment_id": att.get("attachment_id", ""),
                    "sql": q.get("query", ""),
                    "title": q.get("title", ""),
                    "description": q.get("description", ""),
                    "statement_id": q.get("statement_id", ""),
                    "row_count": (q.get("query_result_metadata") or {}).get("row_count"),
                    "thoughts": q.get("thoughts", []),
                })
            elif att.get("text"):
                t = att["text"]
                attachments.append({
                    "type": "text",
                    "content": t.get("content", ""),
                    "purpose": t.get("purpose", ""),
                })
            elif att.get("viz"):
                attachments.append({
                    "type": "viz",
                    "attachment_id": att.get("attachment_id", ""),
                    "query_attachment_id": att["viz"].get("query_attachment_id", ""),
                })
            elif att.get("suggested_questions"):
                attachments.append({
                    "type": "suggested_questions",
                    "questions": att["suggested_questions"].get("questions", []),
                })
        result["attachments"] = attachments
        log.info(
            "genie_completed space=%s conversation_id=%s message_id=%s attachments=%s types=%s",
            space_key, conv_id, msg_id, len(attachments),
            ",".join(att["type"] for att in attachments),
        )
    elif status in {"FAILED", "CANCELLED"}:
        error = d.get("error") or d.get("failure_reason") or {}
        result["error"] = error if isinstance(error, str) else error.get("message", "")
        log.warning(
            "genie_terminal space=%s conversation_id=%s message_id=%s status=%s error=%r",
            space_key, conv_id, msg_id, status, result.get("error", "")[:500],
        )
    return result


@app.get("/api/genie/query-data/{space_key}/{conv_id}/{msg_id}/{attachment_id}")
def genie_query_data(space_key: GenieSpace, conv_id: str, msg_id: str, attachment_id: str):
    """Fetch query result data for a Genie attachment (used to render charts)."""
    access = _require_unrestricted_upstream("Genie")
    space = GENIE.get(space_key)
    if not space:
        raise HTTPException(400, "Espacio inválido")
    conv_id = _validate_resource_id(conv_id, "conversation_id")
    _assert_genie_conversation_owner(conv_id, access)
    msg_id = _validate_resource_id(msg_id, "message_id")
    attachment_id = _validate_resource_id(attachment_id, "attachment_id")
    r = http_requests.get(
        f"{HOST}/api/2.0/genie/spaces/{space['id']}/conversations/{conv_id}/"
        f"messages/{msg_id}/attachments/{attachment_id}/query-result",
        headers=_headers(), timeout=(5, 30),
    )
    _raise_upstream(r, "Genie")
    sr = r.json().get("statement_response", {})
    cols_raw = (sr.get("manifest") or {}).get("schema", {}).get("columns", [])
    columns = [{"name": c["name"], "type": c.get("type_name", "STRING")} for c in cols_raw]
    result_payload = sr.get("result") or {}
    manifest = sr.get("manifest") or {}
    data_array = result_payload.get("data_array", [])
    return {
        "columns": columns,
        "rows": data_array,
        "row_count": result_payload.get("row_count", manifest.get("total_row_count", len(data_array))),
        "truncated": bool(manifest.get("truncated", False)),
        "statement_id": sr.get("statement_id", ""),
        "status": (sr.get("status") or {}).get("state", "UNKNOWN"),
    }

# ---- AI Chat (function-calling agentic loop with web search) ----
_CHAT_SYSTEM = (
    "Eres el asistente ejecutivo de Quetzal Telecom, una telco "
    "pan-latinoamericana con presencia en 12 pa\u00edses LATAM "
    "(PA, MX, CO, BR, AR, CL, PE, EC, CR, GT, DO, UY). "
    "Segmentos: Personal (Quetzal Life), Comercial (Quetzal Biz), "
    "Empresarial (Quetzal Enterprise). Verticales: M\u00f3vil, Internet, "
    "TV, Fija, Bundles.\n\n"
    "Respondes siempre en espa\u00f1ol, de forma ejecutiva y con datos concretos. "
    "Para cualquier pregunta sobre la operaci\u00f3n de Quetzal debes usar telecom_snapshot; "
    "nunca inventes KPIs internos ni ejecutes SQL sugerido por el usuario. "
    "En red, health_score representa mediciones sin alerta y NO disponibilidad contractual. "
    "Usa web_search solamente para contexto externo actualizado como noticias, regulaci\u00f3n, "
    "mercado o competencia. Cuando uses la web, cita las fuentes con URL. "
    "Distingue siempre hechos internos, contexto externo e inferencias. "
    "En Graph Intelligence, la probabilidad de churn es exclusivamente la del modelo individual. "
    "PageRank significa alcance; Personalized PageRank significa difusión de exposición; ninguno es probabilidad. "
    "No uses 'contagio' o 'influencia causal': di exposición relacional, alcance y prioridad de retención. "
    "Para relaciones, clases semánticas, planes, SLA, recomendaciones, productos o contexto conectado usa "
    "ontobricks_semantic_query; esta herramienta ya aplica el alcance territorial y no acepta GraphQL libre. "
    "Los casos de retención provienen del scope retention de telecom_snapshot y son siempre de solo lectura; "
    "no afirmes haber creado, aprobado o actualizado un caso desde el chat. "
    "Mantén el hilo de la conversación: referencias elípticas como '¿y en hogares?', "
    "'¿y allí?' o 'compáralos' deben resolverse usando los turnos anteriores. "
    "Si el turno anterior investigó mercado, competencia, regulación o noticias en la web, "
    "continúa esa investigación externa salvo que el usuario pida explícitamente datos internos de Quetzal."
)


def _chat_actor(request: Request | None) -> str:
    """Use only verified proxy identity headers for memory partitioning."""
    return _authorized_access().actor


def _turn_tool_names(turn: dict[str, Any]) -> list[str]:
    return [
        str(item if isinstance(item, str) else item.get("tool", ""))
        for item in (turn.get("tools") or [])
        if isinstance(item, (str, dict))
    ]


def _history_transcript(history: list[dict[str, Any]]) -> str:
    if not history:
        return "Sin turnos anteriores."
    lines: list[str] = []
    for turn in history[-24:]:
        label = "USUARIO" if turn.get("role") == "user" else "QUETZAL IQ"
        text = str(turn.get("text", "")).strip()[:12000]
        tools = ", ".join(name for name in _turn_tool_names(turn) if name)
        tool_note = f" [herramientas: {tools}]" if tools else ""
        lines.append(f"{label}{tool_note}: {text}")
    return "\n\n".join(lines)


def _select_chat_tools(
    *,
    continuation_mode: str,
    history: list[dict[str, Any]],
    message: str,
    disable_tools: bool,
) -> tuple[list[dict[str, Any]], str]:
    if disable_tools:
        return [], "disabled"
    if continuation_mode == "external":
        return [_WEB_SEARCH_TOOL], "external"
    if continuation_mode == "internal":
        return _INTERNAL_CHAT_TOOLS, "internal"

    previous_assistant = next(
        (turn for turn in reversed(history) if turn.get("role") == "assistant"),
        None,
    )
    prior_tools = set(_turn_tool_names(previous_assistant or {}))
    normalized = message.casefold()
    explicit_internal = any(
        marker in normalized
        for marker in (
            "quetzal", "nuestros clientes", "nuestros ingresos", "nuestra red",
            "datos internos", "operación interna", "operacion interna",
        )
    )
    if "web_search" in prior_tools and not explicit_internal:
        return [_WEB_SEARCH_TOOL], "external"
    semantic_terms = (
        "grafo", "relación", "relacion", "conectad", "ontología", "ontologia",
        "ontobricks", "plan", "producto", "sla", "recomendación", "recomendacion",
        "grupo de relación", "contacto calificado",
    )
    if any(term in normalized for term in semantic_terms):
        return _INTERNAL_CHAT_TOOLS, "internal"
    return _CHAT_TOOLS, "auto"


def _extract_ai_text(response: dict[str, Any]) -> tuple[str, list[dict[str, str]]]:
    """Extract text from Responses API and compatible chat payload variants."""
    citations: list[dict[str, str]] = []
    candidates: list[str] = []

    if isinstance(response.get("output_text"), str):
        candidates.append(response["output_text"])

    for item in response.get("output", []):
        if not isinstance(item, dict) or item.get("type") not in {"message", "output_message", None}:
            continue
        content = item.get("content", [])
        if isinstance(content, str):
            candidates.append(content)
            content = []
        if isinstance(item.get("text"), str):
            candidates.append(item["text"])
        for part in content if isinstance(content, list) else []:
            if not isinstance(part, dict) or part.get("type") not in {"output_text", "text"}:
                continue
            value = part.get("text") or part.get("content")
            if isinstance(value, str):
                candidates.append(value)
            for annotation in part.get("annotations", []):
                if not isinstance(annotation, dict) or annotation.get("type") != "url_citation":
                    continue
                url = annotation.get("url", "")
                if isinstance(url, str) and url.startswith(("https://", "http://")):
                    citations.append({"url": url, "title": str(annotation.get("title", ""))})

    for choice in response.get("choices", []):
        content = (choice.get("message") or {}).get("content") if isinstance(choice, dict) else None
        if isinstance(content, str):
            candidates.append(content)

    text = "\n\n".join(value.strip() for value in candidates if value and value.strip())
    text = _re.sub(r'<\uff5c[^\n]*?\uff5c>', '', text).strip()
    return text, citations


def _dedupe_citations(citations: list[dict[str, str]]) -> list[dict[str, str]]:
    unique: list[dict[str, str]] = []
    seen: set[str] = set()
    for citation in citations:
        url = citation.get("url", "")
        if not url or url in seen:
            continue
        seen.add(url)
        unique.append(citation)
    return unique[:10]


@app.get("/api/chat/sessions")
def chat_sessions(request: Request):
    actor = _chat_actor(request)
    try:
        sessions = conversation_store.list_sessions(actor)
        return {"sessions": sessions, "memory": {"status": "AVAILABLE", "store": "lakebase"}}
    except Exception as exc:  # noqa: BLE001 - memory must degrade without breaking IQ
        log.warning("iq_memory_list_unavailable actor=%s error=%s", actor, exc)
        return {"sessions": [], "memory": {"status": "DEGRADED", "store": "browser"}}


@app.get("/api/chat/sessions/{conversation_id}")
def chat_session(conversation_id: str, request: Request):
    conversation_id = _validate_resource_id(conversation_id, "conversation_id")
    actor = _chat_actor(request)
    try:
        turns = conversation_store.restore(actor, conversation_id, limit=100)
        return {"conversation_id": conversation_id, "messages": turns, "memory": {"status": "RESTORED", "store": "lakebase"}}
    except Exception as exc:  # noqa: BLE001
        log.warning("iq_memory_restore_unavailable actor=%s conversation_id=%s error=%s", actor, conversation_id, exc)
        return {"conversation_id": conversation_id, "messages": [], "memory": {"status": "DEGRADED", "store": "browser"}}


@app.post("/api/chat")
def ai_chat(request_data: ChatRequest, request: Request = None):
    trace_id = f"iq-{uuid4().hex[:12]}"
    message = request_data.message
    disable_tools = request_data.disable_tools
    actor = _chat_actor(request)
    conversation_id = request_data.conversation_id or f"iqc-{uuid4().hex}"
    request_history = [turn.model_dump() for turn in request_data.history]
    stored_history: list[dict[str, Any]] = []
    memory_status = {"status": "CLIENT_CONTEXT", "store": "request", "restored_messages": 0}
    if request_data.conversation_id:
        try:
            stored_history = conversation_store.restore(actor, conversation_id)
            if stored_history:
                memory_status = {
                    "status": "RESTORED", "store": "lakebase",
                    "restored_messages": len(stored_history),
                }
        except Exception as exc:  # noqa: BLE001
            log.warning(
                "iq_memory_restore_unavailable trace_id=%s conversation_id=%s error=%s",
                trace_id, conversation_id, exc,
            )
            memory_status = {"status": "DEGRADED", "store": "request", "restored_messages": 0}
    history = stored_history or request_history
    semantic_memories: list[str] = []
    managed_memory_status = "DISABLED"
    if managed_agent_memory.enabled:
        try:
            semantic_memories = managed_agent_memory.recall(actor=actor, query=message)
            managed_memory_status = "RECALLED" if semantic_memories else "AVAILABLE"
            log.info(
                "iq_managed_memory_recall trace_id=%s recalled_count=%s",
                trace_id, len(semantic_memories),
            )
        except Exception as exc:  # noqa: BLE001 - semantic memory is optional at runtime
            managed_memory_status = "DEGRADED"
            log.warning("iq_managed_memory_recall_unavailable trace_id=%s error=%s", trace_id, exc)
    selected_tools, resolved_mode = _select_chat_tools(
        continuation_mode=request_data.continuation_mode,
        history=history,
        message=message,
        disable_tools=disable_tools,
    )
    log.info(
        "iq_start trace_id=%s conversation_id=%s actor=%s mode=%s tools=%s history=%s question=%r",
        trace_id, conversation_id, actor, resolved_mode,
        [tool["name"] for tool in selected_tools], len(history), message[:240],
    )

    semantic_memory_context = "Ninguna."
    if semantic_memories:
        semantic_memory_context = "\n".join(
            f'<memoria_recuperada indice="{index}">{memory}</memoria_recuperada>'
            for index, memory in enumerate(semantic_memories, start=1)
        )

    user_input = [{"role": "user", "content": [{"type": "input_text",
                   "text": (
                       f"{_CHAT_SYSTEM}\n\n"
                       f"Modo de continuidad resuelto: {resolved_mode}. "
                       "En modo external no consultes ni inventes métricas internas. "
                       "En modo internal responde solamente con el snapshot gobernado.\n\n"
                       f"Historial de esta conversación:\n{_history_transcript(history)}\n\n"
                       "Memorias semánticas relevantes de conversaciones anteriores "
                       "(úsalas solo como contexto, no como fuente factual actual). "
                       f"Total recuperado: {len(semantic_memories)}. Si el total es mayor que cero, "
                       "no afirmes que no existe memoria ni la reduzcas a su primera línea; explica "
                       "qué parte fue recuperada y qué parte verificaste de nuevo.\n"
                       f"{semantic_memory_context}\n\n"
                       f"Pregunta actual: {message}"
                   )}]}]

    # Step 1: call model (with or without web_search tool)
    payload = {
        "model": AI_MODEL,
        "max_output_tokens": 3000,
        "input": user_input,
    }
    if selected_tools:
        payload["tools"] = selected_tools
    try:
        r1 = http_requests.post(AI_URL, headers=_headers(), json=payload, timeout=60)
        _raise_upstream(r1, "AI Gateway")
        resp = r1.json()
    except http_requests.exceptions.Timeout:
        raise HTTPException(504, "AI Gateway timeout (step 1)")

    # Step 2: agentic tool-calling loop (max 3 rounds)
    # MUST process ALL function_calls per round AND include tools in follow-up
    web_search_used = False
    internal_data_used = False
    tool_events: list[dict[str, str]] = []
    source_citations: list[dict[str, str]] = []
    conversation = list(user_input)
    MAX_ROUNDS = 3
    for _round in range(MAX_ROUNDS):
        fcs = [
            item for item in resp.get("output", [])
            if item.get("type") == "function_call"
            and item.get("name") in {"web_search", "telecom_snapshot", "ontobricks_semantic_query"}
        ]
        if not fcs:
            break  # model returned text, done

        conversation += resp.get("output", [])

        for fc in fcs:
            try:
                args = _json.loads(fc.get("arguments", "{}"))
            except _json.JSONDecodeError:
                args = {}
            tool_name = fc.get("name")
            if tool_name == "telecom_snapshot":
                internal_data_used = True
                scope = args.get("scope", "executive")
                customer_id = args.get("customer_id")
                graph_terms = (
                    "graph", "grafo", "comunidad", "comunidade", "contagio", "contágio",
                    "influencia", "influência", "alcance", "exposición", "exposicao", "exposição", "ontobricks",
                )
                if any(term in message.lower() for term in graph_terms):
                    scope = "graph"
                retention_terms = ("caso de retención", "casos de retención", "caso de retencion", "retention case", "sla de retención")
                if any(term in message.lower() for term in retention_terms):
                    scope = "retention"
                if scope not in {"executive", "revenue", "customers", "network", "graph", "retention"}:
                    scope = "executive"
                log.info("Agent round %s: telecom_snapshot(%s, %s)", _round + 1, scope, customer_id)
                tool_events.append({"tool": "telecom_snapshot", "input": {"scope": scope, "customer_id": customer_id}})
                tool_result = _execute_telecom_snapshot(scope, customer_id)
            elif tool_name == "ontobricks_semantic_query":
                internal_data_used = True
                intent = str(args.get("intent") or "CUSTOMER_CONTEXT")
                class_name = args.get("class_name")
                customer_id = args.get("customer_id")
                limit = args.get("limit", 20)
                tool_result = _execute_ontobricks_semantic(intent, class_name, customer_id, limit)
                tool_events.append({
                    "tool": "ontobricks_semantic_query",
                    "input": {"intent": intent, "class_name": class_name, "customer_id": customer_id},
                    "source": {
                        "type": "ONTOBRICKS_MCP", "domain": settings.ontobricks_domain,
                        "version": settings.ontobricks_version,
                    },
                })
            else:
                web_search_used = True
                query = str(args.get("query", message))[:500]
                log.info("Agent round %s: web_search(%s)", _round + 1, query)
                tool_events.append({"tool": "web_search", "input": query})
                tool_result = _execute_search(query)
                if tool_result == '[]':
                    tool_result = _json.dumps([{"title": "Sin resultados", "snippet": "No se encontraron resultados verificables.", "url": ""}])
                try:
                    for source in _json.loads(tool_result):
                        url = str(source.get("url", ""))
                        if url.startswith(("https://", "http://")):
                            source_citations.append({"url": url, "title": str(source.get("title", ""))})
                except (_json.JSONDecodeError, TypeError):
                    log.warning("iq_search_result_unparseable trace_id=%s", trace_id)
            conversation.append({
                "type": "function_call_output",
                "call_id": fc.get("call_id", ""),
                "output": tool_result,
            })

        try:
            follow_up = {
                "model": AI_MODEL,
                "max_output_tokens": 3000,
                "input": conversation,
            }
            # The last round is synthesis-only. This prevents a final function
            # call from being mistaken for an empty answer when the budget ends.
            if _round + 1 < MAX_ROUNDS:
                follow_up["tools"] = selected_tools
            rn = http_requests.post(AI_URL, headers=_headers(), json=follow_up, timeout=60)
            if rn.status_code == 200:
                resp = rn.json()
            else:
                _raise_upstream(rn, "AI Gateway")
        except HTTPException:
            raise
        except http_requests.exceptions.Timeout:
            raise HTTPException(504, "AI Gateway timeout")
        except http_requests.exceptions.RequestException as e:
            log.warning(f"Round {_round+1} error: {e}")
            break

    # Step 3: extract final text + citations, including compatible model variants.
    text, model_citations = _extract_ai_text(resp)
    citations = _dedupe_citations(model_citations + source_citations)
    if not text:
        output_types = [
            str(item.get("type", "unknown"))
            for item in resp.get("output", []) if isinstance(item, dict)
        ]
        log.error(
            "iq_empty_answer trace_id=%s model=%s output_types=%s tools=%s",
            trace_id, resp.get("model", AI_MODEL), output_types,
            [event["tool"] for event in tool_events],
        )
        text = (
            "No fue posible completar la síntesis de la respuesta. "
            "Las herramientas fueron consultadas, pero el modelo no devolvió texto final."
        )
        answer_status = "error"
    elif tool_events:
        answer_status = "verified"
    else:
        answer_status = "generated"
    log.info(
        "iq_complete trace_id=%s status=%s model=%s tools=%s citations=%s output_chars=%s",
        trace_id, answer_status, resp.get("model", AI_MODEL),
        [event["tool"] for event in tool_events], len(citations), len(text),
    )
    response_payload = {
        "trace_id": trace_id,
        "conversation_id": conversation_id,
        "answer_status": answer_status,
        "response": text,
        "model": resp.get("model", ""),
        "tokens": resp.get("usage", {}),
        "citations": citations,
        "web_search_used": web_search_used,
        "internal_data_used": internal_data_used,
        "tools_used": tool_events,
        "continuation_mode": resolved_mode,
        "memory": memory_status,
        "managed_memory": {
            "status": managed_memory_status,
            "store": "databricks_managed_memory",
            "recalled": bool(semantic_memories),
            "recalled_count": len(semantic_memories),
            "persisted": False,
        },
    }
    try:
        conversation_store.save_exchange(
            actor=actor,
            conversation_id=conversation_id,
            question=message,
            answer=text,
            trace_id=trace_id,
            model=resp.get("model", AI_MODEL),
            citations=citations,
            tools=tool_events,
            metadata={
                "answer_status": answer_status,
                "continuation_mode": resolved_mode,
                "web_search_used": web_search_used,
                "internal_data_used": internal_data_used,
            },
        )
        if conversation_store.enabled:
            response_payload["memory"] = {
                **memory_status,
                "persisted": True,
                "store": "lakebase",
            }
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "iq_memory_save_unavailable trace_id=%s conversation_id=%s error=%s",
            trace_id, conversation_id, exc,
        )
        response_payload["memory"] = {
            **memory_status,
            "persisted": False,
            "store": "request",
        }
    try:
        managed_agent_memory.remember_research(
            actor=actor,
            conversation_id=conversation_id,
            trace_id=trace_id,
            question=message,
            answer=text,
            tools=tool_events,
        )
        if managed_agent_memory.enabled and web_search_used:
            response_payload["managed_memory"] = {
                # Recall is the user-visible result; persistence is an
                # independent write outcome. Do not overwrite RECALLED after
                # successfully saving the current external research.
                "status": "RECALLED" if semantic_memories else "PERSISTED",
                "store": "databricks_managed_memory",
                "recalled": bool(semantic_memories),
                "recalled_count": len(semantic_memories),
                "persisted": True,
            }
    except Exception as exc:  # noqa: BLE001
        log.warning("iq_managed_memory_save_unavailable trace_id=%s error=%s", trace_id, exc)
        response_payload["managed_memory"] = {
            "status": "DEGRADED", "store": "databricks_managed_memory",
            "recalled": bool(semantic_memories),
            "recalled_count": len(semantic_memories),
            "persisted": False,
        }
    return response_payload

# ---- Frontend ----
BASE_DIR = Path(__file__).resolve().parent
FRONTEND_DIR = BASE_DIR / "frontend" / "dist"
LEGACY_STATIC_DIR = BASE_DIR / "static"

if FRONTEND_DIR.exists():
    app.mount("/assets", StaticFiles(directory=str(FRONTEND_DIR / "assets")), name="assets")
elif LEGACY_STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(LEGACY_STATIC_DIR)), name="static")

@app.get("/")
def root():
    index = FRONTEND_DIR / "index.html" if FRONTEND_DIR.exists() else LEGACY_STATIC_DIR / "index.html"
    return FileResponse(index)


@app.get("/{full_path:path}")
def spa_fallback(full_path: str):
    if full_path.startswith("api/"):
        raise HTTPException(404, "Endpoint no encontrado.")
    index = FRONTEND_DIR / "index.html" if FRONTEND_DIR.exists() else LEGACY_STATIC_DIR / "index.html"
    return FileResponse(index)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
