"""Operational telecom APIs: incidents, impact, actions, topology and scenarios."""

from __future__ import annotations

import hashlib
import json
import math
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from uuid import uuid4

import requests
from fastapi import APIRouter, HTTPException, Query, Request

from .access import require_roles, resolve_access, submit_with_context
from .campaign_workflow import (
    CampaignConflict,
    CampaignNotFound,
    campaign_store,
)
from .config import COUNTRIES, settings
from .connectors import connector_for, dispatch_action
from .managed_memory import managed_agent_memory
from .memory import conversation_store
from .models import (
    ActionCreateRequest,
    ActionDecisionRequest,
    ActionExecutionRequest,
    AlertAcknowledgeRequest,
    AlertStateRequest,
    AlertSubscriptionRequest,
    CampaignDraftCreateRequest,
    CampaignDraftRevisionRequest,
    CampaignDraftTransitionRequest,
    CampaignOptimizeRequest,
    FinancialImpactRequest,
    IncidentUpdateRequest,
    RecommendationDecisionRequest,
    RecommendationOutcomeRequest,
    RetentionCaseCreateRequest,
    RetentionCaseTransitionRequest,
    ScenarioRequest,
)
from .platform import (
    SqlExecutionError,
    auth_headers,
    execute_sql,
    run_sql,
    workspace_client,
)
from .retention_cases import (
    RetentionCaseNotFound,
    RetentionConflict,
    retention_case_store,
)

router = APIRouter(prefix="/api", tags=["operations"])
fanout = ThreadPoolExecutor(max_workers=4, thread_name_prefix="quetzal-ops")

CAUSE_LABELS = {
    "THERMAL": "Sobrecarga térmica del equipo",
    "CONGESTION": "Congestión de capacidad",
    "TRANSPORT": "Degradación de transporte",
    "BACKHAUL": "Latencia elevada en backhaul",
    "RADIO_SIGNAL": "Degradación de señal de radio",
}

ACTION_LABELS = {
    "DISPATCH_FIELD": "Despachar equipo de campo",
    "CREATE_WORK_ORDER": "Crear orden de trabajo",
    "CUSTOMER_NOTICE": "Notificar clientes afectados",
    "RETENTION_CAMPAIGN": "Iniciar campaña de retención",
    "COMPENSATION": "Aprobar compensación",
    "CAPACITY_CHANGE": "Modificar capacidad de red",
}

VOC_THEME_LABELS = {
    "NETWORK_QUALITY": "Calidad y cobertura de red",
    "BILLING": "Facturación y pagos",
    "SERVICE": "Atención y soporte",
    "PLAN_VALUE": "Planes, precio y valor",
    "OTHER": "Otros motivos",
}

VOC_RECOMMENDED_FOCUS = {
    "NETWORK_QUALITY": "Correlacionar reclamos con experiencia de red y priorizar recuperación de servicio.",
    "BILLING": "Revisar claridad de factura, cobros y alternativas de pago antes de contactar.",
    "SERVICE": "Reducir reaperturas, tiempo de resolución y brechas de SLA.",
    "PLAN_VALUE": "Validar necesidad, precio y adecuación del plan con consentimiento vigente.",
    "OTHER": "Revisar una muestra gobernada antes de crear una acción específica.",
}

CAMPAIGN_COSTS_EXCLUDED = [
    "Descuentos, subsidios o incentivos concedidos al cliente.",
    "Impuestos, comisiones comerciales y costo de financiación.",
    "Costo incremental de fulfillment, instalación o equipamiento.",
    "Mano de obra operacional adicional fuera del costo por contacto informado.",
    "Efectos de canibalización, costo de oportunidad y respuesta de competidores.",
]


def _campaign_projection(
    *,
    potential_benefit_usd: float,
    contact_cost_usd: float,
    response_rate_pct: float,
    objective: str,
) -> dict:
    """Project campaign economics over the exact selected audience."""
    bounded_rate = max(0.0, min(100.0, response_rate_pct))
    expected_benefit = potential_benefit_usd * bounded_rate / 100
    net_impact = expected_benefit - contact_cost_usd
    return {
        "expected_response_rate_pct": round(bounded_rate, 2),
        "estimated_conversions": None,
        "estimated_retained_revenue_usd": round(expected_benefit, 2) if objective == "RETENTION" else 0.0,
        "estimated_incremental_revenue_usd": round(expected_benefit, 2) if objective == "CROSS_SELL" else 0.0,
        "estimated_gross_benefit_usd": round(expected_benefit, 2),
        "estimated_contact_cost_usd": round(contact_cost_usd, 2),
        "estimated_net_impact_usd": round(net_impact, 2),
        "estimated_roi_pct": round(100 * net_impact / contact_cost_usd, 1) if contact_cost_usd else None,
        "outcome": "POSITIVE" if net_impact > 0 else "NEGATIVE" if net_impact < 0 else "BREAK_EVEN",
    }


def _validate_customer_id(customer_id: str) -> str:
    if not customer_id or len(customer_id) > 128 or not all(char.isalnum() or char in "-_" for char in customer_id):
        raise HTTPException(400, "Identificador de cliente inválido.")
    return customer_id


def _idempotency_key(request: Request) -> str:
    value = request.headers.get("Idempotency-Key", "").strip()
    if not value or len(value) > 128 or not all(char.isalnum() or char in "-_.:" for char in value):
        raise HTTPException(400, "Se requiere un Idempotency-Key válido (máximo 128 caracteres).")
    return value


def _retention_store_error(exc: Exception) -> HTTPException:
    if isinstance(exc, RetentionCaseNotFound):
        return HTTPException(404, "Caso de retención no encontrado.")
    if isinstance(exc, RetentionConflict):
        return HTTPException(409, str(exc))
    return HTTPException(
        503,
        "El workflow de retención está temporalmente no disponible en Lakebase; no se registró un éxito parcial.",
    )


def _campaign_store_error(exc: Exception) -> HTTPException:
    if isinstance(exc, CampaignNotFound):
        return HTTPException(404, "Campaña no encontrada.")
    if isinstance(exc, CampaignConflict):
        return HTTPException(409, str(exc))
    return HTTPException(
        503,
        "El ciclo de campañas está temporalmente no disponible en Lakebase; no se registró un éxito parcial.",
    )


def _validate_campaign_id(campaign_id: str) -> str:
    if not campaign_id or len(campaign_id) > 64 or not all(
        char.isalnum() or char in "-_" for char in campaign_id
    ):
        raise HTTPException(400, "Identificador de campaña inválido.")
    return campaign_id


def _assert_campaign_access(access: dict, campaign: dict) -> None:
    authorized = set(access.get("countries") or [])
    campaign_scope = set(campaign.get("country_scope") or [])
    if authorized and (not campaign_scope or not campaign_scope.issubset(authorized)):
        raise HTTPException(403, "La campaña está fuera de tu alcance territorial.")


def _retention_model_snapshot(customer_id: str) -> dict:
    rows = run_sql(
        """SELECT churn_probability, model_name, model_version, model_run_id, scored_at
           FROM gold_churn_predictions
           WHERE cliente_id = :customer_id
           ORDER BY scored_at DESC LIMIT 1""",
        parameters={"customer_id": customer_id},
        cache_ttl=0,
    )
    if not rows:
        raise HTTPException(409, "El cliente no tiene un scoring de churn gobernado disponible.")
    model = rows[0]
    required = ("churn_probability", "model_name", "model_version", "model_run_id")
    if any(model.get(key) is None for key in required):
        raise HTTPException(409, "El scoring de churn no contiene versión y run de MLflow completos.")
    return model


def _next_best_actions(profile: dict, tickets: list[dict], offers: list[dict]) -> list[dict]:
    """Build deterministic, explainable recommendations from governed signals."""
    actions: list[dict] = []
    open_tickets = int(profile.get("open_tickets") or 0)
    baseline_churn = float(profile.get("churn_probability") or 0)
    churn = baseline_churn
    reach = float(profile.get("reach_score") or profile.get("influence_score") or 0)
    exposure = float(profile.get("network_exposure_score") or profile.get("contagion_risk_score") or 0)
    overdue = float(profile.get("overdue_balance") or 0)
    nps = int(profile.get("nps_ultimo") or 0)

    if open_tickets:
        breached = sum(1 for ticket in tickets if ticket.get("sla_status") == "BREACHED")
        actions.append({
            "type": "SERVICE_RECOVERY", "priority": "CRITICAL" if breached else "HIGH",
            "title": "Resolver experiencia antes de vender",
            "reason": f"{open_tickets} ticket(s) abierto(s); {breached} fuera del objetivo de atención.",
            "action": "Priorizar el caso, informar al cliente y cerrar la causa raíz.",
        })
    if churn >= 0.65:
        actions.append({
            "type": "RETENTION", "priority": "HIGH", "title": "Activar tratamiento de retención",
            "reason": f"Propensión individual de churn de {churn:.0%} en el modelo gobernado.",
            "action": "Revisar fricciones y preparar una oferta de permanencia con aprobación humana.",
        })
    if exposure >= 55 or reach >= 75:
        actions.append({
            "type": "NETWORK_CARE",
            "priority": "HIGH" if exposure >= 70 else "MEDIUM",
            "title": "Revisar exposición y alcance relacional",
            "reason": f"Alcance {reach:.0f}/100 y exposición relacional {exposure:.0f}/100 en contactos calificados.",
            "action": "Coordinar retención individual y seguimiento agregado de la comunidad, sin exponer identidades de terceros.",
        })
    if nps <= 6:
        actions.append({
            "type": "NPS_RECOVERY", "priority": "HIGH", "title": "Cerrar el ciclo con detractor",
            "reason": f"Último NPS individual: {nps}.",
            "action": "Contactar para entender la causa, registrar resolución y volver a medir.",
        })
    if overdue > 0:
        actions.append({
            "type": "PAYMENT_ASSISTANCE", "priority": "MEDIUM", "title": "Ofrecer alternativa de pago",
            "reason": f"Saldo vencido de USD {overdue:,.2f}.",
            "action": "Validar elegibilidad para acuerdo antes de aplicar restricciones de servicio.",
        })
    if not open_tickets and churn < 0.65 and bool(profile.get("acepta_marketing")):
        for offer in offers[:2]:
            actions.append({
                "type": offer.get("recommendation_type", "CROSS_SELL"), "priority": "MEDIUM",
                "title": f"Sugerir {offer.get('product_name')}", "reason": offer.get("reason"),
                "action": "Confirmar necesidad, elegibilidad y consentimiento antes de ofertar.",
                "product": offer,
            })
    if not actions:
        actions.append({
            "type": "MONITOR", "priority": "LOW", "title": "Mantener seguimiento",
            "reason": "No hay una señal crítica que justifique intervención inmediata.",
            "action": "Revisar el perfil en el próximo evento relevante.",
        })
    return actions


def _actor(request: Request) -> str:
    return _access(request)["actor"]


def _access(request: Request) -> dict:
    """Resolve app identity into governed roles and optional country scope."""
    return resolve_access(request, run_sql).as_dict()


def _require_role(request: Request, *allowed: str) -> dict:
    access = _access(request)
    if "ADMIN" not in access["roles"] and not set(allowed).intersection(access["roles"]):
        raise HTTPException(403, "Tu perfil no tiene permiso para realizar esta operación.")
    return access


def _require_context_role(*allowed: str) -> dict:
    access = resolve_access(None, run_sql)
    require_roles(access, allowed)
    return access.as_dict()


def _require_unrestricted_context(*allowed: str) -> dict:
    access = _require_context_role(*allowed)
    if access["countries"]:
        raise HTTPException(403, "Esta vista global no está disponible para perfiles con alcance territorial.")
    return access


def _assert_country_access(access: dict, country: str | None) -> None:
    if country and access["countries"] and country not in access["countries"]:
        raise HTTPException(403, "El país solicitado está fuera de tu alcance operativo.")


def _audit(event_type: str, resource_type: str, resource_id: str, actor: str, detail: dict) -> None:
    execute_sql(
        """
        INSERT INTO ops_audit_log
        VALUES (:event_id, :event_type, :resource_type, :resource_id, :actor, current_timestamp(), :detail_json)
        """,
        parameters={
            "event_id": uuid4().hex,
            "event_type": event_type,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "actor": actor,
            "detail_json": json.dumps(detail, ensure_ascii=False),
        },
    )


def _incident_select(where: str = "TRUE") -> str:
    return f"""
      SELECT c.*,
             COALESCE(s.status, 'NEW') AS status,
             s.assignee,
             s.acknowledged_at,
             s.resolved_at,
             s.updated_at,
             CASE c.severity WHEN 'CRITICAL' THEN 2 WHEN 'HIGH' THEN 4 WHEN 'MEDIUM' THEN 8 ELSE 24 END AS sla_target_hours,
             timestampadd(HOUR, CASE c.severity WHEN 'CRITICAL' THEN 2 WHEN 'HIGH' THEN 4 WHEN 'MEDIUM' THEN 8 ELSE 24 END, c.detected_at) AS sla_deadline_at,
             ROUND(timestampdiff(MINUTE, current_timestamp(), timestampadd(HOUR, CASE c.severity WHEN 'CRITICAL' THEN 2 WHEN 'HIGH' THEN 4 WHEN 'MEDIUM' THEN 8 ELSE 24 END, c.detected_at))/60.0, 1) AS sla_remaining_hours,
             CASE WHEN COALESCE(s.status, 'NEW') = 'RESOLVED' THEN 'MET'
                  WHEN current_timestamp() > timestampadd(HOUR, CASE c.severity WHEN 'CRITICAL' THEN 2 WHEN 'HIGH' THEN 4 WHEN 'MEDIUM' THEN 8 ELSE 24 END, c.detected_at) THEN 'BREACHED'
                  WHEN current_timestamp() > timestampadd(MINUTE, 45, c.detected_at) THEN 'AT_RISK'
                  ELSE 'ON_TRACK' END AS sla_status,
             CASE c.severity WHEN 'CRITICAL' THEN 4 WHEN 'HIGH' THEN 3 WHEN 'MEDIUM' THEN 2 ELSE 1 END AS priority_score
      FROM ops_incident_candidates c
      LEFT JOIN ops_incident_state s ON c.incident_id = s.incident_id
      WHERE {where}
    """


def _customer_profile(customer_id: str) -> list[dict]:
    """Prefer the graph-enriched 360 view while retaining pre-first-run availability."""
    try:
        return run_sql(
            "SELECT * FROM ops_customer_graph_360 WHERE cliente_id = :customer_id",
            parameters={"customer_id": customer_id},
            cache_ttl=15,
        )
    except SqlExecutionError:
        return run_sql(
            "SELECT * FROM ops_customer_360 WHERE cliente_id = :customer_id",
            parameters={"customer_id": customer_id},
            cache_ttl=15,
        )


def _number(value, default: float = 0.0) -> float:
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _country_scope(country: str, access: dict, column: str) -> tuple[str, dict[str, str]]:
    """Build a parameterized territorial filter for an allowlisted SQL column."""
    if country != "ALL":
        _assert_country_access(access, country)
        return f"{column} = :country", {"country": country}
    if access["countries"]:
        return f"array_contains(split(:country_scope, ','), {column})", {
            "country_scope": ",".join(access["countries"]),
        }
    return "TRUE", {}


def _effective_countries(country: str, access: dict) -> list[str]:
    if country != "ALL":
        return [country]
    return access["countries"] or ["ALL"]


def _ticket_theme_case(alias: str = "t") -> str:
    text = f"lower(concat_ws(' ', coalesce({alias}.categoria, ''), coalesce({alias}.motivo, '')))"
    return f"""CASE
      WHEN {text} RLIKE 'red|internet|señal|senal|cobertura|datos|llamada|latencia' THEN 'NETWORK_QUALITY'
      WHEN {text} RLIKE 'factur|cobro|pago|saldo|recarga' THEN 'BILLING'
      WHEN {text} RLIKE 'atenci|soporte|demora|ticket|reclamo|servicio' THEN 'SERVICE'
      WHEN {text} RLIKE 'plan|precio|tarifa|promoci|beneficio' THEN 'PLAN_VALUE'
      ELSE 'OTHER'
    END"""


def _voc_trend(current: int, previous: int) -> str:
    if previous <= 0:
        return "NO_BASELINE"
    ratio = current / previous
    if ratio > 1.10:
        return "UP"
    if ratio < 0.90:
        return "DOWN"
    return "STABLE"


def _explanation_codes(value) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            if isinstance(parsed, list):
                return [str(item) for item in parsed]
        except json.JSONDecodeError:
            pass
        return [item.strip() for item in value.strip("[]").split(",") if item.strip()]
    return []


def _customer_explainability(profile: dict) -> dict:
    """Keep churn probability separate from non-probabilistic graph signals."""
    baseline = _number(profile.get("baseline_churn_probability"), _number(profile.get("churn_probability")))
    graph_available = bool(profile.get("graph_model_version"))
    priority = profile.get("retention_priority_score")
    priority = _number(priority, baseline * 100) if graph_available else None
    neighbour_risk = _number(profile.get("neighbour_avg_churn_probability"))
    exposure = _number(profile.get("network_exposure_score"), _number(profile.get("contagion_risk_score")))
    reach = _number(profile.get("reach_score"), _number(profile.get("influence_score")))
    diffusion = _number(profile.get("risk_diffusion_score"))
    codes = _explanation_codes(profile.get("graph_explanation_codes"))
    code_labels = {
        "HIGH_RISK_NETWORK_EXPOSURE": "Exposición elevada a contactos con riesgo alto",
        "HIGH_NETWORK_INFLUENCE": "Alcance elevado dentro de la red de contactos (snapshot legado)",
        "HIGH_NETWORK_REACH": "Alcance elevado dentro de la red de contactos",
        "HIGH_RISK_DIFFUSION": "Alta proximidade a sementes de risco no grafo ponderado",
        "RELATIONSHIP_BRIDGE": "Cliente conecta partes pouco densas da rede",
        "CROSS_BORDER_REACH": "Alcance de contactos en tres o más países",
        "GRAPH_RISK_UPLIFT": "Código legado de enriquecimiento; no altera la probabilidad v3",
    }
    evidence = [{
        "code": "BASELINE_PROPENSITY",
        "label": "Propensión individual de churn",
        "value": round(baseline, 4),
        "scale": "0_TO_1",
        "direction": "INCREASES_RISK" if baseline >= 0.5 else "LOWERS_RISK",
        "source": "gold_churn_predictions",
    }]
    if graph_available:
        evidence.extend([
            {
                "code": "NEIGHBOUR_RISK",
                "label": "Riesgo promedio de contactos calificados",
                "value": round(neighbour_risk, 4),
                "scale": "0_TO_1",
                "direction": "INCREASES_RISK" if neighbour_risk > baseline else "LOWERS_RISK",
                "source": "gold_customer_graph_features",
            },
            {
                "code": "NETWORK_EXPOSURE",
                "label": "Exposición relacional a churn",
                "value": round(exposure, 1),
                "scale": "0_TO_100",
                "direction": "INCREASES_PRIORITY" if exposure >= 50 else "NEUTRAL",
                "source": "gold_customer_graph_features",
            },
            {
                "code": "NETWORK_REACH",
                "label": "Alcance en la red de contactos",
                "value": round(reach, 1),
                "scale": "0_TO_100",
                "direction": "INCREASES_PRIORITY" if reach >= 70 else "NEUTRAL",
                "source": "gold_customer_graph_features",
            },
        ])
    return {
        "method": "SEPARATED_PROPENSITY_AND_NETWORK_SIGNALS",
        "is_shap": False,
        "model_version": profile.get("graph_model_version") if graph_available else "baseline-only",
        "scores": {
            "individual_baseline": round(baseline, 4),
            "retention_priority": round(priority, 1) if priority is not None else None,
            "network_exposure": round(exposure, 1) if graph_available else None,
            "network_reach": round(reach, 1) if graph_available else None,
            "risk_diffusion": round(diffusion, 1) if graph_available else None,
        },
        "evidence": evidence,
        "reason_codes": [{"code": code, "label": code_labels.get(code, code.replace("_", " ").title())} for code in codes],
        "formula": (
            "Prioridad = 55% propensión individual + 20% exposición relacional + "
            "15% alcance + 10% valor. Es un ranking operativo, no una probabilidad."
        ) if graph_available else "Probabilidad individual gobernada; señales relacionales no disponibles.",
        "limitations": [
            "PageRank mide alcance; no predice churn por sí solo.",
            "Exposición y difusión son asociaciones de red; no demuestran contagio ni causalidad.",
            "La prioridad de retención no sustituye la probabilidad del modelo individual.",
        ],
    }


def _event_time(value) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _customer_timeline(
    profile: dict,
    subscriptions: list[dict],
    tickets: list[dict],
    billing: list[dict],
    nps: list[dict],
    recommendation_history: list[dict],
    geographic_incidents: list[dict],
    retention_cases: list[dict] | None = None,
    limit: int = 80,
) -> list[dict]:
    events: list[dict] = []

    def add(event_type: str, occurred_at, title: str, detail: dict, source: str, association: str = "DIRECT_CUSTOMER_EVENT") -> None:
        timestamp = _event_time(occurred_at)
        if timestamp:
            events.append({
                "event_type": event_type,
                "occurred_at": timestamp,
                "title": title,
                "detail": detail,
                "source": source,
                "association_type": association,
            })

    add("CHURN_SCORE", profile.get("graph_scored_at") or profile.get("churn_scored_at") or profile.get("scored_at"), "Scoring de churn actualizado", {
        "baseline_probability": profile.get("baseline_churn_probability") or profile.get("churn_probability"),
        "retention_priority": profile.get("retention_priority_score"),
        "network_exposure": profile.get("network_exposure_score") or profile.get("contagion_risk_score"),
        "risk_tier": profile.get("graph_risk_tier"),
    }, "ops_customer_graph_360")
    for item in subscriptions:
        add("SUBSCRIPTION_STARTED", item.get("fecha_inicio"), f"Suscripción {item.get('product_name') or item.get('plan_id')} iniciada", {
            "subscription_id": item.get("suscripcion_id"), "status": item.get("estado"),
            "monthly_price_usd": item.get("precio_mensual_usd"),
        }, "silver_suscripciones")
        add("SUBSCRIPTION_ENDED", item.get("fecha_fin"), f"Suscripción {item.get('product_name') or item.get('plan_id')} finalizada", {
            "subscription_id": item.get("suscripcion_id"), "status": item.get("estado"),
        }, "silver_suscripciones")
    for item in tickets:
        add("SUPPORT_TICKET", item.get("fecha_creacion"), f"Ticket {item.get('ticket_id')}", {
            "category": item.get("categoria"), "reason": item.get("motivo"), "status": item.get("estado"),
            "priority": item.get("prioridad"), "sla_status": item.get("sla_status"),
        }, "silver_tickets")
    for item in billing:
        add("BILLING", item.get("fecha_emision"), f"Factura {item.get('factura_id')}", {
            "amount_usd": item.get("monto_total_usd"), "payment_status": item.get("estado_pago"),
            "days_overdue": item.get("dias_atraso"), "due_at": _event_time(item.get("fecha_vencimiento")),
        }, "silver_facturas")
    for item in nps:
        add("NPS", item.get("fecha_encuesta"), f"NPS {item.get('score')}", {
            "score": item.get("score"), "category": item.get("categoria_nps"), "channel": item.get("canal_encuesta"),
        }, "silver_nps")
    for item in recommendation_history:
        add("RECOMMENDATION", item.get("proposed_at") or item.get("created_at"), item.get("title") or "Recomendación registrada", {
            "recommendation_id": item.get("recommendation_id"), "type": item.get("recommendation_type"),
            "decision": item.get("decision"), "outcome": item.get("outcome"),
        }, "ops_recommendation_log")
    for item in geographic_incidents:
        add("NETWORK_INCIDENT_CONTEXT", item.get("detected_at"), f"Contexto de red en {item.get('country')}", {
            "incident_id": item.get("incident_id"), "severity": item.get("severity"), "status": item.get("status"),
            "direct_customer_attribution": False,
        }, "ops_incident_candidates", "GEOGRAPHIC_CONTEXT")
    for case in retention_cases or []:
        for event in case.get("events") or []:
            add("RETENTION_CASE", event.get("created_at"), f"Caso {case.get('case_id')} · {event.get('to_status')}", {
                "case_id": case.get("case_id"), "priority": case.get("priority"),
                "from_status": event.get("from_status"), "status": event.get("to_status"),
                "actor": event.get("actor"), "note": event.get("note"),
            }, "lakebase.quetzal_app.retention_case_events")
    events.sort(key=lambda item: (item["occurred_at"], item["event_type"], item["title"]), reverse=True)
    return events[:limit]


