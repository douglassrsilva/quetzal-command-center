"""Read-only, allowlisted OntoBricks MCP client for Quetzal IQ.

The model selects a business intent, never GraphQL.  Query text and limits are
owned by this module so prompt content cannot widen the semantic data surface.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Literal
from uuid import uuid4

import requests

from .config import settings
from .platform import auth_headers

SemanticIntent = Literal[
    "CUSTOMER_RELATIONSHIPS",
    "CLASS_MEMBERS",
    "CUSTOMER_CONTEXT",
    "PLAN_ELIGIBILITY",
    "SLA_CONTEXT",
    "RECOMMENDATION_CONTEXT",
]

_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
_CLASS_ROOTS = {
    "Customer": ("customers", "baselineChurnProbability retentionPriorityScore networkReachScore networkExposureScore"),
    "QualifiedContact": ("qualifiedContacts", "callCount contactMinutes relationshipWeight isReciprocal qualificationReason"),
    "RelationshipGroup": ("relationshipGroups", ""),
    "Country": ("countries", ""),
    "Plan": ("plans", ""),
    "Product": ("products", ""),
    "Ticket": ("tickets", ""),
    "SLA": ("sLAs", ""),
    "Recommendation": ("recommendations", ""),
}
_INTENT_CLASS = {
    "CUSTOMER_RELATIONSHIPS": "QualifiedContact",
    "CUSTOMER_CONTEXT": "Customer",
    "PLAN_ELIGIBILITY": "Plan",
    "SLA_CONTEXT": "SLA",
    "RECOMMENDATION_CONTEXT": "Recommendation",
}
_CUSTOMER_RELATION_SELECTIONS = {
    "CUSTOMER_RELATIONSHIPS": (
        "qualifiedContact { id uri label baselineChurnProbability retentionPriorityScore "
        "networkReachScore networkExposureScore }"
    ),
    "PLAN_ELIGIBILITY": "subscribedTo { id uri label } recommendedProduct { id uri label }",
    "SLA_CONTEXT": "governedBySLA { id uri label }",
    "RECOMMENDATION_CONTEXT": "recommendedProduct { id uri label }",
}
_CLASS_RELATIONS = {
    "QualifiedContact": _CUSTOMER_RELATION_SELECTIONS["CUSTOMER_RELATIONSHIPS"],
    "RelationshipGroup": "memberOfRelationshipGroup { id uri label }",
    "Country": "locatedIn { id uri label }",
    "Plan": "subscribedTo { id uri label }",
    "Product": "recommendedProduct { id uri label }",
    "SLA": "governedBySLA { id uri label }",
}
_CUSTOMER_FIELDS = (
    "id uri label baselineChurnProbability retentionPriorityScore "
    "networkReachScore networkExposureScore"
)


class OntoBricksError(RuntimeError):
    """Safe operational MCP failure."""


def _parse_response(response: requests.Response) -> dict[str, Any]:
    content_type = response.headers.get("content-type", "")
    try:
        if "json" in content_type:
            return response.json()
        for line in response.text.splitlines():
            if line.startswith("data: "):
                return json.loads(line[6:])
    except (ValueError, json.JSONDecodeError) as exc:
        raise OntoBricksError("OntoBricks MCP devolvió una respuesta inválida.") from exc
    raise OntoBricksError("OntoBricks MCP no devolvió JSON-RPC reconocible.")


def _graphql(
    intent: SemanticIntent,
    class_name: str | None,
    customer_id: str | None,
    limit: int,
) -> tuple[str, str, list[str]]:
    resolved_class = class_name if intent == "CLASS_MEMBERS" else _INTENT_CLASS.get(intent, "Customer")
    if resolved_class not in _CLASS_ROOTS:
        raise OntoBricksError("La clase semántica solicitada no está permitida.")
    root, attributes = _CLASS_ROOTS[resolved_class]
    fields = f"id uri label {attributes}".strip()
    if customer_id:
        if intent == "CUSTOMER_CONTEXT":
            relationships = " ".join([
                "locatedIn { id uri label }",
                "memberOfRelationshipGroup { id uri label }",
                _CUSTOMER_RELATION_SELECTIONS["PLAN_ELIGIBILITY"],
                _CUSTOMER_RELATION_SELECTIONS["SLA_CONTEXT"],
            ])
        elif intent == "CLASS_MEMBERS":
            if resolved_class == "Customer":
                relationships = ""
            elif resolved_class not in _CLASS_RELATIONS:
                raise OntoBricksError(
                    "Esta clase no tiene una navegación territorial segura desde Customer."
                )
            else:
                relationships = _CLASS_RELATIONS[resolved_class]
        else:
            relationships = _CUSTOMER_RELATION_SELECTIONS.get(intent, "")
        query = (
            f'query QuetzalGoverned {{ customer(id: "{customer_id}") '
            f'{{ {_CUSTOMER_FIELDS} {relationships} }} }}'
        )
    else:
        query = f"query QuetzalGoverned {{ {root}(limit: {limit}) {{ {fields} }} }}"
    predicates = {
        "Customer": ["rdf:type", "locatedIn", "memberOfRelationshipGroup"],
        "QualifiedContact": ["qualifiedContact", "contactSource", "contactTarget"],
        "Plan": ["subscribedTo"],
        "SLA": ["governedBySLA"],
        "Recommendation": ["proposedFor", "recommendsProduct"],
    }.get(resolved_class, ["rdf:type", "rdfs:label"])
    return query, resolved_class, predicates


@dataclass(frozen=True)
class OntoBricksMCPClient:
    endpoint: str = settings.ontobricks_mcp_url
    domain: str = settings.ontobricks_domain
    timeout: int = 30

    @property
    def enabled(self) -> bool:
        return bool(self.endpoint)

    def query(
        self,
        *,
        intent: SemanticIntent,
        class_name: str | None = None,
        customer_id: str | None = None,
        limit: int = 20,
        countries: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        if not self.enabled:
            raise OntoBricksError("OntoBricks MCP no está configurado.")
        if customer_id and not _SAFE_ID.fullmatch(customer_id):
            raise OntoBricksError("El identificador de cliente no es válido.")
        if countries and not customer_id:
            raise OntoBricksError(
                "La consulta MCP requiere un cliente validado para perfiles con alcance territorial."
            )
        bounded_limit = max(1, min(int(limit), 50))
        query, resolved_class, predicates = _graphql(intent, class_name, customer_id, bounded_limit)
        session = requests.Session()
        session.headers.update({
            **auth_headers(),
            "Accept": "application/json, text/event-stream",
            "User-Agent": "Quetzal-OntoBricks-MCP/1.0",
        })
        init = self._post(session, {
            "jsonrpc": "2.0", "id": uuid4().hex, "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05", "capabilities": {},
                "clientInfo": {"name": "quetzal-iq", "version": "1.0"},
            },
        })
        session_id = init[1]
        headers = {"Mcp-Session-Id": session_id}
        self._post(session, {
            "jsonrpc": "2.0", "method": "notifications/initialized", "params": {},
        }, headers=headers, expect_result=False)
        self._call(session, headers, "select_domain", {"domain_name": self.domain})
        rendered = self._call(session, headers, "query_graphql", {"query": query})
        return {
            "available": True,
            "source_type": "ONTOBRICKS_MCP",
            "intent": intent,
            "class_name": resolved_class,
            "customer_id": customer_id,
            "territorial_scope": list(countries) or ["ALL"],
            "domain": self.domain,
            "version": settings.ontobricks_version,
            "predicates": predicates,
            "result": _normalize_text(rendered)[:24000],
        }

    def _post(
        self,
        session: requests.Session,
        payload: dict[str, Any],
        *,
        headers: dict[str, str] | None = None,
        expect_result: bool = True,
    ) -> tuple[dict[str, Any], str] | None:
        try:
            response = session.post(self.endpoint, json=payload, headers=headers, timeout=self.timeout)
        except requests.RequestException as exc:
            raise OntoBricksError("OntoBricks MCP no está disponible temporalmente.") from exc
        if response.status_code >= 400:
            raise OntoBricksError(f"OntoBricks MCP respondió HTTP {response.status_code}.")
        if not expect_result:
            return None
        body = _parse_response(response)
        if body.get("error"):
            raise OntoBricksError("OntoBricks MCP rechazó la consulta gobernada.")
        session_id = response.headers.get("Mcp-Session-Id") or response.headers.get("mcp-session-id") or ""
        if expect_result and not body.get("result"):
            raise OntoBricksError("OntoBricks MCP no devolvió un resultado.")
        if expect_result and payload.get("method") == "initialize" and not session_id:
            raise OntoBricksError("OntoBricks MCP no creó una sesión.")
        return (body, session_id) if expect_result else None

    def _call(
        self,
        session: requests.Session,
        headers: dict[str, str],
        name: str,
        arguments: dict[str, Any],
    ) -> str:
        body, _ = self._post(session, {
            "jsonrpc": "2.0", "id": uuid4().hex, "method": "tools/call",
            "params": {"name": name, "arguments": arguments},
        }, headers=headers)
        result = body.get("result") or {}
        rendered = "\n".join(
            str(item.get("text") or "") for item in result.get("content") or []
            if isinstance(item, dict) and item.get("type") == "text"
        )
        if result.get("isError") or not rendered.strip():
            raise OntoBricksError(f"La herramienta MCP {name} no devolvió datos válidos.")
        return rendered


ontobricks_mcp = OntoBricksMCPClient()


def _normalize_text(value: str) -> str:
    """Repair the known UTF-8-as-Latin-1 MCP transport artifact when present."""
    if not any(marker in value for marker in ("Ã", "Â", "â")):
        return value
    try:
        repaired = value.encode("latin-1").decode("utf-8")
    except (UnicodeEncodeError, UnicodeDecodeError):
        return value
    return repaired
