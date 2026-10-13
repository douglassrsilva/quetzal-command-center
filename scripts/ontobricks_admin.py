#!/usr/bin/env python3
"""Import, build, publish and validate the Quetzal OntoBricks domain.

The command authenticates with a Databricks CLI profile, uses the deployed
Apps URLs and never creates a schedule.  State-changing calls use the same
double-submit CSRF contract as the OntoBricks browser UI.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import requests
from databricks.sdk import WorkspaceClient

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OBX = ROOT / "ontology" / "quetzal-telecom-v1.obx"
DEFAULT_APP_URL = "https://ontobricks-quetzal-7474654097678606.aws.databricksapps.com"
DEFAULT_MCP_URL = "https://mcp-ontobricks-quetzal-7474654097678606.aws.databricksapps.com"
TERMINAL_TASK_STATES = {"completed", "failed", "cancelled"}
ONTOLOGY_BASE = "https://quetzal.demo/ontology/"
EXPECTED_ATTRIBUTE_PREDICATES = {
    f"{ONTOLOGY_BASE}{name}"
    for name in (
        "baselineChurnProbability",
        "retentionPriorityScore",
        "networkReachScore",
        "networkExposureScore",
        "callCount",
        "contactMinutes",
        "relationshipWeight",
        "isReciprocal",
        "qualificationReason",
    )
}
GRAPHQL_SMOKE_QUERY = """query QuetzalCustomerSmoke {
  customers(limit: 1) {
    id
    uri
    label
    baselineChurnProbability
    retentionPriorityScore
    networkReachScore
    networkExposureScore
  }
}"""


class AdminError(RuntimeError):
    """Operational error with a concise, user-facing message."""


class OntoBricksClient:
    def __init__(self, profile: str, app_url: str, timeout: int = 60) -> None:
        auth = dict(WorkspaceClient(profile=profile).config.authenticate() or {})
        if not auth.get("Authorization"):
            raise AdminError(f"No fue posible obtener un token para el perfil {profile!r}")
        self.base_url = app_url.rstrip("/")
        self.timeout = timeout
        self.session = requests.Session()
        self.session.headers.update(
            {"Accept": "application/json", "User-Agent": "quetzal-ontobricks-admin/1.0", **auth}
        )
        self._prime_csrf()

    def _prime_csrf(self) -> None:
        response = self.session.get(f"{self.base_url}/healthz", timeout=self.timeout)
        if response.status_code >= 500:
            raise AdminError(f"OntoBricks no está saludable: HTTP {response.status_code}")
        token = self.session.cookies.get("csrf_token")
        if not token:
            response = self.session.get(f"{self.base_url}/", timeout=self.timeout)
            token = self.session.cookies.get("csrf_token")
        if token:
            self.session.headers["X-CSRF-Token"] = token

    @staticmethod
    def _payload(response: requests.Response) -> Any:
        try:
            return response.json()
        except ValueError:
            return {"text": response.text[:1000]}

    def request(self, method: str, path: str, **kwargs: Any) -> Any:
        response = self.session.request(
            method, f"{self.base_url}{path}", timeout=kwargs.pop("timeout", self.timeout), **kwargs
        )
        payload = self._payload(response)
        if response.status_code >= 400:
            message = payload.get("message") or payload.get("detail") or payload.get("text")
            raise AdminError(f"{method} {path}: HTTP {response.status_code}: {message}")
        return payload

    def get(self, path: str, **kwargs: Any) -> Any:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> Any:
        return self.request("POST", path, **kwargs)


def _print_step(label: str, payload: Any) -> None:
    compact = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    print(f"[{label}] {compact}")


def _version_status(client: OntoBricksClient, domain: str, version: str) -> str:
    payload = client.get("/api/v1/domain/versions", params={"domain_name": domain})
    for item in payload.get("versions", []):
        if str(item.get("version")) == str(version):
            return str(item.get("status") or "DRAFT").upper()
    raise AdminError(f"No se encontró {domain} v{version} en el registro")


def _transition(client: OntoBricksClient, domain: str, version: str, status: str) -> Any:
    return client.post(
        "/domain/set-version-status",
        json={"domain_name": domain, "version": version, "status": status},
    )


def _ensure_draft(client: OntoBricksClient, domain: str, version: str) -> None:
    status = _version_status(client, domain, version)
    if status in {"PUBLISHED", "IN-REVIEW"}:
        result = _transition(client, domain, version, "DRAFT")
        _print_step("lifecycle:draft", result)
    elif status != "DRAFT":
        raise AdminError(f"Estado de versión no reconocido: {status}")


def _wait_internal_task(
    client: OntoBricksClient, task_id: str, timeout_seconds: int, poll_seconds: float
) -> dict:
    deadline = time.monotonic() + timeout_seconds
    last_progress = None
    while time.monotonic() < deadline:
        payload = client.get(f"/tasks/{task_id}", timeout=90)
        task = payload.get("task") or payload
        status = str(task.get("status") or "").lower()
        progress = task.get("progress")
        marker = (status, progress, task.get("message"))
        if marker != last_progress:
            _print_step("build:progress", marker)
            last_progress = marker
        if status in TERMINAL_TASK_STATES:
            if status != "completed":
                raise AdminError(
                    f"Build OntoBricks terminó en {status}: "
                    f"{task.get('error') or task.get('message') or 'sin detalle'}"
                )
            return task
        time.sleep(poll_seconds)
    raise AdminError(f"Timeout esperando el build {task_id} después de {timeout_seconds}s")


def import_build_publish(
    client: OntoBricksClient,
    obx_path: Path,
    domain: str,
    version: str,
    timeout_seconds: int,
    poll_seconds: float,
) -> dict:
    if not obx_path.exists():
        raise AdminError(f"No existe el artefacto OBX: {obx_path}")

    with obx_path.open("rb") as handle:
        preview = client.post(
            "/settings/registry/import/preview",
            files={"file": (obx_path.name, handle, "application/json")},
        )
    _print_step("import:preview", preview)

    decision = [{"name": domain, "action": "overwrite"}]
    with obx_path.open("rb") as handle:
        imported = client.post(
            "/settings/registry/import",
            files={"file": (obx_path.name, handle, "application/json")},
            data={"decisions": json.dumps(decision)},
        )
    if not imported.get("success") or int(imported.get("imported_versions") or 0) < 1:
        raise AdminError(f"La importación OBX no escribió versiones: {imported}")
    _print_step("import:apply", imported)

    _ensure_draft(client, domain, version)
    loaded = client.post("/domain/load-from-uc", json={"domain": domain, "version": version})
    if not loaded.get("success"):
        raise AdminError(f"No fue posible cargar el dominio: {loaded}")
    _print_step("domain:load", loaded)

    started = client.post("/dtwin/databricks-build/start", json={})
    task_id = started.get("task_id")
    if not started.get("success") or not task_id:
        raise AdminError(f"No fue posible iniciar el build: {started}")
    _print_step("build:start", started)
    completed = _wait_internal_task(client, str(task_id), timeout_seconds, poll_seconds)
    _print_step("build:completed", completed)

    # OntoBricks 0.8.1's Databricks-specific build pipeline stamps
    # ``last_build`` in the active session but does not flush it to the registry.
    # Persist the loaded DRAFT explicitly so /api/v1/domains can truthfully
    # advertise has_graph=true and the MCP server keeps graph tools enabled.
    saved = client.post("/domain/save-to-uc", json={})
    if not saved.get("success"):
        raise AdminError(f"El build terminó pero last_build no fue persistido: {saved}")
    _print_step("build:persist-registry", saved)

    status = _version_status(client, domain, version)
    if status == "DRAFT":
        _print_step("lifecycle:review", _transition(client, domain, version, "IN-REVIEW"))
        status = "IN-REVIEW"
    if status == "IN-REVIEW":
        _print_step("lifecycle:publish", _transition(client, domain, version, "PUBLISHED"))
    final_status = _version_status(client, domain, version)
    if final_status != "PUBLISHED":
        raise AdminError(f"La versión terminó en {final_status}, no PUBLISHED")
    return {"import": imported, "build": completed, "status": final_status}


def _parse_mcp_response(response: requests.Response) -> dict:
    content_type = response.headers.get("content-type", "")
    if "json" in content_type:
        return response.json()
    for line in response.text.splitlines():
        if line.startswith("data: "):
            return json.loads(line[6:])
    raise AdminError(f"Respuesta MCP no reconocida ({content_type}): {response.text[:500]}")


def validate_mcp(
    profile: str,
    mcp_url: str,
    timeout: int,
    domain: str,
    graphql_query: str,
) -> dict:
    auth = dict(WorkspaceClient(profile=profile).config.authenticate() or {})
    session = requests.Session()
    session.headers.update(
        {
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
            "User-Agent": "quetzal-ontobricks-admin/1.0",
            **auth,
        }
    )
    endpoint = f"{mcp_url.rstrip('/')}/mcp"
    init = session.post(
        endpoint,
        json={
            "jsonrpc": "2.0",
            "id": "quetzal-init",
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "quetzal-admin", "version": "1.0"},
            },
        },
        timeout=timeout,
    )
    if init.status_code >= 400:
        raise AdminError(f"MCP initialize: HTTP {init.status_code}: {init.text[:500]}")
    init_body = _parse_mcp_response(init)
    session_id = init.headers.get("Mcp-Session-Id") or init.headers.get("mcp-session-id")
    if not session_id or not init_body.get("result"):
        raise AdminError(f"MCP initialize no creó sesión: {init_body}")
    headers = {"Mcp-Session-Id": session_id}
    session.post(
        endpoint,
        json={"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
        headers=headers,
        timeout=timeout,
    )
    listed = session.post(
        endpoint,
        json={"jsonrpc": "2.0", "id": "quetzal-tools", "method": "tools/list", "params": {}},
        headers=headers,
        timeout=timeout,
    )
    if listed.status_code >= 400:
        raise AdminError(f"MCP tools/list: HTTP {listed.status_code}: {listed.text[:500]}")
    body = _parse_mcp_response(listed)
    tools = (body.get("result") or {}).get("tools") or []
    if not tools:
        raise AdminError(f"MCP tools/list no devolvió herramientas: {body}")
    tool_names = [item.get("name") for item in tools]
    required = {"select_domain", "query_graphql"}
    missing_tools = required - set(tool_names)
    if missing_tools:
        raise AdminError(f"MCP no expone las herramientas requeridas: {sorted(missing_tools)}")

    def call_tool(call_id: str, name: str, arguments: dict) -> str:
        response = session.post(
            endpoint,
            json={
                "jsonrpc": "2.0",
                "id": call_id,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments},
            },
            headers=headers,
            timeout=timeout,
        )
        if response.status_code >= 400:
            raise AdminError(f"MCP {name}: HTTP {response.status_code}: {response.text[:500]}")
        payload = _parse_mcp_response(response)
        if payload.get("error"):
            raise AdminError(f"MCP {name} devolvió error: {payload['error']}")
        result = payload.get("result") or {}
        content = result.get("content") or []
        rendered = "\n".join(
            str(item.get("text") or "")
            for item in content
            if isinstance(item, dict) and item.get("type") == "text"
        )
        if result.get("isError") or not rendered.strip():
            raise AdminError(f"MCP {name} no devolvió contenido válido: {payload}")
        return rendered

    selection = call_tool("quetzal-select", "select_domain", {"domain_name": domain})
    if "ontology only" in selection.lower() or "ontology-only" in selection.lower():
        raise AdminError(f"MCP clasificó el dominio con datos como ontology-only: {selection}")
    query_result = call_tool(
        "quetzal-query",
        "query_graphql",
        {"query": graphql_query},
    )
    if "baselineChurnProbability" not in query_result:
        raise AdminError(
            "MCP query_graphql no devolvió atributos analíticos de un cliente real: "
            + query_result[:1000]
        )
    return {
        "protocol": (init_body.get("result") or {}).get("protocolVersion"),
        "tool_count": len(tools),
        "tools": tool_names,
        "selected_domain": domain,
        "graphql_data_query": True,
    }


def validate_runtime(
    client: OntoBricksClient,
    profile: str,
    domain: str,
    version: str,
    mcp_url: str,
    timeout: int,
) -> dict:
    domains = client.get("/api/v1/domains")
    entry = next((item for item in domains.get("domains", []) if item.get("name") == domain), None)
    if not entry:
        raise AdminError(f"El dominio publicado {domain!r} no aparece en /api/v1/domains")
    if not entry.get("has_graph"):
        raise AdminError(
            f"El registro publica {domain!r} como ontology-only (has_graph=false): {entry}"
        )
    versions = client.get("/api/v1/domain/versions", params={"domain_name": domain})
    target = next((item for item in versions.get("versions", []) if str(item.get("version")) == version), None)
    if not target or target.get("status") != "PUBLISHED":
        raise AdminError(f"La versión {domain} v{version} no está publicada: {target}")
    status = client.get("/api/v1/digitaltwin/status", params={"domain_name": domain, "domain_version": version})
    if not status.get("has_data") or int(status.get("count") or 0) <= 0:
        raise AdminError(f"El grafo no contiene datos: {status}")
    stats = client.get("/api/v1/digitaltwin/stats", params={"domain_name": domain, "domain_version": version}, timeout=120)
    if int(stats.get("total_triples") or 0) <= 0 or int(stats.get("distinct_predicates") or 0) < 22:
        raise AdminError(f"Las estadísticas del grafo no cumplen el contrato: {stats}")
    predicate_uris = {
        item.get("uri") for item in stats.get("top_predicates", []) if item.get("uri")
    }
    missing_attributes = EXPECTED_ATTRIBUTE_PREDICATES - predicate_uris
    if missing_attributes:
        raise AdminError(
            "El grafo materializado no contiene todos los atributos gobernados: "
            f"{sorted(missing_attributes)}"
        )
    schema = client.get(f"/api/v1/graphql/{domain}/schema", timeout=120)
    if not schema.get("ready") or "type Query" not in str(schema.get("sdl") or ""):
        raise AdminError(f"El esquema GraphQL no está listo: {schema}")
    graphql = client.post(
        f"/api/v1/graphql/{domain}",
        json={"query": GRAPHQL_SMOKE_QUERY},
        timeout=120,
    )
    customers = (graphql.get("data") or {}).get("customers") or []
    required_values = (
        "baselineChurnProbability",
        "retentionPriorityScore",
        "networkReachScore",
        "networkExposureScore",
    )
    if (
        graphql.get("errors")
        or not customers
        or any(customers[0].get(key) in (None, "") for key in required_values)
    ):
        raise AdminError(f"La consulta GraphQL falló: {graphql}")
    mcp = validate_mcp(profile, mcp_url, timeout, domain, GRAPHQL_SMOKE_QUERY)
    result = {
        "domain": entry,
        "version": target,
        "graph": status,
        "stats": stats,
        "graphql": graphql,
        "mcp": mcp,
    }
    _print_step("validate", result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("sync", "validate"))
    parser.add_argument("--profile", default="vibe-coding")
    parser.add_argument("--app-url", default=DEFAULT_APP_URL)
    parser.add_argument("--mcp-url", default=DEFAULT_MCP_URL)
    parser.add_argument("--domain", default="quetzal_telecom")
    parser.add_argument("--version", default="1")
    parser.add_argument("--obx", type=Path, default=DEFAULT_OBX)
    parser.add_argument("--timeout", type=int, default=1800, help="Build timeout in seconds.")
    parser.add_argument("--request-timeout", type=int, default=120)
    parser.add_argument("--poll-seconds", type=float, default=3.0)
    args = parser.parse_args()
    try:
        client = OntoBricksClient(args.profile, args.app_url, args.request_timeout)
        if args.command == "sync":
            import_build_publish(
                client,
                args.obx,
                args.domain,
                args.version,
                args.timeout,
                args.poll_seconds,
            )
        validate_runtime(
            client,
            args.profile,
            args.domain,
            args.version,
            args.mcp_url,
            args.request_timeout,
        )
        return 0
    except (AdminError, requests.RequestException) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