def _check_result(name: str, check) -> dict:
    started = time.monotonic()
    try:
        status, detail = check()
    except Exception as exc:  # noqa: BLE001 - dependency SDKs expose heterogeneous failures
        status, detail = "DEGRADED", f"{type(exc).__name__}: {str(exc)[:240]}"
    return {
        "name": name,
        "status": status,
        "latency_ms": round((time.monotonic() - started) * 1000),
        "detail": detail,
    }


def _preflight_checks(access: dict) -> list[dict]:
    """Read-only dependency checks. This function never invokes models or jobs."""
    def warehouse():
        run_sql("SELECT 1 AS preflight", cache_ttl=0)
        return "READY", {"warehouse_id": settings.warehouse_id, "connectivity": "SQL_OK"}

    def genie():
        client = workspace_client()
        spaces = []
        for key, item in settings.genie_spaces.items():
            if not item.get("id"):
                spaces.append({"space": key, "status": "NOT_CONFIGURED"})
                continue
            client.api_client.do("GET", f"/api/2.0/genie/spaces/{item['id']}")
            spaces.append({"space": key, "status": "READY", "space_id": item["id"]})
        status = "READY" if spaces and all(item["status"] == "READY" for item in spaces) else "NOT_CONFIGURED"
        return status, {"spaces": spaces}

    def ai_gateway():
        if not settings.ai_model or not settings.ai_url:
            return "NOT_CONFIGURED", {"reason": "AI model or gateway URL is missing"}
        return "READY", {
            "model": settings.ai_model,
            "gateway": settings.ai_url,
            "validation_mode": "CONFIGURATION_ONLY",
        }

    def lakebase():
        retention_status = retention_case_store.schema_status()
        campaign_status = campaign_store.schema_status()
        retention_ready = all(
            retention_status.get(key) for key in ("cases_ready", "events_ready", "migration_ready")
        )
        campaign_ready = all(
            campaign_status.get(key)
            for key in ("drafts_ready", "versions_ready", "events_ready", "migration_ready")
        )
        return ("READY" if retention_ready and campaign_ready else "DEGRADED"), {
            "project": conversation_store.project,
            "database": conversation_store.database,
            "connectivity": "POSTGRES_OK",
            "operational_retention_schema": retention_status,
            "operational_campaign_schema": campaign_status,
        }

    def managed_memory():
        if not managed_agent_memory.enabled:
            return "NOT_CONFIGURED", {"reason": "Managed Agent Memory store is not configured"}
        workspace_client().api_client.do("GET", f"/api/2.1/unity-catalog/memory-stores/{managed_agent_memory.store_name}")
        return "READY", {"store": managed_agent_memory.store_name, "probe": "METADATA_ONLY"}

    def dashboard():
        if not settings.dashboard_id:
            return "NOT_CONFIGURED", {"reason": "Dashboard ID is missing"}
        workspace_client().api_client.do("GET", f"/api/2.0/lakeview/dashboards/{settings.dashboard_id}")
        return "READY", {"dashboard_id": settings.dashboard_id, "probe": "METADATA_ONLY"}

    def rbac():
        if not access.get("roles"):
            return "FAILED", {"actor": access.get("actor"), "reason": "No active operational role"}
        return "READY", {"actor": access.get("actor"), "roles": access["roles"], "country_scope": access.get("countries") or ["ALL"]}

    def graph_snapshot():
        snapshot = _graph_snapshot()
        if _graph_snapshot_succeeded(snapshot, None):
            return "READY", {"latest_snapshot": snapshot, "source": "RUN_LOG", "policy_status": "CURRENT"}
        # Snapshots created before the audited run log remain valid demo data.
        # Detect the governed published view without starting the manual job.
        published = run_sql(
            """SELECT graph_model_version AS model_version, MAX(graph_scored_at) AS computed_at,
                      COUNT(*) AS customers
               FROM ops_customer_graph_360
               GROUP BY graph_model_version
               ORDER BY computed_at DESC LIMIT 1""",
            cache_ttl=0,
        )
        if not published:
            return "NOT_CONFIGURED", {"reason": "No published Graph Intelligence snapshot"}
        snapshot = published[0]
        qualified = snapshot.get("model_version") in {
            "graph-fusion-v2-qualified", "graph-intelligence-v3-ontobricks",
        }
        return ("DEGRADED" if not qualified else "READY"), {
            "latest_snapshot": snapshot,
            "source": "PUBLISHED_VIEW",
            "policy_status": "CURRENT" if qualified else "LEGACY_PENDING_MANUAL_REFRESH",
        }

    def ontobricks():
        contract = {
            "contract": "gold_quetzal_knowledge_graph_triples",
            "domain": settings.ontobricks_domain,
            "version": settings.ontobricks_version,
            "external_app_configured": bool(settings.ontobricks_url),
        }
        try:
            rows = run_sql(
                """SELECT count(*) AS triples, count(DISTINCT subject) AS subjects,
                          count(DISTINCT predicate) AS predicates,
                          max(generated_at) AS generated_at
                   FROM gold_quetzal_knowledge_graph_triples""",
                cache_ttl=0,
            )
        except SqlExecutionError:
            return "NOT_CONFIGURED", {
                **contract,
                "reason": "Compatible export will be published by the next manual graph refresh",
            }
        snapshot = rows[0] if rows else {}
        contract["snapshot"] = snapshot
        if not settings.ontobricks_url:
            return "DEGRADED", {**contract, "reason": "OntoBricks runtime URL is not configured"}
        session = requests.Session()
        session.headers.update(auth_headers())

        def read(path: str, *, params: dict | None = None) -> dict:
            response = session.get(f"{settings.ontobricks_url}{path}", params=params, timeout=12)
            response.raise_for_status()
            return response.json()

        health = read("/api/v1/health")
        domains = read("/api/v1/domains")
        domain = next(
            (item for item in domains.get("domains", []) if item.get("name") == settings.ontobricks_domain),
            None,
        )
        if not domain:
            return "DEGRADED", {**contract, "runtime": health, "reason": "Published domain not found"}
        versions = read("/api/v1/domain/versions", params={"domain_name": settings.ontobricks_domain})
        graph = read("/api/v1/digitaltwin/status", params={"domain_name": settings.ontobricks_domain})
        graphql = read(f"/api/v1/graphql/{settings.ontobricks_domain}/schema")
        ready = (
            health.get("status") == "healthy"
            and bool(domain.get("has_graph"))
            and bool(graph.get("has_data"))
            and int(graph.get("count") or 0) > 0
            and bool(graphql.get("ready"))
            and int(snapshot.get("triples") or 0) > 0
        )
        return ("READY" if ready else "DEGRADED"), {
            **contract,
            "runtime": health,
            "published_domain": domain,
            "versions": versions.get("versions", []),
            "graph": graph,
            "graphql": {"ready": graphql.get("ready"), "reason": graphql.get("reason")},
        }

    return [
        _check_result("warehouse", warehouse),
        _check_result("genie", genie),
        _check_result("ai_gateway", ai_gateway),
        _check_result("lakebase", lakebase),
        _check_result("managed_memory", managed_memory),
        _check_result("dashboard", dashboard),
        _check_result("rbac", rbac),
        _check_result("graph_snapshot", graph_snapshot),
        _check_result("ontobricks", ontobricks),
    ]


@router.get("/me")
def current_operator(request: Request):
    access = _access(request)
    actor = access["actor"]
    return {
        "email": actor,
        "display_name": actor.split("@")[0].replace(".", " ").title(),
        "roles": access["roles"],
        "country_scope": access["countries"] or (["ALL"] if access["roles"] else []),
        "identity_source": access["identity_source"],
        "execution_identity": access["execution_identity"],
    }


@router.get("/demo/preflight")
def demo_preflight(request: Request):
    """Run manual, read-only readiness checks without AI inference or job execution."""
    access = _require_role(request, "NOC_OPERATOR", "CARE_AGENT", "EXECUTIVE_VIEWER")
    checks = _preflight_checks(access)
    statuses = {item["status"] for item in checks}
    if "FAILED" in statuses:
        overall = "FAILED"
    elif statuses.intersection({"DEGRADED", "NOT_CONFIGURED"}):
        overall = "DEGRADED"
    else:
        overall = "READY"
    return {
        "status": overall,
        "checks": checks,
        "paid_inference_used": False,
        "job_triggered": False,
        "execution_mode": "MANUAL_READ_ONLY",
        "generated_at": datetime.now(UTC).isoformat(),
    }


@router.get("/demo/journey")
def demo_journey(
    request: Request,
    country: str = Query(default="ALL", pattern=r"^(ALL|PA|MX|CO|BR|AR|CL|PE|EC|CR|GT|DO|UY)$"),
):
    """Select a deterministic, real-data incident-to-customer demo path."""
    access = _require_role(request, "NOC_OPERATOR", "CARE_AGENT", "EXECUTIVE_VIEWER")
    if country != "ALL":
        _assert_country_access(access, country)
    clauses = ["COALESCE(s.status, 'NEW') <> 'RESOLVED'"]
    parameters: dict[str, str] = {}
    if country != "ALL":
        clauses.append("c.country = :country")
        parameters["country"] = country
    elif access["countries"]:
        clauses.append("array_contains(split(:country_scope, ','), c.country)")
        parameters["country_scope"] = ",".join(access["countries"])
    incidents = run_sql(
        _incident_select(" AND ".join(clauses))
        + " ORDER BY priority_score DESC, c.revenue_at_risk DESC, c.detected_at DESC, c.incident_id LIMIT 1",
        parameters=parameters,
        cache_ttl=0,
    )
    if not incidents:
        return {
            "available": False,
            "reason": "NO_UNRESOLVED_INCIDENT_IN_SCOPE",
            "scope": {"requested_country": country, "authorized_countries": access["countries"] or ["ALL"]},
            "steps": [],
            "generated_at": datetime.now(UTC).isoformat(),
        }
    incident = incidents[0]
    market = str(incident.get("country"))
    customer_parameters = {"country": market}
    try:
        customers = run_sql(
            """
            SELECT cliente_id AS customer_id, nombre_completo AS customer_name,
                   pais_codigo AS country, segmento_nombre AS segment,
                   COALESCE(graph_churn_probability, churn_probability) AS churn_probability,
                   churn_probability AS baseline_churn_probability, graph_churn_probability,
                   graph_lift, graph_risk_tier, influence_score, contagion_risk_score,
                   graph_community_id AS community_id,
                   monthly_revenue, revenue_lifetime_est, nps_ultimo AS nps,
                   open_tickets, overdue_balance, graph_recommended_action,
                   graph_explanation_codes
            FROM ops_customer_graph_360
            WHERE pais_codigo = :country AND graph_community_id IS NOT NULL
            ORDER BY COALESCE(graph_churn_probability, churn_probability) DESC,
                     monthly_revenue DESC, open_tickets DESC, cliente_id
            LIMIT 1
            """,
            parameters=customer_parameters,
            cache_ttl=0,
        )
    except SqlExecutionError:
        customers = []
    if not customers:
        customers = run_sql(
            """
            SELECT cliente_id AS customer_id, nombre_completo AS customer_name,
                   pais_codigo AS country, segmento_nombre AS segment,
                   churn_probability, churn_probability AS baseline_churn_probability,
                   monthly_revenue, revenue_lifetime_est, nps_ultimo AS nps,
                   open_tickets, overdue_balance
            FROM ops_customer_360
            WHERE pais_codigo = :country
            ORDER BY churn_probability DESC, monthly_revenue DESC, open_tickets DESC, cliente_id
            LIMIT 1
            """,
            parameters=customer_parameters,
            cache_ttl=0,
        )
    customer = customers[0] if customers else None
    return {
        "available": customer is not None,
        "scope": {
            "requested_country": country,
            "selected_country": market,
            "authorized_countries": access["countries"] or ["ALL"],
        },
        "incident": incident,
        "customer": customer,
        "relationship_semantics": {
            "association_type": "SAME_MARKET_EXAMPLE",
            "direct_customer_attribution": False,
            "statement": "El cliente se selecciona como ejemplo prioritario del mismo país; no existe vínculo cliente-torre en las fuentes disponibles.",
        },
        "steps": [
            {"order": 1, "id": "PREFLIGHT", "title": "Validar dependencias", "endpoint": "/api/demo/preflight"},
            {"order": 2, "id": "INCIDENT", "title": "Entender el incidente prioritario", "resource_id": incident.get("incident_id")},
            {"order": 3, "id": "VOICE_OF_CUSTOMER", "title": "Escuchar temas y señales del mercado", "endpoint": f"/api/voc/overview?country={market}"},
            {"order": 4, "id": "CUSTOMER_360", "title": "Explorar el cliente prioritario del mercado", "resource_id": customer.get("customer_id") if customer else None},
            {"order": 5, "id": "RECOMMENDATION", "title": "Revisar evidencia y próxima mejor acción", "requires_human_approval": True},
            {"order": 6, "id": "CAMPAIGN_OPTIMIZER", "title": "Preparar una audiencia gobernada", "endpoint": "/api/campaigns/optimize", "requires_human_approval": True},
            {"order": 7, "id": "FINANCIAL_IMPACT", "title": "Simular impacto contrafactual", "endpoint": "/api/demo/financial-impact"},
        ],
        "generated_at": datetime.now(UTC).isoformat(),
    }


@router.get("/demo/manifest")
def certified_demo_manifest(
    request: Request,
    country: str = Query(default="ALL", pattern=r"^(ALL|PA|MX|CO|BR|AR|CL|PE|EC|CR|GT|DO|UY)$"),
):
    """Resolve a certified, deterministic and entirely read-only demo scenario."""
    access = _require_role(request, "NOC_OPERATOR", "CARE_AGENT", "EXECUTIVE_VIEWER")
    if country != "ALL":
        _assert_country_access(access, country)
    journey = demo_journey(request, country)
    preflight = demo_preflight(request)
    if not journey.get("available"):
        return {
            "available": False,
            "certification": "CERTIFIED_DEMO_MANIFEST_V1",
            "reason": journey.get("reason") or "NO_CERTIFIED_SCENARIO_IN_SCOPE",
            "scope": journey.get("scope") or {
                "requested_country": country,
                "authorized_countries": access["countries"] or ["ALL"],
            },
            "preflight": preflight,
            "steps": [],
            "safety": {
                "read_only": True, "backend_mutations": False,
                "paid_inference_used": False, "job_triggered": False,
                "campaign_sent": False, "human_approval_required": True,
            },
            "generated_at": datetime.now(UTC).isoformat(),
        }
    incident = journey.get("incident") or {}
    customer = journey.get("customer") or {}
    customer_id = str(customer.get("customer_id") or "")
    market = str(journey.get("scope", {}).get("selected_country") or incident.get("country") or "")
    evidence_warnings: list[str] = []
    try:
        graph_rows = run_sql(
            """SELECT f.customer_id, f.community_id, p.model_version,
                      f.run_id, f.computed_at, f.reach_score,
                      f.network_exposure_score, p.retention_priority_score
               FROM gold_customer_graph_features f
               LEFT JOIN gold_churn_graph_predictions p
                 USING (customer_id, community_id)
               WHERE f.customer_id = :customer_id
               ORDER BY f.computed_at DESC LIMIT 1""",
            parameters={"customer_id": customer_id}, cache_ttl=0,
        )
    except SqlExecutionError:
        graph_rows = []
        evidence_warnings.append("GRAPH_EVIDENCE_UNAVAILABLE")
    if not graph_rows and "GRAPH_EVIDENCE_UNAVAILABLE" not in evidence_warnings:
        evidence_warnings.append("GRAPH_EVIDENCE_UNAVAILABLE")
    graph = graph_rows[0] if graph_rows else {}
    try:
        offer_rows = run_sql(
            """SELECT plan_id, product_name, recommendation_type, recommendation_score,
                      reason, marketing_eligible
               FROM ops_customer_next_best_offer
               WHERE cliente_id = :customer_id
               ORDER BY CASE WHEN marketing_eligible THEN 0 ELSE 1 END,
                        recommendation_score DESC, plan_id LIMIT 1""",
            parameters={"customer_id": customer_id}, cache_ttl=0,
        )
    except SqlExecutionError:
        offer_rows = []
        evidence_warnings.append("OFFER_EVIDENCE_UNAVAILABLE")
    offer = offer_rows[0] if offer_rows else {}
    try:
        scoring_rows = run_sql(
            """SELECT model_name, model_version, model_run_id, scored_at
               FROM gold_churn_predictions
               WHERE cliente_id = :customer_id
               ORDER BY scored_at DESC LIMIT 1""",
            parameters={"customer_id": customer_id}, cache_ttl=0,
        )
    except SqlExecutionError:
        scoring_rows = []
        evidence_warnings.append("CHURN_EVIDENCE_UNAVAILABLE")
    scoring = scoring_rows[0] if scoring_rows else {}
    try:
        voc = voice_of_customer_overview(request, market, 90, 1)
    except SqlExecutionError:
        voc = {"themes": [], "summary": None, "methodology": {}}
        evidence_warnings.append("VOC_EVIDENCE_UNAVAILABLE")
    theme = (voc.get("themes") or [{}])[0]
    scenario_material = "|".join([
        market, str(incident.get("incident_id") or ""), customer_id,
        str(graph.get("community_id") or ""), str(graph.get("run_id") or ""),
        str(theme.get("theme_id") or "OTHER"),
    ])
    manifest_id = "QDM-" + hashlib.sha256(scenario_material.encode()).hexdigest()[:12].upper()
    context = {
        "country": market,
        "incident_id": incident.get("incident_id"),
        "community_id": graph.get("community_id"),
        "customer_id": customer_id,
        "voc_theme_id": theme.get("theme_id") or "OTHER",
        "voc_theme_label": theme.get("label") or VOC_THEME_LABELS["OTHER"],
        "offer_plan_id": offer.get("plan_id"),
        "offer_product_name": offer.get("product_name"),
        "campaign_objective": (
            "CROSS_SELL" if str(theme.get("theme_id") or "") in {"PLAN_VALUE", "OTHER"}
            else "RETENTION"
        ),
        "iq_prompt": (
            f"Explica el contexto conectado del cliente {customer_id}, su grupo "
            f"{graph.get('community_id') or 'sin grupo'}, SLA y recomendación. "
            "Separa churn individual, alcance y exposición relacional y cita OntoBricks."
        ),
    }
    steps = [
        {"id": "PREFLIGHT", "order": 1, "title": "Validar la demo", "page": "journey", "context": {}},
        {"id": "INCIDENT", "order": 2, "title": "Entender el incidente", "page": "incidents", "context": {"incident_id": context["incident_id"]}},
        {"id": "GRAPH", "order": 3, "title": "Explorar el grupo", "page": "graph", "context": {"community_id": context["community_id"], "country": market}},
        {"id": "CUSTOMER_360", "order": 4, "title": "Abrir Cliente 360", "page": "customer360", "context": {"customer_id": customer_id}},
        {"id": "QUETZAL_IQ", "order": 5, "title": "Investigar con Quetzal IQ", "page": "intelligence", "context": {"prompt": context["iq_prompt"]}},
        {"id": "VOICE_OF_CUSTOMER", "order": 6, "title": "Escuchar la voz del mercado", "page": "voice", "context": {"country": market, "theme_id": context["voc_theme_id"]}},
        {"id": "CAMPAIGN_OPTIMIZER", "order": 7, "title": "Preparar una campaña", "page": "campaigns", "context": {"country": market, "theme_id": context["voc_theme_id"], "objective": context["campaign_objective"]}},
        {"id": "ECONOMIC_JOURNEY", "order": 8, "title": "Cerrar el caso económico", "page": "journey", "context": {"country": market, "theme_id": context["voc_theme_id"], "objective": context["campaign_objective"]}},
    ]
    return {
        "available": True,
        "certification": "CERTIFIED_DEMO_MANIFEST_V1",
        "manifest_id": manifest_id,
        "scenario": {
            "title": f"Recuperación y retención conectada · {market}",
            "description": "Escenario telecom determinístico resuelto sobre el último snapshot publicado y el alcance autenticado.",
            "synthetic_data": True,
            "context": context,
            "incident": incident,
            "customer": customer,
            "graph": graph,
            "voice_of_customer": {
                "theme": theme,
                "summary": voc.get("summary"),
                "methodology": voc.get("methodology"),
            },
            "offer": offer,
        },
        "scope": {
            **(journey.get("scope") or {}),
            "effective_countries": _effective_countries(market, access),
        },
        "steps": steps,
        "preflight": preflight,
        "evidence": {
            "app_version": "3.0.0",
            "scenario_resolution": "DETERMINISTIC_SORT_V1",
            "churn_model": scoring,
            "graph_snapshot": {
                "model_version": graph.get("model_version"), "run_id": graph.get("run_id"),
                "computed_at": graph.get("computed_at"),
            },
            "ontobricks": {
                "domain": settings.ontobricks_domain,
                "version": settings.ontobricks_version,
                "source": "gold_quetzal_knowledge_graph_triples",
                "mcp_configured": bool(settings.ontobricks_mcp_url),
            },
            "voc_version": (voc.get("methodology") or {}).get("theme_mapping_version"),
            "campaign_version": "campaign-rules-v1",
            "warnings": evidence_warnings,
            "complete": not evidence_warnings,
            "sources": [
                "ops_incident_candidates", "ops_customer_graph_360",
                "gold_customer_graph_features", "gold_churn_predictions",
                "silver_tickets", "silver_nps", "ops_customer_next_best_offer",
            ],
        },
        "safety": {
            "read_only": True,
            "backend_mutations": False,
            "paid_inference_used": False,
            "job_triggered": False,
            "campaign_sent": False,
            "human_approval_required": True,
            "manual_only_jobs": ["Graph Intelligence", "OntoBricks build", "Lakeflow", "ML refresh"],
            "cost": {
                "mode": "READ_ONLY_EXISTING_SERVICES",
                "billable_surfaces": ["SQL Warehouse queries", "App compute", "metadata APIs"],
                "excluded": ["model inference", "Genie query", "job execution", "campaign connector"],
                "statement": "El manifiesto no monetiza el costo: consume únicamente lecturas sobre servicios ya configurados.",
            },
        },
        "generated_at": datetime.now(UTC).isoformat(),
    }


