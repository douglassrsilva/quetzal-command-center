"""Collect a bounded, read-only Quetzal execution snapshot to stdout.

The collector never starts jobs, invokes Genie/Quetzal IQ, builds OntoBricks,
or persists credentials. Human identities are masked before serialization.
"""

from __future__ import annotations

import argparse
import json
import re
from datetime import UTC, datetime
from typing import Any

import requests
from databricks.sdk import WorkspaceClient

EMAIL_PATTERN = re.compile(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", re.IGNORECASE)
MASK = "[MASKED_DATABRICKS_ACTOR]"


def _mask(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _mask(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_mask(item) for item in value]
    if isinstance(value, str):
        return EMAIL_PATTERN.sub(MASK, value)
    return value


def _get(session: requests.Session, url: str, timeout: int = 180) -> dict[str, Any]:
    response = session.get(url, timeout=timeout)
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise TypeError(f"Expected a JSON object from {url}")
    return payload


def _app_summary(client: WorkspaceClient, app_name: str) -> dict[str, Any]:
    app = client.apps.get(app_name).as_dict()
    deployment = app.get("active_deployment") or {}
    return {
        "name": app.get("name"),
        "url": app.get("url"),
        "app_status": (app.get("app_status") or {}).get("state"),
        "compute_status": (app.get("compute_status") or {}).get("state"),
        "deployment_id": deployment.get("deployment_id"),
        "deployment_status": (deployment.get("status") or {}).get("state"),
        "deployment_create_time": deployment.get("create_time"),
        "deployment_update_time": deployment.get("update_time"),
        "resources": app.get("resources") or [],
    }


def _campaign_summary(payload: dict[str, Any]) -> dict[str, Any]:
    campaign = payload.get("campaign") if isinstance(payload.get("campaign"), dict) else payload
    return {
        "campaign_id": campaign.get("campaign_id"),
        "status": campaign.get("status"),
        "campaign_sent": campaign.get("campaign_sent"),
        "version": campaign.get("version"),
        "snapshot_version": campaign.get("snapshot_version"),
        "audience_fingerprint": campaign.get("audience_fingerprint"),
        "events": campaign.get("events") or [],
    }


def collect(args: argparse.Namespace) -> dict[str, Any]:
    client = WorkspaceClient(profile=args.profile)
    auth = dict(client.config.authenticate() or {})
    if not auth:
        raise RuntimeError(f"Profile {args.profile!r} did not produce authentication headers")

    session = requests.Session()
    session.headers.update({"Accept": "application/json", **auth})
    app = _app_summary(client, args.app_name)
    app_url = str(app.get("url") or "").rstrip("/")
    if not app_url:
        raise RuntimeError(f"App {args.app_name!r} does not expose a URL")

    evidence: dict[str, Any] = {
        "schema_version": "quetzal-read-only-collection-v1",
        "collected_at": datetime.now(UTC).isoformat(),
        "policy": {
            "read_only": True,
            "jobs_started": 0,
            "genie_queries_started": 0,
            "quetzal_iq_inferences_started": 0,
            "tokens_persisted": False,
        },
        "app": app,
        "preflight": _get(session, f"{app_url}/api/demo/preflight"),
        "certified_demo": _get(session, f"{app_url}/api/demo/manifest?country={args.country}"),
        "latest_graph": _get(session, f"{app_url}/api/graph/runs/latest"),
        "graph_methodology": _get(session, f"{app_url}/api/graph/methodology"),
    }

    if args.campaign_id:
        campaign = _get(session, f"{app_url}/api/campaigns/drafts/{args.campaign_id}")
        evidence["campaign"] = _campaign_summary(campaign)

    if args.migration_run_id:
        run = client.jobs.get_run(args.migration_run_id).as_dict()
        evidence["migration_run"] = {
            "run_id": run.get("run_id"),
            "job_id": run.get("job_id"),
            "run_name": run.get("run_name"),
            "trigger": run.get("trigger"),
            "state": run.get("state"),
            "tasks": [
                {"task_key": task.get("task_key"), "run_id": task.get("run_id"), "state": task.get("state")}
                for task in run.get("tasks") or []
            ],
        }

    if args.statement_id:
        statement_url = f"{client.config.host.rstrip('/')}/api/2.0/sql/statements/{args.statement_id}"
        evidence["published_models_statement"] = _get(session, statement_url)

    return _mask(evidence)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default="vibe-coding")
    parser.add_argument("--app-name", default="quetzal-command-center")
    parser.add_argument("--country", default="BR")
    parser.add_argument("--campaign-id")
    parser.add_argument("--migration-run-id", type=int)
    parser.add_argument("--statement-id")
    args = parser.parse_args()
    print(json.dumps(collect(args), ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
