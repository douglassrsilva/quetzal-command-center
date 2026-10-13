"""Auditable operational connectors for CRM, BSS and OSS actions."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from uuid import uuid4

import requests


@dataclass(frozen=True)
class DispatchResult:
    success: bool
    connector: str
    execution_ref: str
    status_code: int
    detail: str

    def as_dict(self) -> dict:
        return asdict(self)


CONNECTOR_BY_ACTION = {
    "DISPATCH_FIELD": "OSS",
    "CREATE_WORK_ORDER": "OSS",
    "CAPACITY_CHANGE": "OSS",
    "CUSTOMER_NOTICE": "CRM",
    "RETENTION_CAMPAIGN": "CRM",
    "COMPENSATION": "BSS",
}


def connector_for(action_type: str, requested: str = "AUTO") -> str:
    return CONNECTOR_BY_ACTION.get(action_type, "INTERNAL") if requested == "AUTO" else requested


def dispatch_action(action: dict, requested_connector: str = "AUTO") -> DispatchResult:
    """Dispatch once using an idempotency key; internal queue is the safe default."""
    connector = connector_for(str(action.get("action_type") or ""), requested_connector)
    execution_ref = f"QZ-{uuid4().hex[:14].upper()}"
    if connector == "INTERNAL":
        return DispatchResult(True, connector, execution_ref, 202, "Registrado en la cola operativa interna de Quetzal.")

    endpoint = os.getenv(f"QUETZAL_{connector}_WEBHOOK_URL", "").strip()
    if not endpoint or not endpoint.startswith(("https://", "http://")):
        if requested_connector == "AUTO":
            return DispatchResult(
                True, "INTERNAL", execution_ref, 202,
                f"Registrado en la cola interna; active QUETZAL_{connector}_WEBHOOK_URL para entrega automática a {connector}.",
            )
        return DispatchResult(False, connector, execution_ref, 424, f"Conector {connector} no configurado.")

    token = os.getenv("QUETZAL_CONNECTOR_TOKEN", "").strip()
    headers = {"Content-Type": "application/json", "Idempotency-Key": str(action["action_id"])}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        response = requests.post(endpoint, json={**action, "execution_ref": execution_ref}, headers=headers, timeout=15)
        response.raise_for_status()
        reference = response.headers.get("x-request-id") or execution_ref
        return DispatchResult(True, connector, reference, response.status_code, response.text[:1000] or "Aceptado por el conector.")
    except requests.RequestException as exc:
        status_code = getattr(getattr(exc, "response", None), "status_code", 502) or 502
        return DispatchResult(False, connector, execution_ref, status_code, str(exc)[:1000])