@router.post("/demo/financial-impact")
def financial_impact(payload: FinancialImpactRequest, request: Request):
    """Estimate retention economics from explicit, reversible assumptions."""
    access = _require_role(request, "NOC_OPERATOR", "CARE_AGENT", "EXECUTIVE_VIEWER")
    if payload.country != "ALL":
        _assert_country_access(access, payload.country)
    clauses = ["upper(estado) IN ('ACTIVO','ACTIVA','ACTIVE')"]
    parameters: dict[str, str] = {}
    if payload.country != "ALL":
        clauses.append("pais_codigo = :country")
        parameters["country"] = payload.country
    elif access["countries"]:
        clauses.append("array_contains(split(:country_scope, ','), pais_codigo)")
        parameters["country_scope"] = ",".join(access["countries"])
    where = " AND ".join(clauses)
    try:
        rows = run_sql(
            f"""
            SELECT COUNT(*) AS eligible_customers,
                   AVG(COALESCE(graph_churn_probability, churn_probability)) AS avg_churn_probability,
                   AVG(monthly_revenue) AS avg_monthly_revenue_usd,
                   AVG(revenue_lifetime_est) AS avg_lifetime_value_usd,
                   MAX(graph_scored_at) AS score_as_of
            FROM ops_customer_graph_360 WHERE {where}
            """,
            parameters=parameters,
            cache_ttl=0,
        )
        score_source = "GRAPH_ENRICHED_WHEN_AVAILABLE"
    except SqlExecutionError:
        rows = run_sql(
            f"""
            SELECT COUNT(*) AS eligible_customers,
                   AVG(churn_probability) AS avg_churn_probability,
                   AVG(monthly_revenue) AS avg_monthly_revenue_usd,
                   AVG(revenue_lifetime_est) AS avg_lifetime_value_usd,
                   MAX(churn_scored_at) AS score_as_of
            FROM ops_customer_360 WHERE {where}
            """,
            parameters=parameters,
            cache_ttl=0,
        )
        score_source = "INDIVIDUAL_BASELINE"
    baseline = rows[0] if rows else {}
    eligible = int(_number(baseline.get("eligible_customers")))
    if eligible <= 0:
        raise HTTPException(404, "No hay clientes elegibles en el alcance solicitado.")
    treated = min(payload.treated_customers, eligible)
    churn = max(0.0, min(1.0, _number(baseline.get("avg_churn_probability"))))
    monthly_revenue = max(0.0, _number(baseline.get("avg_monthly_revenue_usd")))

    def projection(reduction_pct: float) -> dict:
        expected_churners = treated * churn
        avoided_churners = expected_churners * reduction_pct / 100
        retained_revenue = avoided_churners * monthly_revenue * payload.horizon_months
        contact_cost = treated * payload.cost_per_contact_usd
        net_impact = retained_revenue - contact_cost
        return {
            "relative_churn_reduction_pct": round(reduction_pct, 2),
            "expected_churners_before_treatment": round(expected_churners, 2),
            "estimated_avoided_churners": round(avoided_churners, 2),
            "estimated_retained_revenue_usd": round(retained_revenue, 2),
            "estimated_contact_cost_usd": round(contact_cost, 2),
            "estimated_net_impact_usd": round(net_impact, 2),
            "estimated_roi_pct": round(100 * net_impact / contact_cost, 1) if contact_cost else None,
        }

    base_result = projection(payload.relative_churn_reduction_pct)
    return {
        "estimate_type": "COUNTERFACTUAL_ESTIMATE",
        "scope": {
            "requested_country": payload.country,
            "authorized_countries": access["countries"] or ["ALL"],
            "eligible_customers": eligible,
            "treated_customers": treated,
        },
        "assumptions": payload.model_dump(),
        "baseline": {
            "avg_churn_probability": round(churn, 4),
            "avg_monthly_revenue_usd": round(monthly_revenue, 2),
            "avg_lifetime_value_usd": round(_number(baseline.get("avg_lifetime_value_usd")), 2),
            "score_as_of": baseline.get("score_as_of"),
            "score_source": score_source,
        },
        "formulas": {
            "avoided_churners": "treated_customers × avg_churn_probability × relative_churn_reduction_pct",
            "retained_revenue": "avoided_churners × avg_monthly_revenue × horizon_months",
            "net_impact": "retained_revenue − treated_customers × cost_per_contact",
        },
        "result": base_result,
        "sensitivity": {
            "conservative": projection(payload.relative_churn_reduction_pct * 0.75),
            "base": base_result,
            "optimistic": projection(min(100, payload.relative_churn_reduction_pct * 1.25)),
        },
        "disclaimer": "Estimación contrafactual para planificación. No es una previsión causal, compromiso financiero ni resultado observado.",
        "generated_at": datetime.now(UTC).isoformat(),
    }


@router.get("/voc/overview")
def voice_of_customer_overview(
    request: Request,
    country: str = Query(default="ALL", pattern=r"^(ALL|PA|MX|CO|BR|AR|CL|PE|EC|CR|GT|DO|UY)$"),
    window_days: int = Query(default=90, ge=7, le=365),
    max_themes: int = Query(default=8, ge=1, le=8),
):
    """Derive synthetic customer themes from governed operational evidence."""
    access = _require_role(request, "CARE_AGENT", "NOC_OPERATOR", "EXECUTIVE_VIEWER")
    scope_filter, scope_params = _country_scope(country, access, "c.pais_codigo")
    parameters: dict[str, str | int] = {**scope_params, "window_days": window_days}
    theme_case = _ticket_theme_case("t")
    summary_rows = run_sql(
        f"""
        WITH scoped_customers AS (
          SELECT c.* FROM ops_customer_360 c WHERE {scope_filter}
        ), ticket_anchor AS (
          SELECT max(t.fecha_creacion) AS as_of
          FROM silver_tickets t JOIN scoped_customers c ON t.cliente_id = c.cliente_id
        ), ticket_window AS (
          SELECT t.*, c.segmento_id, sla.resolution_target_hours, a.as_of,
                 CASE WHEN upper(t.estado) NOT IN ('CERRADO','CLOSED','RESUELTO','RESOLVED') THEN true ELSE false END AS is_open,
                 CASE WHEN t.tiempo_resolucion_horas IS NOT NULL
                           AND t.tiempo_resolucion_horas > sla.resolution_target_hours THEN true
                      WHEN upper(t.estado) NOT IN ('CERRADO','CLOSED','RESUELTO','RESOLVED')
                           AND timestampdiff(HOUR, t.fecha_creacion, a.as_of) > sla.resolution_target_hours THEN true
                      ELSE false END AS is_sla_breach
          FROM silver_tickets t JOIN scoped_customers c ON t.cliente_id = c.cliente_id
          CROSS JOIN ticket_anchor a
          LEFT JOIN ops_sla_policy sla ON c.segmento_id = sla.segment_id
          WHERE t.fecha_creacion >= timestampadd(DAY, -1 * :window_days, a.as_of)
        ), nps_anchor AS (
          SELECT max(n.fecha_encuesta) AS as_of
          FROM silver_nps n JOIN scoped_customers c ON n.cliente_id = c.cliente_id
          WHERE n.respondida = true
        ), nps_window AS (
          SELECT n.* FROM silver_nps n JOIN scoped_customers c ON n.cliente_id = c.cliente_id
          CROSS JOIN nps_anchor a
          WHERE n.respondida = true
            AND n.fecha_encuesta >= timestampadd(DAY, -1 * :window_days, a.as_of)
        )
        SELECT (SELECT count(*) FROM scoped_customers) AS customers_observed,
               (SELECT count(*) FROM ticket_window) AS tickets,
               (SELECT count(*) FROM ticket_window WHERE is_open) AS open_tickets,
               (SELECT count(*) FROM ticket_window WHERE is_sla_breach) AS sla_breaches,
               (SELECT round(avg(csat_score), 2) FROM ticket_window WHERE csat_score IS NOT NULL) AS avg_csat,
               (SELECT count(*) FROM nps_window) AS nps_responses,
               (SELECT count(*) FROM nps_window WHERE score <= 6) AS detractors,
               (SELECT round(avg(score), 2) FROM nps_window) AS avg_nps,
               (SELECT count(*) FROM scoped_customers WHERE churn_probability >= 0.65) AS high_churn_customers,
               (SELECT as_of FROM ticket_anchor) AS tickets_as_of,
               (SELECT as_of FROM nps_anchor) AS nps_as_of,
               (SELECT max(churn_scored_at) FROM scoped_customers) AS customer_360_as_of
        """,
        parameters=parameters,
        cache_ttl=15,
    )
    summary_row = summary_rows[0] if summary_rows else {}
    theme_rows = run_sql(
        f"""
        WITH scoped_customers AS (
          SELECT c.* FROM ops_customer_360 c WHERE {scope_filter}
        ), anchor AS (
          SELECT max(t.fecha_creacion) AS as_of
          FROM silver_tickets t JOIN scoped_customers c ON t.cliente_id = c.cliente_id
        ), classified AS (
          SELECT t.*, c.nps_ultimo, sla.resolution_target_hours, a.as_of,
                 {theme_case} AS theme_id,
                 CASE WHEN upper(t.estado) NOT IN ('CERRADO','CLOSED','RESUELTO','RESOLVED') THEN true ELSE false END AS is_open,
                 CASE WHEN t.tiempo_resolucion_horas IS NOT NULL
                           AND t.tiempo_resolucion_horas > sla.resolution_target_hours THEN true
                      WHEN upper(t.estado) NOT IN ('CERRADO','CLOSED','RESUELTO','RESOLVED')
                           AND timestampdiff(HOUR, t.fecha_creacion, a.as_of) > sla.resolution_target_hours THEN true
                      ELSE false END AS is_sla_breach,
                 CASE WHEN lower(coalesce(t.prioridad, '')) RLIKE 'alta|crítica|critica|high|critical'
                           OR coalesce(t.csat_score, 5) <= 3 THEN true ELSE false END AS is_negative
          FROM silver_tickets t JOIN scoped_customers c ON t.cliente_id = c.cliente_id
          CROSS JOIN anchor a
          LEFT JOIN ops_sla_policy sla ON c.segmento_id = sla.segment_id
          WHERE t.fecha_creacion >= timestampadd(DAY, -2 * :window_days, a.as_of)
        )
        SELECT theme_id,
               sum(CASE WHEN fecha_creacion >= timestampadd(DAY, -1 * :window_days, as_of) THEN 1 ELSE 0 END) AS mentions,
               sum(CASE WHEN fecha_creacion < timestampadd(DAY, -1 * :window_days, as_of) THEN 1 ELSE 0 END) AS previous_mentions,
               sum(CASE WHEN fecha_creacion >= timestampadd(DAY, -1 * :window_days, as_of) AND is_negative THEN 1 ELSE 0 END) AS negative_signals,
               sum(CASE WHEN fecha_creacion >= timestampadd(DAY, -1 * :window_days, as_of) AND is_open THEN 1 ELSE 0 END) AS open_cases,
               sum(CASE WHEN fecha_creacion >= timestampadd(DAY, -1 * :window_days, as_of) AND is_sla_breach THEN 1 ELSE 0 END) AS sla_breaches,
               round(avg(CASE WHEN fecha_creacion >= timestampadd(DAY, -1 * :window_days, as_of) THEN nps_ultimo END), 2) AS avg_nps,
               max(fecha_creacion) AS latest_evidence_at
        FROM classified GROUP BY theme_id
        HAVING mentions > 0
        ORDER BY mentions DESC, negative_signals DESC, theme_id
        LIMIT {max_themes}
        """,
        parameters=parameters,
        cache_ttl=15,
    )
    example_rows = run_sql(
        f"""
        WITH scoped_customers AS (
          SELECT c.* FROM ops_customer_360 c WHERE {scope_filter}
        ), anchor AS (
          SELECT max(t.fecha_creacion) AS as_of
          FROM silver_tickets t JOIN scoped_customers c ON t.cliente_id = c.cliente_id
        ), ranked AS (
          SELECT {theme_case} AS theme_id, c.cliente_id AS customer_id,
                 concat(left(c.nombre_completo, 1), '•••', right(c.cliente_id, 4)) AS customer_ref,
                 c.pais_codigo AS country, c.churn_probability, c.nps_ultimo AS nps,
                 c.open_tickets, max(t.fecha_creacion) AS latest_evidence_at,
                 max(CASE WHEN lower(coalesce(t.prioridad, '')) RLIKE 'alta|crítica|critica|high|critical' THEN 1 ELSE 0 END) AS urgent
          FROM silver_tickets t JOIN scoped_customers c ON t.cliente_id = c.cliente_id
          CROSS JOIN anchor a
          WHERE t.fecha_creacion >= timestampadd(DAY, -1 * :window_days, a.as_of)
          GROUP BY {theme_case}, c.cliente_id, c.nombre_completo, c.pais_codigo,
                   c.churn_probability, c.nps_ultimo, c.open_tickets
        )
        SELECT * FROM ranked
        QUALIFY row_number() OVER (
          PARTITION BY theme_id
          ORDER BY urgent DESC, open_tickets DESC, churn_probability DESC, latest_evidence_at DESC, customer_id
        ) <= 3
        ORDER BY theme_id, urgent DESC, open_tickets DESC, churn_probability DESC, customer_id
        """,
        parameters=parameters,
        cache_ttl=15,
    )
    examples_by_theme: dict[str, list[dict]] = {}
    for row in example_rows:
        theme_id = str(row.get("theme_id") or "OTHER")
        examples_by_theme.setdefault(theme_id, []).append({
            "customer_id": row.get("customer_id"),
            "customer_ref": row.get("customer_ref"),
            "country": row.get("country"),
            "churn_probability": row.get("churn_probability"),
            "nps": row.get("nps"),
            "open_tickets": row.get("open_tickets"),
            "customer_360_path": f"/customers/{row.get('customer_id')}/360",
        })
    total_mentions = sum(int(_number(row.get("mentions"))) for row in theme_rows)
    themes = []
    for row in theme_rows:
        theme_id = str(row.get("theme_id") or "OTHER")
        mentions = int(_number(row.get("mentions")))
        previous = int(_number(row.get("previous_mentions")))
        negative = int(_number(row.get("negative_signals")))
        breaches = int(_number(row.get("sla_breaches")))
        avg_nps = row.get("avg_nps")
        share = 100 * mentions / total_mentions if total_mentions else 0
        priority = min(100, share * 0.4 + 30 * negative / max(mentions, 1) + 20 * breaches / max(mentions, 1) + (10 if _number(avg_nps, 10) <= 6 else 0))
        themes.append({
            "theme_id": theme_id,
            "label": VOC_THEME_LABELS.get(theme_id, VOC_THEME_LABELS["OTHER"]),
            "mentions": mentions,
            "share_pct": round(share, 1),
            "negative_signals": negative,
            "open_cases": int(_number(row.get("open_cases"))),
            "sla_breaches": breaches,
            "avg_nps": _number(avg_nps) if avg_nps is not None else None,
            "trend": _voc_trend(mentions, previous),
            "priority_score": round(priority, 1),
            "evidence": [
                f"{mentions} ticket(s) clasificado(s) por categoría y motivo.",
                f"{negative} señal(es) negativas y {breaches} brecha(s) de SLA.",
            ],
            "recommended_focus": VOC_RECOMMENDED_FOCUS.get(theme_id, VOC_RECOMMENDED_FOCUS["OTHER"]),
            "customer_examples": examples_by_theme.get(theme_id, [])[:3],
        })
    summary = {
        "customers_observed": int(_number(summary_row.get("customers_observed"))),
        "tickets": int(_number(summary_row.get("tickets"))),
        "open_tickets": int(_number(summary_row.get("open_tickets"))),
        "sla_breaches": int(_number(summary_row.get("sla_breaches"))),
        "nps_responses": int(_number(summary_row.get("nps_responses"))),
        "detractors": int(_number(summary_row.get("detractors"))),
        "avg_nps": _number(summary_row.get("avg_nps")) if summary_row.get("avg_nps") is not None else None,
        "avg_csat": _number(summary_row.get("avg_csat")) if summary_row.get("avg_csat") is not None else None,
    }
    signals = []
    if summary["sla_breaches"]:
        signals.append({
            "type": "SLA_PRESSURE", "severity": "HIGH", "title": "Presión sobre SLA",
            "description": "Tickets fuera del objetivo de resolución dentro de la ventana analizada.",
            "metric": "sla_breaches", "value": summary["sla_breaches"], "unit": "tickets",
        })
    detractor_pct = 100 * summary["detractors"] / summary["nps_responses"] if summary["nps_responses"] else 0
    signals.append({
        "type": "NPS_SENTIMENT", "severity": "HIGH" if detractor_pct >= 40 else "MEDIUM" if detractor_pct >= 20 else "LOW",
        "title": "Voz detractora", "description": "Participación de detractores entre respuestas NPS de la ventana.",
        "metric": "detractor_pct", "value": round(detractor_pct, 1), "unit": "percent",
    })
    if summary["open_tickets"]:
        signals.append({
            "type": "OPEN_CASES", "severity": "HIGH" if summary["open_tickets"] >= 10 else "MEDIUM",
            "title": "Casos aún abiertos", "description": "La recuperación de servicio debe preceder acciones comerciales.",
            "metric": "open_tickets", "value": summary["open_tickets"], "unit": "tickets",
        })
    return {
        "status": "READY",
        "synthetic": True,
        "scope": {
            "requested_country": country,
            "effective_countries": _effective_countries(country, access),
            "window_days": window_days,
        },
        "summary": summary,
        "themes": themes,
        "signals": signals,
        "source_coverage": [
            {"source": "silver_tickets", "rows": summary["tickets"], "as_of": summary_row.get("tickets_as_of")},
            {"source": "silver_nps", "rows": summary["nps_responses"], "as_of": summary_row.get("nps_as_of")},
            {"source": "ops_customer_360", "rows": summary["customers_observed"], "as_of": summary_row.get("customer_360_as_of")},
            {"source": "ops_sla_policy", "rows": summary["tickets"], "as_of": summary_row.get("tickets_as_of")},
        ],
        "methodology": {
            "type": "DETERMINISTIC_RULE_BASED_SYNTHESIS",
            "ai_inference_used": False,
            "synthetic_data": True,
            "theme_mapping_version": "voc-rules-v1",
        },
        "limitations": [
            "Todos los datos y ejemplos son sintéticos y sirven únicamente para demostración.",
            "Los temas se derivan de reglas sobre categoría y motivo; no son sentimiento generado por un modelo.",
            "NPS, tickets y SLA tienen cadencias distintas y no prueban causalidad.",
        ],
        "generated_at": datetime.now(UTC).isoformat(),
    }


@router.post("/campaigns/optimize")
def optimize_campaign(payload: CampaignOptimizeRequest, request: Request):
    """Create a deterministic campaign draft without writes, connectors or execution."""
    access = _require_role(request, "CARE_AGENT")
    scope_filter, scope_params = _country_scope(payload.country, access, "c.pais_codigo")
    source_theme = payload.source_theme_id or "ALL"
    parameters: dict[str, str] = {
        **scope_params,
        "channel": payload.channel,
        "objective": payload.objective,
        "source_theme": source_theme,
    }
    theme_case = _ticket_theme_case("t")
    campaign_cte = f"""
      WITH ticket_anchor AS (
        SELECT max(fecha_creacion) AS as_of FROM silver_tickets
      ), ticket_themes AS (
        SELECT t.cliente_id, collect_set({theme_case}) AS theme_ids
        FROM silver_tickets t CROSS JOIN ticket_anchor a
        WHERE t.fecha_creacion >= timestampadd(DAY, -180, a.as_of)
        GROUP BY t.cliente_id
      ), top_offer AS (
        SELECT cliente_id, plan_id, product_name, vertical, precio_usd,
               recommendation_type, recommendation_score, reason
        FROM ops_customer_next_best_offer
        WHERE marketing_eligible = true
        QUALIFY row_number() OVER (
          PARTITION BY cliente_id ORDER BY recommendation_score DESC, precio_usd, plan_id
        ) = 1
      ), base AS (
        SELECT c.cliente_id AS customer_id,
               concat(left(c.nombre_completo, 1), '•••', right(c.cliente_id, 4)) AS customer_ref,
               c.pais_codigo AS country, c.segmento_nombre AS segment,
               c.monthly_revenue, c.churn_probability, c.nps_ultimo AS nps,
               c.open_tickets, c.avg_resolution_hours, c.resolution_target_hours,
               c.overdue_balance, coalesce(c.acepta_marketing, false) AS marketing_consented,
               CASE WHEN :channel = 'EMAIL' THEN c.email IS NOT NULL AND instr(c.email, '@') > 1
                    ELSE c.telefono IS NOT NULL AND length(trim(c.telefono)) >= 6 END AS channel_reachable,
               CASE WHEN c.open_tickets = 0
                          AND (c.resolution_target_hours IS NULL OR c.avg_resolution_hours IS NULL
                               OR c.avg_resolution_hours <= c.resolution_target_hours)
                    THEN true ELSE false END AS service_eligible,
               CASE WHEN :objective = 'RETENTION' THEN c.churn_probability >= 0.50 OR c.nps_ultimo <= 6
                    ELSE c.churn_probability < 0.65 AND c.nps_ultimo > 6 AND o.plan_id IS NOT NULL END AS objective_eligible,
               CASE WHEN :source_theme = 'ALL' THEN true
                    WHEN :source_theme = 'BILLING' THEN array_contains(coalesce(tt.theme_ids, array()), 'BILLING') OR c.overdue_balance > 0
                    ELSE array_contains(coalesce(tt.theme_ids, array()), :source_theme) END AS source_theme_match,
               o.plan_id, o.product_name, o.vertical, o.precio_usd,
               o.recommendation_type, o.recommendation_score, o.reason AS offer_reason
        FROM ops_customer_360 c
        LEFT JOIN ticket_themes tt ON c.cliente_id = tt.cliente_id
        LEFT JOIN top_offer o ON c.cliente_id = o.cliente_id
        WHERE {scope_filter}
      ), eligible AS (
        SELECT *, round(
          CASE WHEN :objective = 'RETENTION'
               THEN 70 * coalesce(churn_probability, 0) + 20 * CASE WHEN nps <= 6 THEN 1 ELSE 0 END
               ELSE coalesce(recommendation_score, 0) END
          + 10 * CASE WHEN :source_theme <> 'ALL' AND source_theme_match THEN 1 ELSE 0 END
          + least(10D, coalesce(monthly_revenue, 0) / 20D), 2
        ) AS selection_score
        FROM base
      )
    """
    funnel_rows = run_sql(
        campaign_cte + """
        SELECT count(*) AS customers_in_scope,
               sum(CASE WHEN marketing_consented THEN 1 ELSE 0 END) AS marketing_consented,
               sum(CASE WHEN marketing_consented AND channel_reachable THEN 1 ELSE 0 END) AS channel_reachable,
               sum(CASE WHEN marketing_consented AND channel_reachable AND service_eligible THEN 1 ELSE 0 END) AS service_eligible,
               sum(CASE WHEN marketing_consented AND channel_reachable AND service_eligible
                              AND objective_eligible AND source_theme_match THEN 1 ELSE 0 END) AS campaign_eligible
        FROM eligible
        """,
        parameters=parameters,
        cache_ttl=0,
    )
    funnel_row = funnel_rows[0] if funnel_rows else {}
    budget_contact_capacity = int(payload.budget_usd // payload.cost_per_contact_usd)
    effective_limit = min(payload.max_customers, payload.contact_capacity, budget_contact_capacity)
    selected_rows = []
    if effective_limit > 0:
        selected_rows = run_sql(
            campaign_cte + f"""
            SELECT * FROM eligible
            WHERE marketing_consented AND channel_reachable AND service_eligible
              AND objective_eligible AND source_theme_match
            ORDER BY selection_score DESC, monthly_revenue DESC, customer_id
            LIMIT {effective_limit}
            """,
            parameters=parameters,
            cache_ttl=0,
        )
    selected_count = len(selected_rows)
    customers_in_scope = int(_number(funnel_row.get("customers_in_scope")))
    consented = int(_number(funnel_row.get("marketing_consented")))
    reachable = int(_number(funnel_row.get("channel_reachable")))
    service_eligible = int(_number(funnel_row.get("service_eligible")))
    campaign_eligible = int(_number(funnel_row.get("campaign_eligible")))
    funnel = {
        "customers_in_scope": customers_in_scope,
        "marketing_consented": consented,
        "channel_reachable": reachable,
        "service_eligible": service_eligible,
        "offer_eligible": campaign_eligible,
        "selected": selected_count,
        "excluded": {
            "no_consent": max(0, customers_in_scope - consented),
            "channel_unreachable": max(0, consented - reachable),
            "service_first": max(0, reachable - service_eligible),
            "no_offer": max(0, service_eligible - campaign_eligible),
            "budget_or_capacity": max(0, campaign_eligible - selected_count),
        },
    }
    audience_preview = []
    for row in selected_rows[:100]:
        reason_codes = ["CONSENT_VERIFIED", "CHANNEL_REACHABLE", "SERVICE_ELIGIBLE"]
        reason_codes.append("HIGH_CHURN_RISK" if payload.objective == "RETENTION" else "PRODUCT_AFFINITY")
        if payload.source_theme_id:
            reason_codes.append("VOC_THEME_MATCH")
        audience_preview.append({
            "customer_id": row.get("customer_id"),
            "customer_ref": row.get("customer_ref"),
            "country": row.get("country"),
            "segment": row.get("segment"),
            "channel": payload.channel,
            "score": _number(row.get("selection_score")),
            "reason_codes": reason_codes,
            "monthly_revenue": _number(row.get("monthly_revenue")),
            "churn_probability": _number(row.get("churn_probability")),
            "offer": {
                "plan_id": row.get("plan_id"),
                "product_name": row.get("product_name"),
                "price_usd": _number(row.get("precio_usd")),
            } if row.get("plan_id") else None,
            "estimated_contact_cost_usd": payload.cost_per_contact_usd,
        })
    contact_cost = selected_count * payload.cost_per_contact_usd
    audience_monthly_revenue = sum(_number(row.get("monthly_revenue")) for row in selected_rows)
    average_churn_probability = (
        sum(_number(row.get("churn_probability")) for row in selected_rows) / selected_count
        if selected_count else 0.0
    )
    potential_benefit = 0.0
    if payload.objective == "RETENTION":
        potential_benefit = sum(
            _number(row.get("monthly_revenue")) * _number(row.get("churn_probability")) * payload.horizon_months
            for row in selected_rows
        )
    else:
        potential_benefit = sum(
            _number(row.get("precio_usd")) * payload.horizon_months for row in selected_rows
        )
    base_projection = _campaign_projection(
        potential_benefit_usd=potential_benefit,
        contact_cost_usd=contact_cost,
        response_rate_pct=payload.expected_response_rate_pct,
        objective=payload.objective,
    )
    base_projection["estimated_conversions"] = round(
        selected_count * payload.expected_response_rate_pct / 100, 2,
    )
    break_even_rate = 100 * contact_cost / potential_benefit if potential_benefit > 0 else None
    break_even_reachable = break_even_rate is not None and break_even_rate <= 100
    audience_ids = [str(row.get("customer_id") or "") for row in selected_rows]
    audience_fingerprint = hashlib.sha256("\n".join(audience_ids).encode()).hexdigest()[:16]
    draft_material = json.dumps({
        "request": payload.model_dump(),
        "customers": audience_ids,
    }, sort_keys=True, separators=(",", ":"))
    draft_id = "DRAFT-" + hashlib.sha256(draft_material.encode()).hexdigest()[:12].upper()
    sensitivity = {}
    for name, multiplier in (("conservative", 0.75), ("base", 1.0), ("optimistic", 1.25)):
        projected_rate = min(100.0, payload.expected_response_rate_pct * multiplier)
        projection = _campaign_projection(
            potential_benefit_usd=potential_benefit,
            contact_cost_usd=contact_cost,
            response_rate_pct=projected_rate,
            objective=payload.objective,
        )
        projection["estimated_conversions"] = round(selected_count * projected_rate / 100, 2)
        sensitivity[name] = projection
    return {
        "draft_id": draft_id,
        "status": "DRAFT",
        "execution": {
            "campaign_sent": False,
            "records_written": False,
            "requires_human_approval": True,
        },
        "scope": {
            "requested_country": payload.country,
            "effective_countries": _effective_countries(payload.country, access),
            "source_theme_id": payload.source_theme_id,
        },
        "constraints": {
            **payload.model_dump(),
            "budget_contact_capacity": budget_contact_capacity,
            "effective_selection_limit": effective_limit,
        },
        "funnel": funnel,
        "audience_preview": audience_preview,
        "impact": {
            "estimate_type": "COUNTERFACTUAL_ESTIMATE",
            **base_projection,
            "budget_remaining_usd": round(payload.budget_usd - contact_cost, 2),
            "break_even_response_rate_pct": round(break_even_rate, 2) if break_even_rate is not None else None,
            "break_even_reachable": break_even_reachable,
            "margin_vs_break_even_pct_points": (
                round(payload.expected_response_rate_pct - break_even_rate, 2)
                if break_even_rate is not None else None
            ),
        },
        "reconciliation": {
            "draft_id": draft_id,
            "population_source": "EXACT_SELECTED_CAMPAIGN_AUDIENCE",
            "eligible_before_caps": campaign_eligible,
            "selected_customers": selected_count,
            "audience_fingerprint": audience_fingerprint,
            "same_population_used_for_impact": True,
        },
        "intermediates": {
            "audience_monthly_revenue_usd": round(audience_monthly_revenue, 2),
            "average_churn_probability": round(average_churn_probability, 4),
            "gross_benefit_at_100_pct_response_usd": round(potential_benefit, 2),
            "contact_cost_usd": round(contact_cost, 2),
        },
        "sensitivity": sensitivity,
        "formulas": {
            "selected": "min(clientes elegibles, máximo solicitado, capacidad de contacto, floor(presupuesto / costo por contacto))",
            "contact_cost": "clientes seleccionados × costo por contacto",
            "estimated_conversions": "clientes seleccionados × tasa de respuesta esperada",
            "retained_revenue": "Σ(ingreso mensual × probabilidad de churn × horizonte) × tasa de respuesta; solo RETENTION",
            "incremental_revenue": "Σ(precio de oferta × horizonte) × tasa de respuesta; solo CROSS_SELL",
            "net_impact": "ingreso retenido + ingreso incremental − costo de contacto",
            "break_even_response_rate": "costo de contacto ÷ beneficio bruto potencial al 100%",
        },
        "methodology": {
            "type": "DETERMINISTIC_RULE_BASED_OPTIMIZER",
            "ai_inference_used": False,
            "selection_version": "campaign-rules-v1",
            "source_theme_policy": "Cuando source_theme_id está presente, solo son elegibles clientes con una señal temática gobernada correspondiente en los últimos 180 días.",
            "policies": [
                "CONSENT_REQUIRED", "CHANNEL_REACHABILITY_REQUIRED", "SERVICE_BEFORE_SALES",
                "BUDGET_CAP", "CONTACT_CAPACITY_CAP", "DETERMINISTIC_RANKING",
            ],
            "risk_contract": {
                "churn_prediction_horizon_days": 30,
                "business_value_horizon_months": payload.horizon_months,
                "interpretation": (
                    "La probabilidad de churn estima cancelación sintética en los 30 días posteriores al snapshot; "
                    "no es una tasa anual. El horizonte comercial valora los meses de ingreso que se conservarían "
                    "si el tratamiento resulta exitoso."
                ),
                "response_rate_interpretation": (
                    "Hipótesis combinada de respuesta y éxito del tratamiento; no es un efecto causal observado."
                ),
            },
            "costs_included": ["Costo por contacto × clientes seleccionados."],
            "costs_excluded": CAMPAIGN_COSTS_EXCLUDED,
        },
        "limitations": [
            "El resultado es un borrador sintético; no crea, persiste ni envía una campaña.",
            "El impacto es contrafactual y no representa causalidad ni resultado garantizado.",
            "La disponibilidad del canal se infiere por presencia de email o teléfono, no por entrega confirmada.",
            "La audiencia completa queda acotada por presupuesto y capacidad; la respuesta incluye hasta 100 ejemplos.",
            "El punto de equilibrio cubre solamente los costos incluidos; no incorpora los costos excluidos declarados.",
        ],
        "generated_at": datetime.now(UTC).isoformat(),
    }


@router.get("/campaigns/drafts")
def list_campaign_drafts(request: Request, limit: int = Query(default=12, ge=1, le=50)):
    """List persisted campaign summaries inside the authenticated territorial scope."""
    access = _require_role(request, "CARE_AGENT", "ACTION_APPROVER")
    try:
        campaigns = campaign_store.list_for_scope(tuple(access["countries"]), limit=limit)
    except Exception as exc:
        raise _campaign_store_error(exc) from exc
    return {
        "status": "READY",
        "source": "LAKEBASE",
        "country_scope": access["countries"] or ["ALL"],
        "campaigns": campaigns,
    }


@router.get("/campaigns/drafts/{campaign_id}")
def get_campaign_draft(campaign_id: str, request: Request):
    """Restore one complete governed campaign snapshot after navigation or reload."""
    access = _require_role(request, "CARE_AGENT", "ACTION_APPROVER")
    campaign_id = _validate_campaign_id(campaign_id)
    try:
        campaign = campaign_store.get_campaign(campaign_id)
        _assert_campaign_access(access, campaign)
    except HTTPException:
        raise
    except Exception as exc:
        raise _campaign_store_error(exc) from exc
    return {"status": "READY", "source": "LAKEBASE", "campaign": campaign}


@router.post("/campaigns/drafts", status_code=201)
def create_campaign_draft(
    payload: CampaignDraftCreateRequest,
    request: Request,
):
    """Recompute and persist a governed campaign without invoking delivery."""
    access = _require_role(request, "CARE_AGENT")
    idempotency_key = _idempotency_key(request)
    snapshot = optimize_campaign(payload.campaign, request)
    try:
        campaign = campaign_store.create_campaign(
            actor=access["actor"],
            title=payload.title,
            assigned_to=payload.assigned_to or access["actor"],
            campaign_request=payload.campaign.model_dump(),
            snapshot=snapshot,
            idempotency_key=idempotency_key,
        )
    except Exception as exc:
        raise _campaign_store_error(exc) from exc
    return {
        "status": "CREATED",
        "source": "LAKEBASE",
        "execution": {"campaign_sent": False, "connector_invoked": False},
        "campaign": campaign,
    }


@router.patch("/campaigns/drafts/{campaign_id}/revision")
def revise_campaign_draft(
    campaign_id: str,
    payload: CampaignDraftRevisionRequest,
    request: Request,
):
    """Persist a new immutable audience/economic version for a DRAFT campaign."""
    access = _require_role(request, "CARE_AGENT")
    campaign_id = _validate_campaign_id(campaign_id)
    try:
        current = campaign_store.get_campaign(campaign_id)
        _assert_campaign_access(access, current)
        snapshot = optimize_campaign(payload.campaign, request)
        campaign = campaign_store.revise_campaign(
            campaign_id=campaign_id,
            expected_version=payload.expected_version,
            actor=access["actor"],
            title=payload.title,
            assigned_to=payload.assigned_to,
            note=payload.note,
            campaign_request=payload.campaign.model_dump(),
            snapshot=snapshot,
            idempotency_key=_idempotency_key(request),
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise _campaign_store_error(exc) from exc
    return {
        "status": "UPDATED",
        "source": "LAKEBASE",
        "execution": {"campaign_sent": False, "connector_invoked": False},
        "campaign": campaign,
    }


@router.patch("/campaigns/drafts/{campaign_id}")
def transition_campaign_draft(
    campaign_id: str,
    payload: CampaignDraftTransitionRequest,
    request: Request,
):
    """Submit, approve, reject or cancel without ever delivering a campaign."""
    access = _require_role(
        request,
        "ACTION_APPROVER" if payload.to_status in {"APPROVED", "REJECTED"} else "CARE_AGENT",
    )
    campaign_id = _validate_campaign_id(campaign_id)
    try:
        current = campaign_store.get_campaign(campaign_id)
        _assert_campaign_access(access, current)
        campaign = campaign_store.transition_campaign(
            campaign_id=campaign_id,
            to_status=payload.to_status,
            expected_version=payload.expected_version,
            actor=access["actor"],
            note=payload.note,
            idempotency_key=_idempotency_key(request),
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise _campaign_store_error(exc) from exc
    return {
        "status": "UPDATED",
        "source": "LAKEBASE",
        "execution": {"campaign_sent": False, "connector_invoked": False},
        "campaign": campaign,
    }


@router.get("/command/summary")
def command_summary():
    access = _require_context_role("NOC_OPERATOR", "CARE_AGENT", "EXECUTIVE_VIEWER")
    country_filter, parameters = _country_scope("ALL", access, "c.country")
    incidents_future = submit_with_context(
        fanout,
        run_sql,
        _incident_select(f"COALESCE(s.status, 'NEW') <> 'RESOLVED' AND {country_filter}")
        + " ORDER BY priority_score DESC, c.revenue_at_risk DESC LIMIT 6",
        parameters=parameters,
    )
    action_future = submit_with_context(
        fanout,
        run_sql,
        f"""SELECT COUNT(*) AS pending_actions
            FROM ops_action_log a
            LEFT JOIN ops_incident_candidates c ON a.incident_id = c.incident_id
            WHERE a.status = 'PENDING_APPROVAL' AND {country_filter}""",
        parameters=parameters,
    )
    incidents = incidents_future.result()
    actions = action_future.result()
    return {
        "incidents": incidents,
        "totals": {
            "open_incidents": len(incidents),
            "critical_incidents": sum(1 for row in incidents if row.get("severity") == "CRITICAL"),
            "affected_customers": sum(int(row.get("affected_customers") or 0) for row in incidents),
            "revenue_at_risk": sum(float(row.get("revenue_at_risk") or 0) for row in incidents),
            "pending_actions": int((actions[0] if actions else {}).get("pending_actions") or 0),
        },
        "generated_at": datetime.now(UTC).isoformat(),
    }


@router.get("/incidents")
def incidents(
    request: Request,
    status: str | None = Query(default=None, pattern=r"^(NEW|ACKNOWLEDGED|IN_PROGRESS|MONITORING|RESOLVED)$"),
    severity: str | None = Query(default=None, pattern=r"^(CRITICAL|HIGH|MEDIUM|LOW)$"),
    country: str | None = Query(default=None, pattern=r"^[A-Z]{2}$"),
):
    access = _require_role(request, "CARE_AGENT", "NOC_OPERATOR", "EXECUTIVE_VIEWER")
    _assert_country_access(access, country)
    clauses = ["TRUE"]
    params: dict[str, str] = {}
    if status:
        clauses.append("COALESCE(s.status, 'NEW') = :status")
        params["status"] = status
    if severity:
        clauses.append("c.severity = :severity")
        params["severity"] = severity
    if country:
        clauses.append("c.country = :country")
        params["country"] = country
    elif access["countries"]:
        clauses.append("array_contains(split(:country_scope, ','), c.country)")
        params["country_scope"] = ",".join(access["countries"])
    return run_sql(
        _incident_select(" AND ".join(clauses))
        + " ORDER BY priority_score DESC, c.revenue_at_risk DESC, c.detected_at DESC LIMIT 100",
        parameters=params,
    )


@router.get("/customers/search")
def customer_search(
    request: Request,
    q: str = Query(min_length=2, max_length=120),
    country: str | None = Query(default=None, pattern=r"^[A-Z]{2}$"),
):
    """Search the governed customer index by ID, name, email or phone."""
    if country and country not in COUNTRIES:
        raise HTTPException(400, "País inválido.")
    access = _require_role(request, "CARE_AGENT", "NOC_OPERATOR")
    _assert_country_access(access, country)
    clauses = [(
        "(contains(lower(cliente_id), :term) OR "
        "contains(lower(nombre_completo), :term) OR "
        "contains(lower(email), :term) OR contains(lower(telefono), :term))"
    )]
    parameters = {"term": q.strip().lower()}
    if country:
        clauses.append("pais_codigo = :country")
        parameters["country"] = country
    elif access["countries"]:
        clauses.append("array_contains(split(:country_scope, ','), pais_codigo)")
        parameters["country_scope"] = ",".join(access["countries"])
    return run_sql(
        f"""
        SELECT cliente_id, nombre_completo, pais_codigo, segmento_id, marca_comercial,
               estado, nps_ultimo, ROUND(churn_probability, 3) AS churn_probability,
               active_subscriptions, monthly_revenue, open_tickets, overdue_balance
        FROM ops_customer_360
        WHERE {' AND '.join(clauses)}
        ORDER BY CASE WHEN lower(cliente_id) = :term THEN 0 ELSE 1 END,
                 churn_probability DESC, nombre_completo
        LIMIT 25
        """,
        parameters=parameters,
        cache_ttl=10,
    )


@router.get("/customers/{customer_id}/360")
def customer_360(customer_id: str, request: Request):
    """Return an individual customer profile and explainable recommendations."""
    access = _require_role(request, "CARE_AGENT", "NOC_OPERATOR")
    customer_id = _validate_customer_id(customer_id)
    params = {"customer_id": customer_id}
    profiles = _customer_profile(customer_id)
    if not profiles:
        raise HTTPException(404, "Cliente no encontrado.")
    profile = profiles[0]
    customer_country = profile.get("pais_codigo") or profile.get("country")
    _assert_country_access(access, customer_country)
    subscriptions_future = submit_with_context(
        fanout,
        run_sql,
        """
        SELECT s.suscripcion_id, s.plan_id, p.nombre AS product_name, p.vertical, p.tier,
               p.data_gb, p.internet_mbps, p.minutos, p.tv_canales, p.es_bundle,
               s.estado, s.fecha_inicio, s.fecha_fin, s.precio_mensual_usd,
               s.metodo_pago, s.auto_renovacion
        FROM silver_suscripciones s
        LEFT JOIN bronze_planes p ON s.plan_id = p.plan_id
        WHERE s.cliente_id = :customer_id
        ORDER BY CASE WHEN upper(s.estado) IN ('ACTIVA','ACTIVE') THEN 0 ELSE 1 END, s.fecha_inicio DESC
        """,
        parameters=params,
        cache_ttl=15,
    )
    tickets_future = submit_with_context(
        fanout,
        run_sql,
        """
        SELECT t.ticket_id, t.fecha_creacion, t.categoria, t.motivo, t.canal,
               t.prioridad, t.estado, t.tiempo_resolucion_horas, t.csat_score, t.recontacto,
               sla.resolution_target_hours,
               CASE
                 WHEN t.tiempo_resolucion_horas IS NOT NULL AND t.tiempo_resolucion_horas > sla.resolution_target_hours THEN 'BREACHED'
                 WHEN upper(t.estado) NOT IN ('CERRADO','CLOSED','RESUELTO','RESOLVED')
                      AND timestampdiff(HOUR, t.fecha_creacion, current_timestamp()) > sla.resolution_target_hours THEN 'BREACHED'
                 ELSE 'WITHIN_TARGET'
               END AS sla_status
        FROM silver_tickets t
        JOIN silver_clientes c ON t.cliente_id = c.cliente_id
        LEFT JOIN ops_sla_policy sla ON c.segmento_id = sla.segment_id
        WHERE t.cliente_id = :customer_id
        ORDER BY t.fecha_creacion DESC
        LIMIT 30
        """,
        parameters=params,
        cache_ttl=15,
    )
    billing_future = submit_with_context(
        fanout,
        run_sql,
        """
        SELECT factura_id, fecha_emision, fecha_vencimiento, monto_total_usd,
               estado_pago, dias_atraso, fecha_pago
        FROM silver_facturas WHERE cliente_id = :customer_id
        ORDER BY fecha_emision DESC LIMIT 18
        """,
        parameters=params,
        cache_ttl=15,
    )
    nps_future = submit_with_context(
        fanout,
        run_sql,
        """
        SELECT fecha_encuesta, score, categoria_nps, canal_encuesta
        FROM silver_nps WHERE cliente_id = :customer_id AND respondida = true
        ORDER BY fecha_encuesta DESC LIMIT 12
        """,
        parameters=params,
        cache_ttl=15,
    )
    offers_future = submit_with_context(
        fanout,
        run_sql,
        """
        SELECT * FROM ops_customer_next_best_offer
        WHERE cliente_id = :customer_id
        ORDER BY recommendation_score DESC, precio_usd
        """,
        parameters=params,
        cache_ttl=15,
    )
    recommendation_history_future = submit_with_context(
        fanout,
        run_sql,
        """SELECT * FROM ops_recommendation_log WHERE customer_id = :customer_id
           ORDER BY proposed_at DESC LIMIT 25""",
        parameters=params,
        cache_ttl=0,
    )
    geographic_incidents_future = submit_with_context(
        fanout,
        run_sql,
        _incident_select("c.country = :country")
        + " ORDER BY c.detected_at DESC, priority_score DESC LIMIT 12",
        parameters={"country": customer_country},
        cache_ttl=15,
    )
    subscriptions = subscriptions_future.result()
    tickets = tickets_future.result()
    billing = billing_future.result()
    nps = nps_future.result()
    offers = offers_future.result()
    recommendation_history = recommendation_history_future.result()
    geographic_incidents = geographic_incidents_future.result()
    try:
        retention_cases = retention_case_store.list_for_customer(customer_id)
        retention_workflow = {
            "status": "READY",
            "source": "lakebase.quetzal_app.retention_cases",
            "cases": retention_cases,
            "message": None,
        }
    except Exception as exc:  # noqa: BLE001 - SDK, OAuth and Postgres expose heterogeneous failures
        retention_cases = []
        retention_workflow = {
            "status": "DEGRADED",
            "source": "lakebase.quetzal_app.retention_cases",
            "cases": [],
            "message": (
                "El workflow operacional no está disponible. Los datos analíticos siguen visibles, "
                "pero crear o avanzar casos está bloqueado."
            ),
            "detail": f"{type(exc).__name__}: {str(exc)[:240]}",
        }
    assessed_tickets = [ticket for ticket in tickets if ticket.get("resolution_target_hours") is not None]
    breaches = sum(1 for ticket in assessed_tickets if ticket.get("sla_status") == "BREACHED")
    sla = {
        "policy_name": profile.get("sla_policy_name"),
        "first_response_target_hours": profile.get("first_response_target_hours"),
        "resolution_target_hours": profile.get("resolution_target_hours"),
        "service_target_pct": profile.get("service_target_pct"),
        "policy_source": profile.get("sla_policy_source"),
        "tickets_assessed": len(assessed_tickets),
        "tickets_breached": breaches,
        "ticket_compliance_pct": round(100 * (len(assessed_tickets) - breaches) / len(assessed_tickets), 1) if assessed_tickets else None,
        "estimated_credit_usd": round(float(profile.get("monthly_revenue") or 0) * float(profile.get("sla_breach_credit_pct") or 0) / 100 * breaches, 2),
        "contractual": bool(profile.get("sla_contractual")),
        "source": profile.get("sla_policy_source"),
        "disclaimer": "Contrato individual cuando está disponible; de lo contrario se usa la referencia gobernada del segmento.",
    }
    return {
        "profile": profile,
        "subscriptions": subscriptions,
        "tickets": tickets,
        "billing": billing,
        "nps_history": nps,
        "sla": sla,
        "product_offers": offers,
        "recommendations": _next_best_actions(profile, tickets, offers),
        "recommendation_history": recommendation_history,
        "retention_workflow": retention_workflow,
        "timeline": _customer_timeline(
            profile, subscriptions, tickets, billing, nps,
            recommendation_history, geographic_incidents, retention_cases,
        ),
        "explainability": _customer_explainability(profile),
        "network_context": {
            "association_type": "GEOGRAPHIC_CONTEXT",
            "direct_customer_attribution": False,
            "country": customer_country,
            "incidents": geographic_incidents,
            "disclaimer": "Incidentes del mismo país para contexto operativo; las fuentes no permiten atribuirlos directamente a este cliente.",
        },
        "generated_at": datetime.now(UTC).isoformat(),
    }


def _job_run_payload(run) -> dict:
    state = getattr(run, "state", None)
    lifecycle = getattr(state, "life_cycle_state", None)
    result = getattr(state, "result_state", None)
    lifecycle_value = getattr(lifecycle, "value", lifecycle)
    result_value = getattr(result, "value", result)
    return {
        "run_id": getattr(run, "run_id", None),
        "run_name": getattr(run, "run_name", None),
        "status": result_value or lifecycle_value,
        "life_cycle_state": lifecycle_value,
        "result_state": result_value,
        "state_message": getattr(state, "state_message", None),
        "start_time": getattr(run, "start_time", None),
        "end_time": getattr(run, "end_time", None),
        "run_page_url": getattr(run, "run_page_url", None),
    }


_GRAPH_SUCCESS = {"SUCCESS", "SUCCEEDED", "COMPLETED"}
_GRAPH_TERMINAL = _GRAPH_SUCCESS | {
    "FAILED", "CANCELED", "CANCELLED", "SKIPPED", "TIMEDOUT",
    "INTERNAL_ERROR", "BLOCKED", "UPSTREAM_FAILED",
}
_GRAPH_MODEL_VERSION = "graph-intelligence-v3-ontobricks"


def _graph_snapshot(workflow_run_id: int | None = None) -> dict | None:
    where = "WHERE workflow_run_id = :workflow_run_id" if workflow_run_id else ""
    parameters = {"workflow_run_id": workflow_run_id} if workflow_run_id else None
    try:
        rows = run_sql(
            f"SELECT * FROM ops_graph_run_log {where} ORDER BY started_at DESC LIMIT 1",
            parameters=parameters,
            cache_ttl=0,
        )
    except SqlExecutionError:
        return None
    return rows[0] if rows else None


def _graph_snapshot_succeeded(snapshot: dict | None, workflow_run_id: int | None) -> bool:
    if not snapshot:
        return False
    bound_run_id = int(snapshot.get("workflow_run_id") or 0)
    return (
        str(snapshot.get("status") or "").upper() in _GRAPH_SUCCESS
        and str(snapshot.get("model_version") or "") == _GRAPH_MODEL_VERSION
        and int(snapshot.get("triple_count") or 0) > 0
        and bool(snapshot.get("published_at"))
        and (not workflow_run_id or bound_run_id == workflow_run_id)
    )


def _compose_graph_run(workflow: dict | None, snapshot: dict | None) -> dict | None:
    if not workflow and not snapshot:
        return None
    unified = {**(snapshot or {}), **(workflow or {})}
    workflow_run_id = int((workflow or {}).get("run_id") or 0)
    workflow_status = str((workflow or {}).get("status") or "").upper()
    snapshot_status = str((snapshot or {}).get("status") or "").upper()
    if workflow:
        if workflow_status in _GRAPH_SUCCESS:
            if _graph_snapshot_succeeded(snapshot, workflow_run_id):
                unified["status"] = "SUCCEEDED"
                unified["publication_status"] = "PUBLISHED"
            else:
                unified["status"] = "FAILED"
                unified["publication_status"] = "FAILED"
                unified["state_message"] = (
                    "El workflow terminó, pero el snapshot v3 y sus triplas no fueron publicados."
                )
        elif workflow_status in _GRAPH_TERMINAL:
            unified["status"] = workflow_status
            unified["publication_status"] = "FAILED"
        else:
            unified["status"] = workflow_status or "RUNNING"
            unified["publication_status"] = "PENDING"
    else:
        unified["status"] = "SUCCEEDED" if _graph_snapshot_succeeded(snapshot, None) else snapshot_status or "FAILED"
        unified["publication_status"] = "PUBLISHED" if unified["status"] == "SUCCEEDED" else "FAILED"
    unified["computed_at"] = (snapshot or {}).get("published_at") or (snapshot or {}).get("completed_at")
    unified["snapshot_run_id"] = (snapshot or {}).get("run_id")
    return unified


def _graph_job_id() -> int:
    if not settings.graph_job_id or not settings.graph_job_id.isdigit():
        raise HTTPException(503, "Graph Intelligence todavía no está vinculado al App.")
    return int(settings.graph_job_id)


@router.post("/graph/runs", status_code=202)
def run_graph_intelligence(request: Request):
    """Start the DAB-managed workflow. No scheduler exists for this workload."""
    access = _require_role(request, "ADMIN")
    job_id = _graph_job_id()
    active = list(workspace_client().jobs.list_runs(job_id=job_id, active_only=True, limit=1))
    if active:
        return {"started": False, "reason": "ALREADY_RUNNING", "run": _job_run_payload(active[0]), "scheduled": False}
    response = workspace_client().jobs.run_now(job_id=job_id)
    run_id = response.response.run_id if getattr(response, "response", None) else None
    _audit("GRAPH_RUN_REQUESTED", "job", str(job_id), access["actor"], {"run_id": run_id, "scheduled": False})
    return {"started": True, "run_id": run_id, "job_id": job_id, "scheduled": False}


@router.get("/graph/runs/latest")
def latest_graph_run():
    _require_context_role("NOC_OPERATOR")
    job_id = _graph_job_id()
    runs = list(workspace_client().jobs.list_runs(job_id=job_id, limit=1))
    workflow = _job_run_payload(runs[0]) if runs else None
    workflow_run_id = int((workflow or {}).get("run_id") or 0)
    snapshot = _graph_snapshot(workflow_run_id or None)
    return {
        "job_id": job_id,
        "run": _compose_graph_run(workflow, snapshot),
        "workflow": workflow,
        "snapshot": snapshot,
        "scheduled": False,
    }


@router.get("/graph/runs/{run_id}")
def graph_run(run_id: int):
    _require_context_role("NOC_OPERATOR")
    run = workspace_client().jobs.get_run(run_id=run_id)
    workflow = _job_run_payload(run)
    snapshot = _graph_snapshot(run_id)
    return {
        "run": _compose_graph_run(workflow, snapshot),
        "workflow": workflow,
        "snapshot": snapshot,
        "scheduled": False,
    }


@router.get("/graph/methodology")
def graph_methodology():
    """Describe the active graph semantics without running any paid workload."""
    _require_unrestricted_context("NOC_OPERATOR", "CARE_AGENT", "EXECUTIVE_VIEWER")
    snapshot: dict = {}
    triples: dict = {}
    try:
        rows = run_sql(
            """SELECT model_version, max(scored_at) AS computed_at,
                      max(run_id) AS run_id, count(*) AS customers
               FROM gold_churn_graph_predictions GROUP BY model_version
               ORDER BY computed_at DESC LIMIT 1""",
            cache_ttl=15,
        )
        snapshot = rows[0] if rows else {}
    except SqlExecutionError:
        pass
    try:
        rows = run_sql(
            """SELECT count(*) AS triples, count(DISTINCT subject) AS subjects,
                      count(DISTINCT predicate) AS predicates, max(generated_at) AS generated_at
               FROM gold_quetzal_knowledge_graph_triples""",
            cache_ttl=15,
        )
        triples = rows[0] if rows else {}
    except SqlExecutionError:
        pass
    active_version = str(snapshot.get("model_version") or "not-published")
    is_v3 = active_version == "graph-intelligence-v3-ontobricks"
    return {
        "status": "ACTIVE" if is_v3 else "PENDING_MANUAL_REFRESH",
        "active_model_version": active_version,
        "target_model_version": "graph-intelligence-v3-ontobricks",
        "manual_only": True,
        "snapshot": snapshot,
        "relationship": {
            "label": "Contacto calificado",
            "criteria": ["3+ llamadas", "10+ minutos", "reciprocidad", "actividad en 60 días"],
            "weight": "45% recurrencia logarítmica + 35% duración logarítmica + 20% reciprocidad; decaimiento exponencial por recencia",
            "semantics": "Asociación observada. No implica vínculo personal, influencia causal ni contagio de churn.",
        },
        "algorithms": [
            {
                "id": "BASELINE_CHURN", "label": "Propensión individual", "algorithm": "Modelo ML gobernado existente",
                "output": "Probabilidad 0–1", "role": "Predicción individual; no es modificada por el grafo.",
            },
            {
                "id": "NETWORK_EXPOSURE", "label": "Exposición relacional", "algorithm": "Promedio ponderado de riesgo vecino",
                "output": "Score 0–100", "role": "Contexto directo por fuerza y recencia de la relación.",
            },
            {
                "id": "RISK_DIFFUSION", "label": "Difusión de exposición", "algorithm": "Personalized PageRank ponderado",
                "output": "Percentil 0–100", "role": "Proximidad estructural a clientes de alto riesgo; no es probabilidad.",
            },
            {
                "id": "NETWORK_REACH", "label": "Alcance", "algorithm": "PageRank ponderado",
                "output": "Score 0–100", "role": "Importancia para alcance y priorización; no predice churn por sí solo.",
            },
            {
                "id": "RELATIONSHIP_GROUP", "label": "Grupo de relaciones", "algorithm": "Label Propagation ponderado determinístico",
                "output": "Cohorte operacional", "role": "Agrupa clientes para descoberta e ação, sin atribuir causalidad.",
            },
            {
                "id": "RETENTION_PRIORITY", "label": "Prioridad de retención", "algorithm": "Ranking compuesto explicable",
                "output": "Score 0–100", "role": "Orden de trabajo; explícitamente no es probabilidad.",
            },
        ],
        "pagerank_decision": {
            "is_best_churn_algorithm": False,
            "decision": "PageRank se conserva únicamente para alcance. Personalized PageRank se usa para difusión de exposición.",
            "validation_required": "Comparar lift/AUC y calibración contra una cohorte con churn observado antes de afirmar mejora predictiva.",
        },
        "ontobricks": {
            "mode": "LAKEHOUSE_TRIPLE_CONTRACT",
            "version": settings.ontobricks_version,
            "domain": settings.ontobricks_domain,
            "ontology_path": "ontology/quetzal-telecom-v1.ttl",
            "triple_table": "gold_quetzal_knowledge_graph_triples",
            "external_app_url": settings.ontobricks_url or None,
            "runtime_status": (
                "READY" if settings.ontobricks_url and is_v3 and int(triples.get("triples") or 0) > 0
                else "PENDING"
            ),
            "snapshot": triples,
            "purpose": ["ontología", "navegación", "SHACL/SWRL", "GraphQL", "MCP"],
            "analytics_policy": "Quetzal calcula señales ponderadas; el analytics genérico no debe reemplazarlas porque deduplica relaciones sin peso.",
            "lineage": [
                "silver_customer_call_edges",
                "gold_customer_graph_features",
                "gold_churn_graph_predictions",
                "gold_quetzal_knowledge_graph_triples",
                "OntoBricks quetzal_telecom v1",
            ],
        },
        "limitations": [
            "Los contactos y eventos de la demo son sintéticos.",
            "No existe churn observado positivo en el snapshot actual para comparar AUC o calibración.",
            "La ejecución manual debe publicar v3 antes de que sus nuevas señales aparezcan en los perfiles.",
        ],
    }


@router.get("/customers/{customer_id}/graph")
def customer_graph(
    customer_id: str,
    request: Request,
    max_neighbors: int = Query(default=30, ge=5, le=60),
    affinity: str = Query(default="ALL", pattern=r"^(ALL|FREQUENT|HOUSEHOLD|SOCIAL|WORK|OTHER|CROSS_BORDER)$"),
):
    """Return a bounded ego network for Customer 360."""
    access = _require_role(request, "CARE_AGENT")
    customer_id = _validate_customer_id(customer_id)
    params = {"customer_id": customer_id, "affinity": affinity}
    try:
        center_rows = run_sql(
            """SELECT cliente_id AS customer_id, nombre_completo AS label, pais_codigo AS country,
                      segmento_nombre AS segment, graph_community_id AS community_id,
                      graph_risk_tier AS risk_tier, graph_churn_probability AS churn_probability,
                      influence_score, contagion_risk_score AS contagion_score,
                      graph_unique_contacts AS unique_contacts,
                      graph_countries_reached AS countries_reached,
                      graph_international_call_pct AS international_call_pct,
                      influenced_revenue_usd, graph_model_version AS model_version,
                      graph_scored_at AS computed_at
               FROM ops_customer_graph_360 WHERE cliente_id = :customer_id""",
            parameters={"customer_id": customer_id}, cache_ttl=15,
        )
    except SqlExecutionError:
        return {"available": False, "reason": "GRAPH_NOT_READY", "nodes": [], "edges": []}
    if not center_rows:
        raise HTTPException(404, "Cliente no encontrado en Graph Intelligence.")
    center = center_rows[0]
    _assert_country_access(access, center.get("country"))
    contacts = run_sql(
        f"""
        WITH related AS (
          SELECT destination_customer_id AS peer_id, 'OUT' AS direction,
                 duration_seconds, dropped, international, contact_affinity, occurred_at
          FROM silver_customer_call_edges WHERE source_customer_id = :customer_id
          UNION ALL
          SELECT source_customer_id AS peer_id, 'IN' AS direction,
                 duration_seconds, dropped, international, contact_affinity, occurred_at
          FROM silver_customer_call_edges WHERE destination_customer_id = :customer_id
        ), aggregated AS (
          SELECT peer_id, count(*) AS calls, round(sum(duration_seconds) / 60D, 1) AS minutes,
                 round(100 * avg(CASE WHEN dropped THEN 1D ELSE 0D END), 1) AS dropped_pct,
                 max(CASE WHEN international THEN 1 ELSE 0 END) = 1 AS international,
                 max(contact_affinity) AS affinity,
                 size(collect_set(direction)) = 2 AS reciprocal,
                 max(occurred_at) AS last_contact_at
          FROM related
          WHERE (:affinity = 'ALL' OR contact_affinity = :affinity)
          GROUP BY peer_id
        )
        SELECT a.*, p.nombre_completo AS label, p.pais_codigo AS country,
               p.segmento_nombre AS segment, p.graph_community_id AS community_id,
               p.graph_risk_tier AS risk_tier, p.graph_churn_probability AS churn_probability,
               p.influence_score, p.contagion_risk_score AS contagion_score
        FROM aggregated a
        JOIN ops_customer_graph_360 p ON a.peer_id = p.cliente_id
        ORDER BY a.calls DESC, a.minutes DESC
        LIMIT {max_neighbors}
        """,
        parameters=params,
        cache_ttl=15,
    )
    center.update({"x": 50.0, "y": 50.0, "is_center": True})
    model_version = str(center.get("model_version") or "graph-fusion-v1")
    center["baseline_churn_probability"] = center.get("churn_probability")
    center["reach_score"] = center.get("influence_score")
    center["network_exposure_score"] = center.get("contagion_score")
    if model_version == "graph-intelligence-v3-ontobricks":
        relationship_definition = {
            "version": "WEIGHTED_V3", "status": "ACTIVE",
            "label": "Contactos calificados y ponderados",
            "criteria": ["3+ llamadas", "10+ minutos", "o reciprocidad", "actividad en 60 días"],
            "affinity_semantics": "El peso combina recurrencia, duración, recencia y reciprocidad; no implica causalidad.",
        }
    elif model_version == "graph-fusion-v2-qualified":
        relationship_definition = {
            "version": "QUALIFIED_V2", "status": "ACTIVE",
            "label": "Relaciones calificadas",
            "criteria": ["3+ llamadas", "10+ minutos", "o reciprocidad", "actividad en 60 días"],
            "affinity_semantics": "FREQUENT indica recurrencia; no presupone vínculo personal.",
        }
    else:
        relationship_definition = {
            "version": "LEGACY_CALL_V1", "status": "PENDING_MANUAL_REFRESH",
            "label": "Snapshot anterior",
            "criteria": ["1+ llamada en 90 días"],
            "affinity_semantics": "Las afinidades personales de este snapshot son sintéticas.",
        }
    nodes = [center]
    edges = []
    total = max(1, len(contacts))
    for index, contact in enumerate(contacts):
        angle = 2 * math.pi * index / total - math.pi / 2
        radius = 28 if index % 2 == 0 else 38
        peer_id = contact.pop("peer_id")
        reach_score = contact.pop("influence_score")
        exposure_score = contact.pop("contagion_score")
        node = {
            "customer_id": peer_id,
            "label": contact.pop("label"),
            "country": contact.pop("country"),
            "segment": contact.pop("segment"),
            "community_id": contact.pop("community_id"),
            "risk_tier": contact.pop("risk_tier"),
            "churn_probability": contact.pop("churn_probability"),
            "influence_score": reach_score,
            "contagion_score": exposure_score,
            "reach_score": reach_score,
            "network_exposure_score": exposure_score,
            "x": round(50 + radius * math.cos(angle), 2),
            "y": round(50 + radius * math.sin(angle), 2),
            "is_center": False,
        }
        nodes.append(node)
        edges.append({"source": customer_id, "target": peer_id, **contact})
    return {
        "available": True,
        "run": {"computed_at": center.get("computed_at"), "window_days": 90},
        "relationship_definition": relationship_definition,
        "summary": {
            "influence_score": center.get("influence_score"),
            "contagion_score": center.get("contagion_score"),
            "reach_score": center.get("reach_score"),
            "network_exposure_score": center.get("network_exposure_score"),
            "community_id": center.get("community_id"),
            "countries_reached": center.get("countries_reached"),
            "international_call_pct": center.get("international_call_pct"),
            "influenced_revenue_usd": center.get("influenced_revenue_usd"),
        },
        "nodes": nodes,
        "edges": edges,
    }


@router.get("/graph/network")
def graph_network(
    request: Request,
    level: str = Query(default="community", pattern=r"^(community|customer)$"),
    country: str = Query(default="ALL", pattern=r"^(ALL|PA|MX|CO|BR|AR|CL|PE|EC|CR|GT|DO|UY)$"),
    community_id: str | None = Query(default=None, max_length=64, pattern=r"^COM-[a-f0-9]{10}$"),
    risk_tier: str = Query(default="ALL", pattern=r"^(ALL|CRITICAL|HIGH|MEDIUM|LOW)$"),
    limit: int = Query(default=120, ge=20, le=250),
):
    """Return bounded community or customer graph payloads for the explorer."""
    access = _require_role(request, "CARE_AGENT", "NOC_OPERATOR", "EXECUTIVE_VIEWER")
    _assert_country_access(access, None if country == "ALL" else country)
    params: dict = {"country": country, "risk_tier": risk_tier}
    scope = access["countries"]
    params["country_scope"] = ",".join(scope)
    country_filter = "(:country = 'ALL' OR f.country = :country)"
    if scope:
        country_filter += " AND array_contains(split(:country_scope, ','), f.country)"
    try:
        if level == "community":
            nodes = run_sql(
                f"""
                SELECT f.community_id AS node_id,
                       'community' AS node_type,
                       concat('Red ', mode(c.segmento_nombre), ' ', mode(f.country), ' · ',
                         count(DISTINCT f.country), ' país(es)') AS label,
                       mode(f.country) AS country,
                       concat_ws(',', sort_array(collect_set(f.country))) AS countries,
                       mode(c.segmento_nombre) AS dominant_segment,
                       count(DISTINCT f.country) AS countries_reached,
                       count(*) AS customer_count,
                       round(avg(p.graph_churn_probability), 4) AS churn_probability,
                       round(avg(p.graph_churn_probability), 4) AS avg_churn_probability,
                       CASE
                         WHEN 100D * sum(CASE WHEN p.risk_tier IN ('CRITICAL','HIGH') THEN 1 ELSE 0 END) / count(*) >= 35
                           OR 100D * sum(CASE WHEN c.open_tickets > 0 AND c.avg_resolution_hours > c.resolution_target_hours THEN 1 ELSE 0 END) / count(*) >= 20
                           THEN 'CRITICAL'
                         WHEN 100D * sum(CASE WHEN p.risk_tier IN ('CRITICAL','HIGH') THEN 1 ELSE 0 END) / count(*) >= 20
                           OR sum(c.monthly_revenue * p.graph_churn_probability) >= 1000
                           THEN 'HIGH'
                         WHEN 100D * sum(CASE WHEN p.risk_tier IN ('CRITICAL','HIGH') THEN 1 ELSE 0 END) / count(*) >= 8
                           THEN 'MEDIUM'
                         ELSE 'LOW'
                       END AS risk_tier,
                       sum(CASE WHEN p.risk_tier IN ('CRITICAL','HIGH') THEN 1 ELSE 0 END) AS high_risk_customers,
                       round(100D * sum(CASE WHEN p.risk_tier IN ('CRITICAL','HIGH') THEN 1 ELSE 0 END) / count(*), 1) AS high_risk_share_pct,
                       round(sum(c.monthly_revenue * p.graph_churn_probability), 2) AS monthly_revenue_at_risk_usd,
                       sum(CASE WHEN c.open_tickets > 0 AND c.avg_resolution_hours > c.resolution_target_hours THEN 1 ELSE 0 END) AS customers_with_sla_pressure,
                       round(avg(f.influence_score), 1) AS influence_score,
                       round(avg(f.contagion_risk_score), 1) AS contagion_score,
                       round(sum(f.influenced_revenue_usd), 2) AS influenced_revenue_usd,
                       round(15 + pmod(xxhash64(f.community_id, 92), 7000) / 100D, 2) AS x,
                       round(15 + pmod(xxhash64(f.community_id, 102), 7000) / 100D, 2) AS y
                FROM gold_customer_graph_features f
                JOIN gold_churn_graph_predictions p USING (customer_id, community_id)
                JOIN ops_customer_360 c ON f.customer_id = c.cliente_id
                WHERE {country_filter}
                  AND (:risk_tier = 'ALL' OR p.risk_tier = :risk_tier)
                GROUP BY f.community_id
                ORDER BY high_risk_customers DESC, monthly_revenue_at_risk_usd DESC, influenced_revenue_usd DESC
                LIMIT {min(limit, 120)}
                """, parameters=params, cache_ttl=15,
            )
            community_ids = [str(node["node_id"]) for node in nodes]
            if not community_ids:
                return {"available": True, "level": level, "summary": {}, "nodes": [], "edges": []}
            quoted = ",".join(f"'{value}'" for value in community_ids)
            edges = run_sql(
                f"""
                SELECT least(a.community_id, b.community_id) AS source,
                       greatest(a.community_id, b.community_id) AS target,
                       count(*) AS calls,
                       round(sum(e.duration_seconds) / 60D, 1) AS minutes,
                       round(100 * avg(CASE WHEN e.dropped THEN 1D ELSE 0D END), 1) AS dropped_pct,
                       max(CASE WHEN e.source_country_code <> e.destination_country_code THEN 1 ELSE 0 END) = 1 AS international,
                       CASE WHEN max(CASE WHEN e.source_country_code <> e.destination_country_code THEN 1 ELSE 0 END) = 1
                            THEN 'CROSS_BORDER' ELSE 'OTHER' END AS affinity
                FROM silver_customer_call_edges e
                JOIN gold_customer_graph_features a ON e.source_customer_id = a.customer_id
                JOIN gold_customer_graph_features b ON e.destination_customer_id = b.customer_id
                WHERE a.community_id <> b.community_id
                  AND a.community_id IN ({quoted}) AND b.community_id IN ({quoted})
                GROUP BY least(a.community_id, b.community_id), greatest(a.community_id, b.community_id)
                ORDER BY calls DESC LIMIT 100
                """, cache_ttl=15,
            )
        else:
            if not community_id:
                raise HTTPException(400, "community_id es obligatorio para el nivel customer.")
            params["community_id"] = community_id
            nodes = run_sql(
                f"""
                SELECT f.customer_id AS node_id,
                       f.customer_id AS customer_id,
                       'customer' AS node_type,
                       concat(left(c.nombre_completo, 1), '•••', right(f.customer_id, 4)) AS label,
                       f.country, f.segment_id, f.community_id, p.risk_tier,
                       p.graph_churn_probability AS churn_probability,
                       f.influence_score, f.contagion_risk_score AS contagion_score,
                       f.unique_contacts, f.countries_reached, f.influenced_revenue_usd,
                       round(50 + (15 + pmod(xxhash64(f.customer_id, 111), 2500) / 100D)
                         * cos(2 * pi() * pmod(xxhash64(f.customer_id, 112), 1000) / 1000D), 2) AS x,
                       round(50 + (15 + pmod(xxhash64(f.customer_id, 113), 2500) / 100D)
                         * sin(2 * pi() * pmod(xxhash64(f.customer_id, 112), 1000) / 1000D), 2) AS y
                FROM gold_customer_graph_features f
                JOIN gold_churn_graph_predictions p USING (customer_id, community_id)
                JOIN silver_clientes c ON f.customer_id = c.cliente_id
                WHERE f.community_id = :community_id AND {country_filter}
                  AND (:risk_tier = 'ALL' OR p.risk_tier = :risk_tier)
                ORDER BY f.influence_score DESC, p.graph_churn_probability DESC
                LIMIT {limit}
                """, parameters=params, cache_ttl=15,
            )
            node_ids = [str(node["node_id"]) for node in nodes]
            if not node_ids:
                return {"available": True, "level": level, "summary": {}, "nodes": [], "edges": []}
            quoted = ",".join(f"'{value}'" for value in node_ids)
            edges = run_sql(
                f"""SELECT source_customer_id AS source, destination_customer_id AS target,
                           count(*) AS calls, round(sum(duration_seconds) / 60D, 1) AS minutes,
                           round(100 * avg(CASE WHEN dropped THEN 1D ELSE 0D END), 1) AS dropped_pct,
                           max(CASE WHEN international THEN 1 ELSE 0 END) = 1 AS international,
                           max(contact_affinity) AS affinity
                    FROM silver_customer_call_edges
                    WHERE source_customer_id IN ({quoted}) AND destination_customer_id IN ({quoted})
                    GROUP BY source_customer_id, destination_customer_id
                    ORDER BY calls DESC LIMIT 800""", cache_ttl=15,
            )
    except SqlExecutionError:
        return {"available": False, "reason": "GRAPH_NOT_READY", "level": level, "summary": {}, "nodes": [], "edges": []}
    for node in nodes:
        node.setdefault("reach_score", node.get("influence_score"))
        node.setdefault("network_exposure_score", node.get("contagion_score"))
    return {
        "available": True,
        "level": level,
        "summary": {
            "nodes": len(nodes), "edges": len(edges),
            "customers": sum(int(node.get("customer_count") or 1) for node in nodes),
            "high_risk_customers": sum(int(node.get("high_risk_customers") or (1 if node.get("risk_tier") in {"CRITICAL", "HIGH"} else 0)) for node in nodes),
            "influenced_revenue_usd": round(sum(float(node.get("influenced_revenue_usd") or 0) for node in nodes), 2),
        },
        "nodes": nodes,
        "edges": edges,
    }


_SEMANTIC_CLASSES = {
    "Customer", "QualifiedContact", "RelationshipGroup", "Country", "Plan",
    "Product", "Ticket", "SLA", "Recommendation",
}
_SEMANTIC_PREDICATES = {
    "qualifiedContact", "contactSource", "contactTarget", "locatedIn",
    "memberOfRelationshipGroup", "subscribedTo", "openedBy", "governedBySLA",
    "proposedFor", "recommendsProduct", "recommendedProduct",
}
_RDF_TYPE = "http://www.w3.org/1999/02/22-rdf-syntax-ns#type"
_RDFS_LABEL = "http://www.w3.org/2000/01/rdf-schema#label"
_ONTOLOGY_BASE = "https://quetzal.demo/ontology/"


def _semantic_scope_ctes() -> str:
    """Map every business entity to a customer country before aggregation."""
    return f"""
      WITH customer_country AS (
        SELECT t.subject AS customer_uri,
               regexp_extract(t.object, '([^/]+)$', 1) AS country
        FROM gold_quetzal_knowledge_graph_triples t
        WHERE t.predicate IN ('{_ONTOLOGY_BASE}locatedIn','{_ONTOLOGY_BASE.rstrip('/')}#locatedIn')
      ), direct_links AS (
        SELECT customer_uri AS entity_uri, customer_uri, country FROM customer_country
        UNION ALL
        SELECT r.object, cc.customer_uri, cc.country
        FROM gold_quetzal_knowledge_graph_triples r
        JOIN customer_country cc ON r.subject = cc.customer_uri
        WHERE r.object_is_iri = true
        UNION ALL
        SELECT r.subject, cc.customer_uri, cc.country
        FROM gold_quetzal_knowledge_graph_triples r
        JOIN customer_country cc ON r.object = cc.customer_uri
        WHERE r.object_is_iri = true
      ), relation_links AS (
        SELECT r.subject AS entity_uri, cc.customer_uri, cc.country
        FROM gold_quetzal_knowledge_graph_triples r
        JOIN customer_country cc ON r.object = cc.customer_uri
        WHERE regexp_extract(r.predicate, '([^#/]+)$', 1) IN ('contactSource','contactTarget')
      ), entity_scope AS (
        SELECT entity_uri, customer_uri, country FROM direct_links
        UNION ALL SELECT entity_uri, customer_uri, country FROM relation_links
      ), allowed_entities AS (
        SELECT DISTINCT entity_uri
        FROM entity_scope
        WHERE (:country = 'ALL' OR country = :country)
          AND (:authorized_country_scope = '' OR array_contains(split(:authorized_country_scope, ','), country))
      ), typed AS (
        SELECT subject, max(object) AS class_uri
        FROM gold_quetzal_knowledge_graph_triples
        WHERE predicate = '{_RDF_TYPE}'
        GROUP BY subject
      )
    """


def _semantic_provenance(
    summary: dict, predicates: list[str], access: dict, country: str = "ALL"
) -> dict:
    return {
        "source_type": "ONTOBRICKS_DELTA_PROJECTION",
        "domain": settings.ontobricks_domain,
        "version": settings.ontobricks_version,
        "table": "gold_quetzal_knowledge_graph_triples",
        "snapshot": {"run_id": summary.get("run_id"), "generated_at": summary.get("generated_at")},
        "algorithm": "Proyección RDF gobernada; Graph Intelligence v3 ponderado",
        "predicates": predicates,
        "territorial_scope": (
            [country] if country != "ALL" else (access["countries"] or ["ALL"])
        ),
        "manual_only": True,
    }


@router.get("/graph/semantic")
def semantic_graph(
    request: Request,
    limit: int = Query(default=120, ge=20, le=250),
    country: str = Query(default="ALL", pattern=r"^(ALL|PA|MX|CO|BR|AR|CL|PE|EC|CR|GT|DO|UY)$"),
):
    """Return a bounded class-level projection of the published OntoBricks graph."""
    access = _require_role(request, "NOC_OPERATOR", "CARE_AGENT", "EXECUTIVE_VIEWER")
    _assert_country_access(access, None if country == "ALL" else country)
    params = {"country": country, "authorized_country_scope": ",".join(access["countries"])}
    labels = {
        "Customer": "Clientes",
        "QualifiedContact": "Contactos calificados",
        "RelationshipGroup": "Grupos de relación",
        "Country": "Países",
        "Plan": "Planes",
        "Product": "Productos",
        "Ticket": "Tickets",
        "SLA": "Políticas SLA",
        "Recommendation": "Recomendaciones",
    }
    try:
        nodes = run_sql(
            _semantic_scope_ctes() + f"""
            SELECT object AS node_id, 'semantic' AS node_type,
                   regexp_extract(object, '([^#/]+)$', 1) AS class_name,
                   count(DISTINCT subject) AS entity_count,
                   round(12 + pmod(xxhash64(object, 314), 7600) / 100D, 2) AS x,
                   round(12 + pmod(xxhash64(object, 271), 7600) / 100D, 2) AS y
            FROM gold_quetzal_knowledge_graph_triples
            JOIN allowed_entities ON entity_uri = subject
            WHERE predicate = '{_RDF_TYPE}'
            GROUP BY object
            ORDER BY entity_count DESC
            LIMIT {min(limit, 120)}
            """,
            parameters=params, cache_ttl=15,
        )
        edges = run_sql(
            _semantic_scope_ctes() + f"""
            SELECT s.class_uri AS source, o.class_uri AS target,
                   r.predicate,
                   regexp_extract(r.predicate, '([^#/]+)$', 1) AS label,
                   count(*) AS relationship_count,
                   count(*) AS weight,
                   false AS international
            FROM gold_quetzal_knowledge_graph_triples r
            JOIN typed s ON r.subject = s.subject
            JOIN typed o ON r.object = o.subject
            JOIN allowed_entities ae1 ON ae1.entity_uri = r.subject
            JOIN allowed_entities ae2 ON ae2.entity_uri = r.object
            WHERE r.object_is_iri = true AND r.predicate <> '{_RDF_TYPE}'
            GROUP BY s.class_uri, o.class_uri, r.predicate
            ORDER BY relationship_count DESC
            LIMIT {min(limit * 2, 300)}
            """,
            parameters=params, cache_ttl=15,
        )
        totals = run_sql(
            _semantic_scope_ctes() + """
            SELECT count(*) AS triples, count(DISTINCT subject) AS entities,
                   count(DISTINCT predicate) AS predicates, max(generated_at) AS generated_at,
                   max(run_id) AS run_id
            FROM gold_quetzal_knowledge_graph_triples
            JOIN allowed_entities ON entity_uri = subject
            """, parameters=params, cache_ttl=15,
        )
    except SqlExecutionError:
        return {"available": False, "reason": "SEMANTIC_GRAPH_NOT_READY", "level": "semantic", "nodes": [], "edges": [], "summary": {}}
    for node in nodes:
        class_name = str(node.get("class_name") or "Entidad")
        node["label"] = labels.get(class_name, class_name)
        node["type"] = "semantic"
    summary = totals[0] if totals else {}
    summary.update({"nodes": len(nodes), "edges": len(edges), "entity_types": len(nodes)})
    return {
        "available": True,
        "level": "semantic",
        "domain": settings.ontobricks_domain,
        "summary": summary,
        "nodes": nodes,
        "edges": edges,
        "provenance": _semantic_provenance(
            summary,
            sorted({str(edge.get("predicate") or "") for edge in edges if edge.get("predicate")}),
            access,
            country,
        ),
    }


@router.get("/graph/semantic/entities")
def semantic_entities(
    request: Request,
    class_name: str = Query(pattern=r"^[A-Za-z]{2,64}$"),
    predicate: str | None = Query(default=None, pattern=r"^[A-Za-z]{2,64}$"),
    country: str = Query(default="ALL", pattern=r"^(ALL|PA|MX|CO|BR|AR|CL|PE|EC|CR|GT|DO|UY)$"),
    limit: int = Query(default=10, ge=1, le=50),
    offset: int = Query(default=0, ge=0, le=10000),
):
    """Return real, paginated semantic entities connected to governed customers."""
    access = _require_role(request, "CARE_AGENT")
    _assert_country_access(access, None if country == "ALL" else country)
    if class_name not in _SEMANTIC_CLASSES:
        raise HTTPException(400, "La clase semántica no está permitida.")
    if predicate and predicate not in _SEMANTIC_PREDICATES:
        raise HTTPException(400, "La relación semántica no está permitida.")
    class_uri = f"{_ONTOLOGY_BASE}{class_name}"
    predicate_uri = f"{_ONTOLOGY_BASE}{predicate}" if predicate else ""
    legacy_predicate_uri = f"{_ONTOLOGY_BASE.rstrip('/')}#{predicate}" if predicate else ""
    params = {
        "country": country, "authorized_country_scope": ",".join(access["countries"]),
        "class_uri": class_uri, "predicate_uri": predicate_uri,
        "legacy_predicate_uri": legacy_predicate_uri, "class_name": class_name,
    }
    relation_scope = ""
    relation_join = ""
    if predicate:
        # Materialize the bounded relationship endpoints once.  A correlated
        # EXISTS over the 1.6M-triple projection exceeded the SQL statement
        # timeout and was surfaced by the UI as an empty result set.
        relation_scope = """
      , relation_entities AS (
        SELECT subject AS entity_uri
        FROM gold_quetzal_knowledge_graph_triples
        WHERE predicate IN (:predicate_uri, :legacy_predicate_uri)
        UNION
        SELECT object AS entity_uri
        FROM gold_quetzal_knowledge_graph_triples
        WHERE predicate IN (:predicate_uri, :legacy_predicate_uri) AND object_is_iri = true
      )
        """
        relation_join = "JOIN relation_entities re ON re.entity_uri = t.subject"
    if class_name == "Customer":
        entity_customer_source = """
        SELECT DISTINCT s.entity_uri, cc.customer_uri, cc.country
        FROM selected s
        JOIN customer_country cc ON cc.customer_uri = s.entity_uri
        WHERE (:country = 'ALL' OR cc.country = :country)
          AND (:authorized_country_scope = '' OR array_contains(split(:authorized_country_scope, ','), cc.country))
        """
    else:
        entity_customer_source = """
        SELECT DISTINCT s.entity_uri, es.customer_uri, es.country
        FROM selected s JOIN entity_scope es ON es.entity_uri = s.entity_uri
        WHERE (:country = 'ALL' OR es.country = :country)
          AND (:authorized_country_scope = '' OR array_contains(split(:authorized_country_scope, ','), es.country))
        """
    base = _semantic_scope_ctes() + f"""
      , labels AS (
        SELECT subject, max(object) AS label
        FROM gold_quetzal_knowledge_graph_triples
        WHERE predicate = '{_RDFS_LABEL}' GROUP BY subject
      ) {relation_scope}, selected AS (
        SELECT t.subject AS entity_uri, regexp_extract(t.subject, '([^/]+)$', 1) AS entity_id,
               coalesce(l.label, regexp_extract(t.subject, '([^/]+)$', 1)) AS label
        FROM gold_quetzal_knowledge_graph_triples t
        JOIN allowed_entities a ON a.entity_uri = t.subject
        {relation_join}
        LEFT JOIN labels l ON l.subject = t.subject
        WHERE t.predicate = '{_RDF_TYPE}'
          AND regexp_extract(t.object, '([^#/]+)$', 1) = :class_name
      ), entity_customer AS (
        {entity_customer_source}
      ), current_plan AS (
        SELECT s.cliente_id, max_by(coalesce(p.nombre, s.plan_id), s.precio_mensual_usd) AS current_plan
        FROM silver_suscripciones s LEFT JOIN bronze_planes p ON p.plan_id = s.plan_id
        WHERE upper(s.estado) IN ('ACTIVA','ACTIVE') GROUP BY s.cliente_id
      ), top_offer AS (
        SELECT cliente_id, plan_id, product_name, recommendation_type, recommendation_score, marketing_eligible
        FROM ops_customer_next_best_offer
        QUALIFY row_number() OVER (PARTITION BY cliente_id ORDER BY recommendation_score DESC, plan_id) = 1
      )
    """
    try:
        total_rows = run_sql(
            base + "SELECT count(*) AS total FROM selected",
            parameters=params, cache_ttl=15,
        )
        rows = run_sql(
            base + f"""
            SELECT s.entity_uri, s.entity_id, s.label, :class_uri AS class_uri,
                   regexp_extract(ec.customer_uri, '([^/]+)$', 1) AS customer_id,
                   concat(left(c.nombre_completo, 1), '•••', right(c.cliente_id, 4)) AS customer_ref,
                   ec.country, c.segmento_nombre AS segment, c.churn_probability,
                   cp.current_plan, c.sla_policy_name, c.open_tickets,
                   o.plan_id AS proposed_plan_id, o.product_name AS proposed_product,
                   o.recommendation_type, o.recommendation_score, o.marketing_eligible
            FROM selected s
            LEFT JOIN entity_customer ec ON ec.entity_uri = s.entity_uri
            LEFT JOIN ops_customer_360 c ON c.cliente_id = regexp_extract(ec.customer_uri, '([^/]+)$', 1)
            LEFT JOIN current_plan cp ON cp.cliente_id = c.cliente_id
            LEFT JOIN top_offer o ON o.cliente_id = c.cliente_id
            QUALIFY row_number() OVER (PARTITION BY s.entity_uri ORDER BY c.churn_probability DESC NULLS LAST) = 1
            ORDER BY s.label, s.entity_uri LIMIT {limit} OFFSET {offset}
            """, parameters=params, cache_ttl=15,
        )
        snapshot = run_sql(
            "SELECT max(run_id) AS run_id, max(generated_at) AS generated_at FROM gold_quetzal_knowledge_graph_triples",
            cache_ttl=15,
        )
    except SqlExecutionError:
        return {
            "available": False,
            "reason": "SEMANTIC_ENTITIES_NOT_READY",
            "class_name": class_name,
            "predicate": predicate,
            "entities": [],
            "pagination": {"offset": offset, "limit": limit, "total": 0},
        }
    provenance_base = snapshot[0] if snapshot else {}
    predicates = [predicate] if predicate else ["rdf:type", "rdfs:label"]
    return {
        "available": True, "class_name": class_name, "predicate": predicate,
        "entities": rows,
        "pagination": {"offset": offset, "limit": limit, "total": int((total_rows[0] if total_rows else {}).get("total") or 0)},
        "provenance": _semantic_provenance(provenance_base, predicates, access, country),
    }


@router.get("/graph/communities/{community_id}/operational")
def graph_community_operational(
    community_id: str,
    request: Request,
    country: str = Query(default="ALL", pattern=r"^(ALL|PA|MX|CO|BR|AR|CL|PE|EC|CR|GT|DO|UY)$"),
    risk_tier: str = Query(default="ALL", pattern=r"^(ALL|CRITICAL|HIGH|MEDIUM|LOW)$"),
    sort: str = Query(default="priority", pattern=r"^(priority|opportunity|influence)$"),
    limit: int = Query(default=25, ge=10, le=100),
    offset: int = Query(default=0, ge=0, le=10000),
):
    """Turn a detected graph community into an actionable, governed customer cohort."""
    access = _require_role(request, "CARE_AGENT")
    if len(community_id) != 14 or not community_id.startswith("COM-") or not all(
        char in "0123456789abcdef" for char in community_id[4:]
    ):
        raise HTTPException(400, "Identificador de grupo inválido.")
    _assert_country_access(access, None if country == "ALL" else country)
    params: dict[str, str] = {
        "community_id": community_id,
        "country": country,
        "risk_tier": risk_tier,
        "country_scope": ",".join(access["countries"]),
    }
    scope_filter = "(:country = 'ALL' OR f.country = :country)"
    if access["countries"]:
        scope_filter += " AND array_contains(split(:country_scope, ','), f.country)"
    risk_filter = "(:risk_tier = 'ALL' OR p.risk_tier = :risk_tier)"
    scoped = f"""
      SELECT f.*, p.graph_churn_probability, p.graph_lift, p.risk_tier,
             p.recommended_action AS graph_recommended_action,
             c.nombre_completo, c.segmento_nombre, c.monthly_revenue,
             c.nps_ultimo, c.open_tickets, c.avg_resolution_hours,
             c.resolution_target_hours, c.overdue_balance, c.active_subscriptions,
             c.acepta_marketing
      FROM gold_customer_graph_features f
      JOIN gold_churn_graph_predictions p USING (customer_id, community_id)
      JOIN ops_customer_360 c ON f.customer_id = c.cliente_id
      WHERE f.community_id = :community_id AND {scope_filter} AND {risk_filter}
    """
    try:
        groups = run_sql(
            f"""
            WITH scoped AS ({scoped})
            SELECT community_id,
                   mode(country) AS primary_country,
                   mode(segment_id) AS dominant_segment_id,
                   mode(segmento_nombre) AS dominant_segment,
                   concat_ws(',', sort_array(collect_set(country))) AS countries,
                   count(DISTINCT country) AS countries_reached,
                   count(*) AS customer_count,
                   round(avg(graph_churn_probability), 4) AS avg_churn_probability,
                   sum(CASE WHEN risk_tier IN ('CRITICAL','HIGH') THEN 1 ELSE 0 END) AS high_risk_customers,
                   round(sum(monthly_revenue), 2) AS monthly_revenue_usd,
                   round(sum(monthly_revenue * graph_churn_probability), 2) AS monthly_revenue_at_risk_usd,
                   round(avg(influence_score), 1) AS avg_influence_score,
                   round(avg(contagion_risk_score), 1) AS avg_contagion_score,
                   round(avg(international_call_pct), 1) AS international_call_pct,
                   sum(CASE WHEN open_tickets > 0 THEN 1 ELSE 0 END) AS customers_with_open_tickets,
                   sum(CASE WHEN open_tickets > 0 AND avg_resolution_hours > resolution_target_hours THEN 1 ELSE 0 END) AS customers_with_sla_pressure,
                   sum(CASE WHEN nps_ultimo <= 6 THEN 1 ELSE 0 END) AS detractors,
                   sum(CASE WHEN acepta_marketing THEN 1 ELSE 0 END) AS marketing_eligible_customers,
                   max(computed_at) AS computed_at
            FROM scoped GROUP BY community_id
            """,
            parameters=params, cache_ttl=15,
        )
    except SqlExecutionError:
        return {"available": False, "reason": "GRAPH_NOT_READY", "group": None, "members": [], "offers": [], "playbooks": []}
    if not groups:
        raise HTTPException(404, "Grupo de relación no encontrado para el alcance solicitado.")
    group = groups[0]
    group["technical_id"] = community_id
    reach = "Alcance regional" if int(group.get("countries_reached") or 0) >= 3 else "Relaciones locales"
    group["display_name"] = (
        f"Red {group.get('dominant_segment') or group.get('dominant_segment_id') or 'Clientes'} "
        f"{group.get('primary_country') or 'LATAM'} · {reach}"
    )

    order_by = {
        "priority": "CASE WHEN c.active_subscriptions > 0 OR c.open_tickets > 0 OR c.monthly_revenue > 0 THEN 0 ELSE 1 END, p.graph_churn_probability DESC, f.influence_score DESC, c.monthly_revenue DESC",
        "opportunity": "CASE WHEN o.marketing_eligible THEN 0 ELSE 1 END, coalesce(o.recommendation_score, 0) DESC, c.monthly_revenue DESC, p.graph_churn_probability ASC",
        "influence": "CASE WHEN c.active_subscriptions > 0 OR c.open_tickets > 0 OR c.monthly_revenue > 0 THEN 0 ELSE 1 END, f.influence_score DESC, f.contagion_risk_score DESC, c.monthly_revenue DESC",
    }[sort]
    try:
        members = run_sql(
            f"""
        WITH current_plan AS (
          SELECT s.cliente_id, max_by(bp.nombre, s.precio_mensual_usd) AS current_plan
          FROM silver_suscripciones s LEFT JOIN bronze_planes bp ON s.plan_id = bp.plan_id
          WHERE upper(s.estado) IN ('ACTIVA','ACTIVE') GROUP BY s.cliente_id
        ), top_offer AS (
          SELECT * FROM ops_customer_next_best_offer WHERE marketing_eligible = true
          QUALIFY row_number() OVER (PARTITION BY cliente_id ORDER BY recommendation_score DESC, precio_usd) = 1
        )
        SELECT f.customer_id,
               concat(left(c.nombre_completo, 1), '•••', right(f.customer_id, 4)) AS customer_ref,
               f.country, c.segmento_nombre AS segment, cp.current_plan,
               c.monthly_revenue, p.graph_churn_probability AS churn_probability,
               p.graph_lift, p.risk_tier, f.influence_score,
               f.contagion_risk_score AS contagion_score, c.nps_ultimo,
               c.open_tickets, c.overdue_balance, c.active_subscriptions,
               CASE WHEN c.open_tickets > 0 AND c.avg_resolution_hours > c.resolution_target_hours THEN 'AT_RISK'
                    WHEN c.open_tickets > 0 THEN 'OPEN' ELSE 'ON_TRACK' END AS sla_status,
               CASE WHEN c.open_tickets > 0 THEN 'SERVICE_RECOVERY'
                    WHEN p.graph_churn_probability >= 0.65 THEN 'RETENTION'
                    WHEN c.nps_ultimo <= 6 THEN 'NPS_RECOVERY'
                    WHEN c.overdue_balance > 0 THEN 'PAYMENT_ASSISTANCE'
                    WHEN o.marketing_eligible THEN coalesce(o.recommendation_type, 'CROSS_SELL')
                    ELSE 'MONITOR' END AS next_best_action,
               o.plan_id AS proposed_plan_id, o.product_name AS proposed_product,
               o.vertical AS proposed_vertical, o.precio_usd AS proposed_price_usd,
               o.recommendation_score AS offer_score, o.marketing_eligible
        FROM gold_customer_graph_features f
        JOIN gold_churn_graph_predictions p USING (customer_id, community_id)
        JOIN ops_customer_360 c ON f.customer_id = c.cliente_id
        LEFT JOIN current_plan cp ON f.customer_id = cp.cliente_id
        LEFT JOIN top_offer o ON f.customer_id = o.cliente_id
        WHERE f.community_id = :community_id AND {scope_filter} AND {risk_filter}
        ORDER BY {order_by}
        LIMIT {limit} OFFSET {offset}
            """,
            parameters=params, cache_ttl=15,
        )
        offers = run_sql(
            f"""
        SELECT o.plan_id, max(o.product_name) AS product_name, max(o.vertical) AS vertical,
               max(o.tier) AS tier, round(avg(o.precio_usd), 2) AS price_usd,
               max(o.recommendation_type) AS recommendation_type,
               count(DISTINCT o.cliente_id) AS eligible_customers,
               round(avg(o.recommendation_score), 1) AS avg_score,
               max(o.reason) AS reason
        FROM ops_customer_next_best_offer o
        JOIN gold_customer_graph_features f ON o.cliente_id = f.customer_id
        JOIN gold_churn_graph_predictions p USING (customer_id, community_id)
        WHERE f.community_id = :community_id AND o.marketing_eligible = true
          AND {scope_filter} AND {risk_filter}
        GROUP BY o.plan_id
        ORDER BY eligible_customers DESC, avg_score DESC LIMIT 5
            """,
            parameters=params, cache_ttl=15,
        )
    except SqlExecutionError:
        return {
            "available": False, "reason": "OPERATIONAL_DATA_NOT_READY", "group": group,
            "members": [], "offers": [], "playbooks": [],
            "pagination": {"offset": offset, "limit": limit, "total": int(group.get("customer_count") or 0)},
            "filters": {"country": country, "risk_tier": risk_tier, "sort": sort},
        }
    high_risk = int(group.get("high_risk_customers") or 0)
    service_pressure = int(group.get("customers_with_sla_pressure") or 0)
    detractors = int(group.get("detractors") or 0)
    playbooks: list[dict] = []
    if service_pressure or int(group.get("customers_with_open_tickets") or 0):
        playbooks.append({
            "type": "SERVICE_RECOVERY", "priority": "HIGH", "title": "Recuperar servicio antes de vender",
            "audience": service_pressure or int(group.get("customers_with_open_tickets") or 0),
            "reason": "Clientes con tickets abiertos o presión sobre el objetivo de SLA.",
            "action": "Priorizar resolución, comunicación proactiva y crédito cuando sea aplicable.",
        })
    if high_risk:
        playbooks.append({
            "type": "RETENTION", "priority": "HIGH", "title": "Tratar el riesgo cliente por cliente",
            "audience": high_risk, "reason": "Clientes HIGH/CRITICAL dentro del grupo de relaciones.",
            "action": "Abrir Cliente 360, resolver fricciones y aprobar la oferta de permanencia adecuada.",
        })
    if detractors:
        playbooks.append({
            "type": "NPS_RECOVERY", "priority": "MEDIUM", "title": "Cerrar el ciclo con detractores",
            "audience": detractors, "reason": "Último NPS entre 0 y 6.",
            "action": "Entender causa, registrar solución y volver a medir antes de una campaña comercial.",
        })
    if offers:
        playbooks.append({
            "type": "GROWTH", "priority": "MEDIUM", "title": "Activar crecimiento elegible",
            "audience": int(group.get("marketing_eligible_customers") or 0),
            "reason": "Clientes estables con consentimiento y productos compatibles no contratados.",
            "action": "Priorizar las oportunidades de mayor afinidad; validar necesidad antes de ofertar.",
        })
    return {
        "available": True, "group": group, "members": members, "offers": offers,
        "playbooks": playbooks, "pagination": {"offset": offset, "limit": limit, "total": int(group.get("customer_count") or 0)},
        "filters": {"country": country, "risk_tier": risk_tier, "sort": sort},
    }


@router.get("/customers/{customer_id}/retention-cases")
def customer_retention_cases(customer_id: str, request: Request):
    access = _require_role(request, "CARE_AGENT", "ACTION_APPROVER", "NOC_OPERATOR", "EXECUTIVE_VIEWER")
    customer_id = _validate_customer_id(customer_id)
    profiles = _customer_profile(customer_id)
    if not profiles:
        raise HTTPException(404, "Cliente no encontrado.")
    _assert_country_access(access, profiles[0].get("pais_codigo") or profiles[0].get("country"))
    try:
        cases = retention_case_store.list_for_customer(customer_id)
    except Exception as exc:
        raise _retention_store_error(exc) from exc
    return {"status": "READY", "customer_id": customer_id, "cases": cases}


@router.get("/retention-cases")
def retention_cases(request: Request, limit: int = Query(default=25, ge=1, le=100)):
    access = _require_role(request, "CARE_AGENT", "ACTION_APPROVER", "NOC_OPERATOR", "EXECUTIVE_VIEWER")
    try:
        cases = retention_case_store.list_for_scope(tuple(access["countries"]), limit=limit)
    except Exception as exc:
        raise _retention_store_error(exc) from exc
    return {"status": "READY", "country_scope": access["countries"] or ["ALL"], "cases": cases}


@router.post("/customers/{customer_id}/retention-cases", status_code=201)
def create_retention_case(
    customer_id: str,
    payload: RetentionCaseCreateRequest,
    request: Request,
):
    access = _require_role(request, "CARE_AGENT")
    customer_id = _validate_customer_id(customer_id)
    profiles = _customer_profile(customer_id)
    if not profiles:
        raise HTTPException(404, "Cliente no encontrado.")
    customer = profiles[0]
    _assert_country_access(access, customer.get("pais_codigo") or customer.get("country"))
    model = _retention_model_snapshot(customer_id)
    recommendation = payload.model_dump()
    idempotency_key = _idempotency_key(request)
    try:
        case = retention_case_store.create_case(
            actor=access["actor"],
            customer=customer,
            model=model,
            recommendation=recommendation,
            idempotency_key=idempotency_key,
        )
    except Exception as exc:
        raise _retention_store_error(exc) from exc
    return {"status": "CREATED", "case": case}


@router.patch("/retention-cases/{case_id}")
def transition_retention_case(
    case_id: str,
    payload: RetentionCaseTransitionRequest,
    request: Request,
):
    if not case_id or len(case_id) > 64 or not all(char.isalnum() or char in "-_" for char in case_id):
        raise HTTPException(400, "Identificador de caso inválido.")
    access = _require_role(
        request,
        "ACTION_APPROVER" if payload.to_status in {"APPROVED", "REJECTED"} else "CARE_AGENT",
    )
    try:
        current = retention_case_store.get_case(case_id)
        _assert_country_access(access, current.get("country"))
        case = retention_case_store.transition_case(
            case_id=case_id,
            to_status=payload.to_status,
            expected_version=payload.expected_version,
            actor=access["actor"],
            note=payload.note,
            idempotency_key=_idempotency_key(request),
        )
    except HTTPException:
        raise
    except Exception as exc:
        raise _retention_store_error(exc) from exc
    return {"status": "UPDATED", "case": case}


@router.post("/customers/{customer_id}/recommendations", status_code=201)
def decide_recommendation(customer_id: str, payload: RecommendationDecisionRequest, request: Request):
    access = _require_role(request, "CARE_AGENT")
    customer_id = _validate_customer_id(customer_id)
    customers = run_sql("SELECT pais_codigo FROM ops_customer_360 WHERE cliente_id = :customer_id", parameters={"customer_id": customer_id}, cache_ttl=0)
    if not customers:
        raise HTTPException(404, "Cliente no encontrado.")
    _assert_country_access(access, customers[0].get("pais_codigo"))
    recommendation_id = "REC-" + uuid4().hex[:12].upper()
    execute_sql(
        """INSERT INTO ops_recommendation_log
           VALUES (:id, :customer_id, :type, :product_id, :title, :reason, :score, :status,
                   :actor, current_timestamp(), :actor, current_timestamp(), NULL, NULL, :note)""",
        parameters={"id": recommendation_id, "customer_id": customer_id, "type": payload.recommendation_type,
                    "product_id": payload.product_id, "title": payload.title, "reason": payload.reason,
                    "score": payload.score, "status": payload.decision, "actor": access["actor"], "note": payload.note},
    )
    _audit("RECOMMENDATION_" + payload.decision, "recommendation", recommendation_id, access["actor"], payload.model_dump())
    return {"recommendation_id": recommendation_id, "status": payload.decision}


@router.post("/recommendations/{recommendation_id}/outcome")
def recommendation_outcome(recommendation_id: str, payload: RecommendationOutcomeRequest, request: Request):
    access = _require_role(request, "CARE_AGENT")
    rows = run_sql(
        """SELECT r.status, c.pais_codigo AS country
           FROM ops_recommendation_log r
           JOIN ops_customer_360 c ON r.customer_id = c.cliente_id
           WHERE r.recommendation_id = :id""",
        parameters={"id": recommendation_id}, cache_ttl=0,
    )
    if not rows:
        raise HTTPException(404, "Recomendación no encontrada.")
    _assert_country_access(access, rows[0].get("country"))
    if rows[0].get("status") != "ACCEPTED":
        raise HTTPException(409, "Solo una recomendación aceptada puede recibir resultado.")
    execute_sql(
        """UPDATE ops_recommendation_log SET status = :status, outcome_value_usd = :value,
           outcome_at = current_timestamp(), updated_by = :actor, updated_at = current_timestamp(), note = :note
           WHERE recommendation_id = :id""",
        parameters={"status": payload.outcome, "value": payload.outcome_value_usd, "actor": access["actor"], "note": payload.note, "id": recommendation_id},
    )
    _audit("RECOMMENDATION_OUTCOME", "recommendation", recommendation_id, access["actor"], payload.model_dump())
    return {"recommendation_id": recommendation_id, "status": payload.outcome}


@router.get("/incidents/{incident_id}")
def incident_detail(incident_id: str):
    access = _require_context_role("NOC_OPERATOR", "CARE_AGENT", "EXECUTIVE_VIEWER")
    rows = run_sql(
        _incident_select("c.incident_id = :incident_id"),
        parameters={"incident_id": incident_id},
        cache_ttl=0,
    )
    if not rows:
        raise HTTPException(404, "Incidente no encontrado.")
    item = rows[0]
    _assert_country_access(access, item.get("country"))
    actions = run_sql(
        "SELECT * FROM ops_action_log WHERE incident_id = :incident_id ORDER BY requested_at DESC",
        parameters={"incident_id": incident_id},
        cache_ttl=0,
    )
    cause = str(item.get("probable_cause") or "RADIO_SIGNAL")
    item["root_cause"] = {
        "code": cause,
        "label": CAUSE_LABELS.get(cause, cause),
        "confidence": item.get("cause_confidence"),
        "evidence": [
            {"metric": "anomaly_score", "value": item.get("anomaly_score")},
            {"metric": "latency_ms", "value": item.get("latency_ms")},
            {"metric": "packet_loss_pct", "value": item.get("packet_loss_pct")},
            {"metric": "capacity_pct", "value": item.get("capacity_pct")},
            {"metric": "equipment_temp_c", "value": item.get("equipment_temp_c")},
            {"metric": "tickets_7d", "value": item.get("tickets_7d")},
        ],
    }
    item["recommended_actions"] = _recommended_actions(cause, item)
    item["actions"] = actions
    item["timeline"] = _timeline(item, actions)
    return item


def _recommended_actions(cause: str, incident: dict) -> list[dict]:
    primary = {
        "THERMAL": "DISPATCH_FIELD",
        "CONGESTION": "CAPACITY_CHANGE",
        "TRANSPORT": "CREATE_WORK_ORDER",
        "BACKHAUL": "CREATE_WORK_ORDER",
        "RADIO_SIGNAL": "DISPATCH_FIELD",
    }.get(cause, "CREATE_WORK_ORDER")
    actions = [
        {"type": primary, "label": ACTION_LABELS[primary], "approval_required": True},
        {"type": "CUSTOMER_NOTICE", "label": ACTION_LABELS["CUSTOMER_NOTICE"], "approval_required": True},
    ]
    if int(incident.get("high_churn_customers") or 0) > 0:
        actions.append({"type": "RETENTION_CAMPAIGN", "label": ACTION_LABELS["RETENTION_CAMPAIGN"], "approval_required": True})
    return actions


def _timeline(incident: dict, actions: list[dict]) -> list[dict]:
    result = [
        {"at": incident.get("detected_at"), "type": "DETECTED", "label": "Anomalía detectada por Isolation Forest"},
        {"at": incident.get("detected_at"), "type": "CORRELATED", "label": "Impacto de clientes, tickets y churn correlacionado"},
    ]
    for action in reversed(actions):
        result.append({
            "at": action.get("requested_at"),
            "type": "ACTION",
            "label": f"{ACTION_LABELS.get(action.get('action_type'), action.get('action_type'))} · {action.get('status')}",
        })
    if incident.get("updated_at"):
        result.append({"at": incident["updated_at"], "type": "STATUS", "label": f"Estado actualizado a {incident.get('status')}"})
    return result


@router.patch("/incidents/{incident_id}")
def update_incident(incident_id: str, payload: IncidentUpdateRequest, request: Request):
    access = _require_role(request, "NOC_OPERATOR")
    incidents = run_sql(
        "SELECT incident_id, country FROM ops_incident_candidates WHERE incident_id = :incident_id",
        parameters={"incident_id": incident_id},
        cache_ttl=0,
    )
    if not incidents:
        raise HTTPException(404, "Incidente no encontrado.")
    _assert_country_access(access, incidents[0].get("country"))
    actor = access["actor"]
    execute_sql(
        """
        MERGE INTO ops_incident_state AS target
        USING (SELECT :incident_id AS incident_id) AS source
        ON target.incident_id = source.incident_id
        WHEN MATCHED THEN UPDATE SET
          status = :status,
          assignee = :assignee,
          acknowledged_at = CASE WHEN :status IN ('ACKNOWLEDGED','IN_PROGRESS') AND target.acknowledged_at IS NULL THEN current_timestamp() ELSE target.acknowledged_at END,
          resolved_at = CASE WHEN :status = 'RESOLVED' THEN current_timestamp() ELSE NULL END,
          updated_at = current_timestamp(),
          updated_by = :actor
        WHEN NOT MATCHED THEN INSERT (incident_id, status, assignee, acknowledged_at, resolved_at, updated_at, updated_by)
        VALUES (:incident_id, :status, :assignee,
                CASE WHEN :status IN ('ACKNOWLEDGED','IN_PROGRESS') THEN current_timestamp() END,
                CASE WHEN :status = 'RESOLVED' THEN current_timestamp() END,
                current_timestamp(), :actor)
        """,
        parameters={"incident_id": incident_id, "status": payload.status, "assignee": payload.assignee or actor, "actor": actor},
    )
    _audit("INCIDENT_STATUS_CHANGED", "incident", incident_id, actor, payload.model_dump())
    return {"incident_id": incident_id, "status": payload.status, "assignee": payload.assignee or actor}


@router.get("/network/topology")
def network_topology(country: str | None = Query(default=None, pattern=r"^[A-Z]{2}$"), city: str | None = Query(default=None, max_length=120)):
    access = _require_context_role("NOC_OPERATOR", "CARE_AGENT", "EXECUTIVE_VIEWER")
    _assert_country_access(access, country)
    params: dict[str, str] = {}
    country_where = "TRUE"
    city_where = "TRUE"
    tower_where = "TRUE"
    if country:
        country_where += " AND pais_codigo = :country"
        city_where += " AND t.pais_codigo = :country"
        tower_where += " AND t.pais_codigo = :country"
        params["country"] = country
    elif access["countries"]:
        country_where += " AND array_contains(split(:country_scope, ','), pais_codigo)"
        city_where += " AND array_contains(split(:country_scope, ','), t.pais_codigo)"
        tower_where += " AND array_contains(split(:country_scope, ','), t.pais_codigo)"
        params["country_scope"] = ",".join(access["countries"])
    if city:
        tower_where += " AND t.ciudad = :city"
        params["city"] = city
    countries_future = submit_with_context(fanout, run_sql, f"""
      SELECT pais_codigo AS country, ROUND(AVG(uptime_pct),2) AS health_score,
             ROUND(AVG(avg_latencia_ms),1) AS latency_ms,
             ROUND(AVG(avg_throughput_mbps),1) AS throughput_mbps,
             ROUND(AVG(avg_packet_loss_pct),2) AS packet_loss_pct,
             ROUND(AVG(avg_uso_capacidad_pct),1) AS capacity_pct,
             SUM(torres_en_alerta) AS towers_alert, MAX(hora) AS as_of
      FROM gold_network_health
      WHERE hora = (SELECT MAX(hora) FROM gold_network_health) AND {country_where}
      GROUP BY pais_codigo ORDER BY health_score DESC
    """, parameters=params)
    cities_future = submit_with_context(fanout, run_sql, f"""
      WITH anchor AS (SELECT MAX(timestamp) AS ts FROM silver_telemetria_red)
      SELECT t.pais_codigo AS country, t.ciudad AS city, COUNT(DISTINCT t.torre_id) AS towers,
             ROUND(AVG(CASE WHEN lower(t.alerta) IN ('sin alerta','normal','ok','false','0') THEN 100 ELSE 0 END),1) AS health_score,
             ROUND(AVG(t.latencia_ms),1) AS latency_ms, ROUND(AVG(t.throughput_mbps),1) AS throughput_mbps,
             ROUND(AVG(t.uso_capacidad_pct),1) AS capacity_pct,
             SUM(CASE WHEN lower(t.alerta) NOT IN ('sin alerta','normal','ok','false','0') THEN 1 ELSE 0 END) AS towers_alert
      FROM silver_telemetria_red t CROSS JOIN anchor a
      WHERE t.timestamp = a.ts AND {city_where}
      GROUP BY t.pais_codigo, t.ciudad ORDER BY towers_alert DESC, capacity_pct DESC LIMIT 100
    """, parameters=params)
    towers = []
    if country:
        towers = run_sql(f"""
          WITH anchor AS (SELECT MAX(timestamp) AS ts FROM silver_telemetria_red)
          SELECT t.torre_id, t.pais_codigo AS country, t.ciudad AS city, t.tecnologia AS technology,
                 d.latitud AS latitude, d.longitud AS longitude, t.usuarios_conectados AS connected_customers,
                 ROUND(t.latencia_ms,1) AS latency_ms, ROUND(t.throughput_mbps,1) AS throughput_mbps,
                 ROUND(t.packet_loss_pct,2) AS packet_loss_pct, ROUND(t.uso_capacidad_pct,1) AS capacity_pct,
                 t.temperatura_equipo_c AS equipment_temp_c, t.alerta AS alert, t.timestamp AS as_of
          FROM silver_telemetria_red t CROSS JOIN anchor a
          LEFT JOIN bronze_torres_red d ON t.torre_id = d.torre_id
          WHERE t.timestamp = a.ts AND {tower_where}
          ORDER BY CASE WHEN lower(t.alerta) IN ('sin alerta','normal','ok','false','0') THEN 1 ELSE 0 END,
                   t.uso_capacidad_pct DESC LIMIT 200
        """, parameters=params)
    return {
        "countries": countries_future.result(),
        "cities": cities_future.result(),
        "towers": towers,
        "metric_semantics": {"health_score": "percentage_of_measurements_without_alerts", "contractual_uptime": "not_available"},
    }


@router.get("/customer-impact")
def customer_impact(country: str | None = Query(default=None, pattern=r"^[A-Z]{2}$")):
    access = _require_context_role("NOC_OPERATOR", "CARE_AGENT", "EXECUTIVE_VIEWER")
    _assert_country_access(access, country)
    where = "TRUE"
    params: dict[str, str] = {}
    if country:
        where = "c.pais_codigo = :country"
        params["country"] = country
    elif access["countries"]:
        where = "array_contains(split(:country_scope, ','), c.pais_codigo)"
        params["country_scope"] = ",".join(access["countries"])
    rows = run_sql(f"""
      WITH anchor AS (SELECT MAX(scored_at) AS ts FROM gold_churn_predictions)
      SELECT c.pais_codigo AS country,
             COUNT(*) AS customers_scored,
             SUM(CASE WHEN lower(c.risk_tier) IN ('alto','crítico','critico','high','critical') THEN 1 ELSE 0 END) AS high_risk_customers,
             ROUND(AVG(c.churn_probability),3) AS avg_churn_probability,
             ROUND(SUM(CASE WHEN lower(c.risk_tier) IN ('alto','crítico','critico','high','critical') THEN c.gasto_mensual_total ELSE 0 END),0) AS monthly_revenue_at_risk,
             SUM(CASE WHEN c.total_tickets > 2 THEN 1 ELSE 0 END) AS repeat_contact_customers,
             SUM(CASE WHEN c.nps_ultimo <= 6 THEN 1 ELSE 0 END) AS detractors
      FROM gold_churn_predictions c CROSS JOIN anchor a
      WHERE c.scored_at = a.ts AND {where}
      GROUP BY c.pais_codigo ORDER BY monthly_revenue_at_risk DESC
    """, parameters=params)
    return {"countries": rows, "methodology": "latest_churn_scoring_with_customer_value"}


@router.get("/proactive-care")
def proactive_care(country: str | None = Query(default=None, pattern=r"^[A-Z]{2}$"), limit: int = Query(default=20, ge=1, le=100)):
    access = _require_context_role("CARE_AGENT", "NOC_OPERATOR")
    _assert_country_access(access, country)
    where = "lower(c.risk_tier) IN ('alto','crítico','critico','high','critical')"
    params: dict[str, object] = {"limit": limit}
    if country:
        where += " AND c.pais_codigo = :country"
        params["country"] = country
    elif access["countries"]:
        where += " AND array_contains(split(:country_scope, ','), c.pais_codigo)"
        params["country_scope"] = ",".join(access["countries"])
    return run_sql(f"""
      WITH anchor AS (SELECT MAX(scored_at) AS ts FROM gold_churn_predictions)
      SELECT c.cliente_id AS customer_id,
             concat('••••', right(c.cliente_id, 6)) AS customer_ref,
             c.pais_codigo AS country, c.segmento_id AS segment,
             ROUND(c.churn_probability,3) AS churn_probability,
             ROUND(c.gasto_mensual_total,2) AS monthly_value,
             c.total_tickets, c.facturas_vencidas, c.nps_ultimo,
             CASE WHEN c.tickets_cancelacion > 0 THEN 'RETENTION_SPECIALIST'
                  WHEN c.facturas_vencidas > 0 THEN 'PAYMENT_PLAN'
                  WHEN c.nps_ultimo <= 6 THEN 'SERVICE_RECOVERY'
                  ELSE 'PROACTIVE_CONTACT' END AS recommended_action,
             CASE WHEN c.churn_probability >= .85 THEN 'URGENT' ELSE 'HIGH' END AS priority
      FROM gold_churn_predictions c CROSS JOIN anchor a
      WHERE c.scored_at = a.ts AND {where}
      ORDER BY c.churn_probability * c.gasto_mensual_total DESC LIMIT :limit
    """, parameters=params)


@router.post("/scenarios/capacity")
def capacity_scenario(payload: ScenarioRequest):
    access = _require_context_role("NOC_OPERATOR")
    _assert_country_access(access, None if payload.country == "ALL" else payload.country)
    where = "hora = (SELECT MAX(hora) FROM gold_network_health)"
    params: dict[str, object] = {}
    if payload.country != "ALL":
        where += " AND pais_codigo = :country"
        params["country"] = payload.country
    elif access["countries"]:
        where += " AND array_contains(split(:country_scope, ','), pais_codigo)"
        params["country_scope"] = ",".join(access["countries"])
    rows = run_sql(f"""
      SELECT pais_codigo AS country,
             ROUND(AVG(avg_uso_capacidad_pct),1) AS current_capacity_pct,
             ROUND(AVG(avg_throughput_mbps),1) AS throughput_mbps,
             SUM(torres_en_alerta) AS towers_alert,
             SUM(total_mediciones) AS measurements
      FROM gold_network_health WHERE {where}
      GROUP BY pais_codigo ORDER BY current_capacity_pct DESC
    """, parameters=params)
    output = []
    for row in rows:
        current = float(row.get("current_capacity_pct") or 0)
        projected = max(0, current * (1 + payload.growth_pct / 100) * (1 - payload.traffic_shift_pct / 100))
        towers_alert = int(row.get("towers_alert") or 0)
        congestion_factor = max(0.0, (projected - 75) / 25)
        towers_at_risk = round(towers_alert * (1 + congestion_factor))
        estimated_investment = max(0, towers_at_risk - towers_alert) * 85000
        output.append({
            "country": row["country"],
            "current_capacity_pct": round(current, 1),
            "projected_capacity_pct": round(projected, 1),
            "risk": "CRITICAL" if projected >= 90 else "HIGH" if projected >= 80 else "CONTROLLED",
            "towers_at_risk": towers_at_risk,
            "estimated_investment_usd": estimated_investment,
            "recommended_action": "EXPAND_CAPACITY" if projected >= 80 else "MONITOR",
        })
    return {
        "inputs": payload.model_dump(),
        "results": output,
        "totals": {
            "towers_at_risk": sum(x["towers_at_risk"] for x in output),
            "estimated_investment_usd": sum(x["estimated_investment_usd"] for x in output),
        },
        "methodology": "capacity_growth_stress_test_v1",
    }


@router.get("/actions")
def actions(request: Request, status: str | None = Query(default=None, pattern=r"^(PENDING_APPROVAL|APPROVED|REJECTED|EXECUTING|EXECUTED|FAILED)$")):
    access = _require_role(request, "NOC_OPERATOR", "ACTION_APPROVER", "EXECUTIVE_VIEWER")
    where = "TRUE"
    params: dict[str, str] = {}
    if status:
        where = "a.status = :status"
        params["status"] = status
    if access["countries"]:
        where += " AND array_contains(split(:country_scope, ','), c.country)"
        params["country_scope"] = ",".join(access["countries"])
    return run_sql(f"""
      SELECT a.*, c.title AS incident_title, c.country, c.severity,
             x.connector, x.execution_ref, x.detail AS execution_detail, x.completed_at AS executed_at
      FROM ops_action_log a LEFT JOIN ops_incident_candidates c ON a.incident_id = c.incident_id
      LEFT JOIN (
        SELECT * FROM ops_action_attempts
        QUALIFY ROW_NUMBER() OVER (PARTITION BY action_id ORDER BY started_at DESC) = 1
      ) x ON a.action_id = x.action_id
      WHERE {where} ORDER BY a.requested_at DESC LIMIT 200
    """, parameters=params, cache_ttl=0)


@router.post("/incidents/{incident_id}/actions", status_code=201)
def create_action(incident_id: str, payload: ActionCreateRequest, request: Request):
    access = _require_role(request, "NOC_OPERATOR")
    incidents = run_sql(
        "SELECT incident_id, country FROM ops_incident_candidates WHERE incident_id = :incident_id",
        parameters={"incident_id": incident_id}, cache_ttl=0,
    )
    if not incidents:
        raise HTTPException(404, "Incidente no encontrado.")
    _assert_country_access(access, incidents[0].get("country"))
    actor = access["actor"]
    action_id = "ACT-" + uuid4().hex[:12].upper()
    execute_sql(
        """INSERT INTO ops_action_log
        VALUES (:action_id, :incident_id, :action_type, :rationale, 'PENDING_APPROVAL',
                :actor, current_timestamp(), NULL, NULL, NULL)""",
        parameters={"action_id": action_id, "incident_id": incident_id, "action_type": payload.action_type, "rationale": payload.rationale, "actor": actor},
    )
    _audit("ACTION_REQUESTED", "action", action_id, actor, {"incident_id": incident_id, **payload.model_dump()})
    return {"action_id": action_id, "status": "PENDING_APPROVAL", "approval_required": True}


@router.post("/actions/{action_id}/decision")
def decide_action(action_id: str, payload: ActionDecisionRequest, request: Request):
    access = _require_role(request, "ACTION_APPROVER")
    existing = run_sql(
        """SELECT a.status, a.requested_by, c.country
           FROM ops_action_log a
           LEFT JOIN ops_incident_candidates c ON a.incident_id = c.incident_id
           WHERE a.action_id = :action_id""",
        parameters={"action_id": action_id}, cache_ttl=0,
    )
    if not existing:
        raise HTTPException(404, "Acción no encontrada.")
    if existing[0]["status"] != "PENDING_APPROVAL":
        raise HTTPException(409, "La acción ya fue decidida.")
    _assert_country_access(access, existing[0].get("country"))
    actor = access["actor"]
    if str(existing[0].get("requested_by") or "").lower() == actor.lower():
        raise HTTPException(409, "Segregación de funciones: el solicitante no puede aprobar su propia acción.")
    execute_sql(
        """UPDATE ops_action_log SET status = :status, decided_by = :actor,
           decided_at = current_timestamp(), decision_note = :note WHERE action_id = :action_id""",
        parameters={"status": payload.decision, "actor": actor, "note": payload.note, "action_id": action_id},
    )
    _audit("ACTION_DECIDED", "action", action_id, actor, payload.model_dump())
    return {"action_id": action_id, "status": payload.decision, "decided_by": actor}


@router.post("/actions/{action_id}/execute")
def execute_action(action_id: str, payload: ActionExecutionRequest, request: Request):
    access = _require_role(request, "NOC_OPERATOR")
    rows = run_sql(
        """SELECT a.*, c.country, c.title AS incident_title
           FROM ops_action_log a LEFT JOIN ops_incident_candidates c ON a.incident_id = c.incident_id
           WHERE a.action_id = :action_id""",
        parameters={"action_id": action_id}, cache_ttl=0,
    )
    if not rows:
        raise HTTPException(404, "Acción no encontrada.")
    action = rows[0]
    _assert_country_access(access, action.get("country"))
    if action.get("status") not in ("APPROVED", "FAILED"):
        raise HTTPException(409, "Solo una acción aprobada o fallida puede ejecutarse.")
    attempt_id = "RUN-" + uuid4().hex[:12].upper()
    connector = connector_for(str(action.get("action_type")), payload.connector)
    execute_sql(
        """INSERT INTO ops_action_attempts
           (attempt_id, action_id, connector, status, idempotency_key, request_json,
            response_code, response_json, started_at, completed_at, actor, execution_ref, detail)
           VALUES (:attempt_id, :action_id, :connector, 'EXECUTING', :idempotency_key,
                   :request_json, NULL, NULL, current_timestamp(), NULL, :actor, NULL, NULL)""",
        parameters={"attempt_id": attempt_id, "action_id": action_id, "connector": connector,
                    "idempotency_key": action_id, "request_json": json.dumps(action, default=str), "actor": access["actor"]},
    )
    execute_sql("UPDATE ops_action_log SET status = 'EXECUTING' WHERE action_id = :action_id", parameters={"action_id": action_id})
    result = dispatch_action({**action, "execution_note": payload.note}, payload.connector)
    final_status = "EXECUTED" if result.success else "FAILED"
    execute_sql(
        """UPDATE ops_action_attempts SET status = :status, response_code = :response_code,
           response_json = :response_json, completed_at = current_timestamp(), execution_ref = :execution_ref,
           detail = :detail WHERE attempt_id = :attempt_id""",
        parameters={"status": final_status, "response_code": result.status_code,
                    "response_json": json.dumps(result.as_dict(), ensure_ascii=False), "execution_ref": result.execution_ref,
                    "detail": result.detail, "attempt_id": attempt_id},
    )
    execute_sql("UPDATE ops_action_log SET status = :status WHERE action_id = :action_id", parameters={"status": final_status, "action_id": action_id})
    _audit("ACTION_EXECUTION_" + final_status, "action", action_id, access["actor"], result.as_dict())
    if not result.success:
        raise HTTPException(424, {"action_id": action_id, "status": final_status, **result.as_dict()})
    return {"action_id": action_id, "attempt_id": attempt_id, "status": final_status, **result.as_dict()}


@router.get("/alerts/subscriptions")
def alert_subscriptions(request: Request):
    access = _require_role(request, "NOC_OPERATOR")
    return run_sql(
        "SELECT * FROM ops_alert_subscriptions WHERE owner = :owner ORDER BY updated_at DESC",
        parameters={"owner": access["actor"]},
        cache_ttl=0,
    )


@router.post("/alerts/subscriptions", status_code=201)
def create_alert_subscription(payload: AlertSubscriptionRequest, request: Request):
    access = _require_role(request, "NOC_OPERATOR")
    actor = access["actor"]
    if payload.country == "ALL" and access["countries"]:
        raise HTTPException(403, "Selecciona un país dentro de tu alcance para crear la alerta.")
    _assert_country_access(access, None if payload.country == "ALL" else payload.country)
    subscription_id = "SUB-" + uuid4().hex[:12].upper()
    execute_sql(
        """INSERT INTO ops_alert_subscriptions
        VALUES (:id, :owner, :name, :domain, :country, :metric, :operator, :threshold,
                :channel, :enabled, current_timestamp(), current_timestamp())""",
        parameters={
            "id": subscription_id,
            "owner": actor,
            "name": payload.name,
            "domain": payload.domain,
            "country": None if payload.country == "ALL" else payload.country,
            "metric": payload.metric,
            "operator": payload.operator,
            "threshold": payload.threshold,
            "channel": payload.channel,
            "enabled": payload.enabled,
        },
    )
    _audit("ALERT_SUBSCRIBED", "alert_subscription", subscription_id, actor, payload.model_dump())
    return {"subscription_id": subscription_id, "enabled": payload.enabled}


@router.patch("/alerts/subscriptions/{subscription_id}")
def update_alert_subscription(subscription_id: str, payload: AlertStateRequest, request: Request):
    access = _require_role(request, "NOC_OPERATOR")
    rows = run_sql(
        "SELECT owner FROM ops_alert_subscriptions WHERE subscription_id = :id",
        parameters={"id": subscription_id}, cache_ttl=0,
    )
    if not rows:
        raise HTTPException(404, "Regla de alerta no encontrada.")
    if "ADMIN" not in access["roles"] and str(rows[0].get("owner")).lower() != access["actor"].lower():
        raise HTTPException(403, "Solo el propietario puede modificar esta regla.")
    execute_sql(
        "UPDATE ops_alert_subscriptions SET enabled = :enabled, updated_at = current_timestamp() WHERE subscription_id = :id",
        parameters={"enabled": payload.enabled, "id": subscription_id},
    )
    _audit("ALERT_RULE_UPDATED", "alert_subscription", subscription_id, access["actor"], payload.model_dump())
    return {"subscription_id": subscription_id, "enabled": payload.enabled}


def _comparison(operator: str, observed: float, threshold: float) -> bool:
    return {">": observed > threshold, ">=": observed >= threshold, "<": observed < threshold,
            "<=": observed <= threshold, "=": observed == threshold}.get(operator, False)


@router.post("/alerts/evaluate")
def evaluate_alerts(request: Request):
    access = _require_role(request, "ADMIN")
    rules = run_sql("SELECT * FROM ops_alert_subscriptions WHERE enabled = true", cache_ttl=0)
    capacity = run_sql(
        """SELECT pais_codigo AS country, ROUND(AVG(avg_uso_capacidad_pct), 2) AS capacity_pct
           FROM gold_network_health WHERE hora = (SELECT MAX(hora) FROM gold_network_health)
           GROUP BY pais_codigo""", cache_ttl=0,
    )
    metric_rows = {"capacity_pct": capacity}
    triggered = 0
    unsupported: list[str] = []
    for rule in rules:
        metric = str(rule.get("metric"))
        if metric not in metric_rows:
            unsupported.append(metric)
            continue
        for row in metric_rows[metric]:
            country = str(row.get("country"))
            if rule.get("country") and rule.get("country") != country:
                continue
            observed = float(row.get(metric) or 0)
            threshold = float(rule.get("threshold") or 0)
            if not _comparison(str(rule.get("operator")), observed, threshold):
                continue
            fingerprint = f"{rule['subscription_id']}:{country}:{metric}:{datetime.now(UTC).strftime('%Y%m%d%H')}"
            event_id = "ALT-" + uuid4().hex[:12].upper()
            notification_status = "DELIVERED" if rule.get("channel") == "IN_APP" else "PENDING_CONNECTOR"
            execute_sql(
                """MERGE INTO ops_alert_events AS target
                   USING (SELECT :fingerprint AS fingerprint) AS source ON target.fingerprint = source.fingerprint
                   WHEN NOT MATCHED THEN INSERT (event_id, subscription_id, fingerprint, country, metric,
                     observed_value, threshold, severity, status, notification_status, detected_at,
                     notified_at, acknowledged_at, acknowledged_by, note)
                   VALUES (:event_id, :subscription_id, :fingerprint, :country, :metric, :observed,
                     :threshold, :severity, 'OPEN', :notification_status, current_timestamp(),
                     CASE WHEN :notification_status = 'DELIVERED' THEN current_timestamp() END, NULL, NULL, NULL)""",
                parameters={"event_id": event_id, "subscription_id": rule["subscription_id"], "fingerprint": fingerprint,
                            "country": country, "metric": metric, "observed": observed, "threshold": threshold,
                            "severity": "CRITICAL" if observed >= threshold * 1.1 else "HIGH",
                            "notification_status": notification_status},
            )
            triggered += 1
    _audit("ALERT_EVALUATION", "alert_engine", "scheduled-or-manual", access["actor"], {"triggered": triggered, "unsupported": unsupported})
    return {"rules_evaluated": len(rules), "signals_triggered": triggered, "unsupported_metrics": sorted(set(unsupported))}


@router.get("/alerts/events")
def alert_events(request: Request, status: str = Query(default="OPEN", pattern=r"^(OPEN|ACKNOWLEDGED|ALL)$")):
    access = _require_role(request, "NOC_OPERATOR", "EXECUTIVE_VIEWER")
    clauses = ["TRUE" if status == "ALL" else "e.status = :status"]
    params: dict[str, str] = {} if status == "ALL" else {"status": status}
    if access["countries"]:
        clauses.append("array_contains(split(:country_scope, ','), e.country)")
        params["country_scope"] = ",".join(access["countries"])
    return run_sql(
        f"""SELECT e.*, s.name, s.owner, s.channel FROM ops_alert_events e
            JOIN ops_alert_subscriptions s ON e.subscription_id = s.subscription_id
            WHERE {' AND '.join(clauses)} ORDER BY e.detected_at DESC LIMIT 100""",
        parameters=params, cache_ttl=0,
    )


@router.post("/alerts/events/{event_id}/acknowledge")
def acknowledge_alert(event_id: str, payload: AlertAcknowledgeRequest, request: Request):
    access = _require_role(request, "NOC_OPERATOR")
    events = run_sql(
        "SELECT country FROM ops_alert_events WHERE event_id = :id",
        parameters={"id": event_id}, cache_ttl=0,
    )
    if not events:
        raise HTTPException(404, "Alerta no encontrada.")
    _assert_country_access(access, events[0].get("country"))
    execute_sql(
        """UPDATE ops_alert_events SET status = 'ACKNOWLEDGED', acknowledged_at = current_timestamp(),
           acknowledged_by = :actor, note = :note WHERE event_id = :id""",
        parameters={"actor": access["actor"], "note": payload.note, "id": event_id},
    )
    _audit("ALERT_ACKNOWLEDGED", "alert_event", event_id, access["actor"], payload.model_dump())
    return {"event_id": event_id, "status": "ACKNOWLEDGED"}


@router.get("/sla/portfolio")
def sla_portfolio(request: Request):
    access = _require_role(request, "NOC_OPERATOR", "CARE_AGENT", "EXECUTIVE_VIEWER")
    where = "TRUE"
    params: dict[str, str] = {}
    if access["countries"]:
        where = "array_contains(split(:country_scope, ','), c.pais_codigo)"
        params["country_scope"] = ",".join(access["countries"])
    rows = run_sql(
        f"""SELECT c.pais_codigo AS country, COUNT(*) AS tickets_assessed,
             SUM(CASE WHEN t.tiempo_resolucion_horas > p.resolution_target_hours THEN 1 ELSE 0 END) AS breached,
             ROUND(100 * AVG(CASE WHEN t.tiempo_resolucion_horas <= p.resolution_target_hours THEN 1 ELSE 0 END), 1) AS compliance_pct,
             ROUND(SUM(CASE WHEN t.tiempo_resolucion_horas > p.resolution_target_hours
                       THEN q.monthly_revenue * p.breach_credit_pct / 100 ELSE 0 END), 2) AS estimated_credit_usd
           FROM silver_tickets t JOIN silver_clientes c ON t.cliente_id = c.cliente_id
           JOIN ops_sla_policy p ON c.segmento_id = p.segment_id
           LEFT JOIN ops_customer_360 q ON t.cliente_id = q.cliente_id
           WHERE t.tiempo_resolucion_horas IS NOT NULL AND {where}
           GROUP BY c.pais_codigo ORDER BY breached DESC""",
        parameters=params, cache_ttl=0,
    )
    return {"countries": rows, "generated_at": datetime.now(UTC).isoformat()}


@router.get("/governance/trust")
def governance_trust():
    _require_context_role("ADMIN")
    freshness = run_sql("""
      WITH sources AS (
        SELECT 'network' AS domain, 'hourly' AS cadence, CAST(MAX(hora) AS TIMESTAMP) AS as_of FROM gold_network_health
        UNION ALL SELECT 'revenue','monthly',CAST(MAX(mes) AS TIMESTAMP) FROM gold_revenue_by_country_service WHERE mes < DATE_TRUNC('MONTH', CURRENT_DATE())
        UNION ALL SELECT 'customers','daily',CAST(MAX(scored_at) AS TIMESTAMP) FROM gold_churn_predictions
        UNION ALL SELECT 'tickets','daily',CAST(MAX(fecha_creacion) AS TIMESTAMP) FROM silver_tickets
      )
      SELECT *, ROUND((UNIX_TIMESTAMP(CURRENT_TIMESTAMP()) - UNIX_TIMESTAMP(as_of))/3600.0,1) AS lag_hours,
        CASE WHEN cadence='hourly' AND as_of >= CURRENT_TIMESTAMP()-INTERVAL 2 HOURS THEN 'FRESH'
             WHEN cadence='daily' AND as_of >= CURRENT_TIMESTAMP()-INTERVAL 48 HOURS THEN 'FRESH'
             WHEN cadence='monthly' AND as_of >= ADD_MONTHS(DATE_TRUNC('MONTH',CURRENT_DATE()),-1) THEN 'FRESH'
             ELSE 'STALE' END AS status
      FROM sources ORDER BY domain
    """, cache_ttl=0)
    audit = run_sql("SELECT * FROM ops_audit_log ORDER BY event_at DESC LIMIT 25", cache_ttl=0)
    return {
        "freshness": freshness,
        "metric_definitions": [
            {"name": "network_health_score", "definition": "Porcentaje de mediciones sin alerta", "contractual_uptime": False, "owner": "Network Operations"},
            {"name": "revenue_at_risk", "definition": "Clientes afectados × valor mensual × factor de severidad", "contractual_uptime": None, "owner": "Finance & CX"},
            {"name": "customer_impact_score", "definition": "Impacto ponderado por clientes, valor, churn y severidad", "contractual_uptime": None, "owner": "Customer Operations"},
        ],
        "lineage": [
            {"product": "Incident Center", "sources": ["gold_network_anomalies", "silver_tickets", "gold_churn_predictions"]},
            {"product": "Network Topology", "sources": ["silver_telemetria_red", "bronze_torres_red", "gold_network_health"]},
            {"product": "Proactive Care", "sources": ["gold_churn_predictions"]},
        ],
        "audit": audit,
    }
