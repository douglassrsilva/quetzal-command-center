"""Apply the additive governed-campaign workflow to Lakebase Autoscaling."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

import psycopg
from databricks.sdk import WorkspaceClient

_SCRIPT_PATH = globals().get("__file__") or globals().get("filename")
if not _SCRIPT_PATH:
    raise RuntimeError("The migration script path is unavailable")
ROOT = Path(_SCRIPT_PATH).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.campaign_schema import DDL_STATEMENTS, MIGRATION_VERSION

ROLE_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{1,127}$")


def _args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", required=True)
    parser.add_argument("--branch", default="production")
    parser.add_argument("--endpoint", default="primary")
    parser.add_argument("--database", required=True)
    parser.add_argument("--host", required=True)
    parser.add_argument("--app-role", required=True)
    return parser.parse_args()


def _quoted_role(value: str) -> str:
    if not ROLE_PATTERN.fullmatch(value):
        raise ValueError("app role contains unsupported characters")
    return '"' + value.replace('"', '""') + '"'


def main() -> None:
    args = _args()
    client = WorkspaceClient()
    endpoint = f"projects/{args.project}/branches/{args.branch}/endpoints/{args.endpoint}"
    credential = client.postgres.generate_database_credential(endpoint)
    principal = client.current_user.me()
    user = getattr(principal, "user_name", None)
    if not credential.token or not user:
        raise RuntimeError("Lakebase OAuth identity is incomplete")
    checksum = hashlib.sha256("\n".join(DDL_STATEMENTS).encode("utf-8")).hexdigest()
    role = _quoted_role(args.app_role)

    with psycopg.connect(
        host=args.host,
        port=5432,
        dbname=args.database,
        user=user,
        password=credential.token,
        sslmode="require",
        connect_timeout=20,
    ) as connection, connection.cursor() as cursor:
        for statement in DDL_STATEMENTS:
            cursor.execute(statement)
        cursor.execute(
            "SELECT checksum FROM quetzal_app.schema_migrations WHERE version = %s",
            (MIGRATION_VERSION,),
        )
        existing = cursor.fetchone()
        if existing and existing[0] != checksum:
            raise RuntimeError(f"Migration {MIGRATION_VERSION} checksum mismatch")
        cursor.execute(
            """
            INSERT INTO quetzal_app.schema_migrations (version, checksum, applied_by)
            VALUES (%s, %s, %s)
            ON CONFLICT (version) DO NOTHING
            """,
            (MIGRATION_VERSION, checksum, user),
        )
        cursor.execute(f"GRANT USAGE ON SCHEMA quetzal_app TO {role}")
        cursor.execute(f"GRANT SELECT, INSERT, UPDATE ON quetzal_app.campaign_drafts TO {role}")
        cursor.execute(f"GRANT SELECT, INSERT ON quetzal_app.campaign_draft_versions TO {role}")
        cursor.execute(f"GRANT SELECT, INSERT ON quetzal_app.campaign_events TO {role}")
        cursor.execute(f"GRANT SELECT ON quetzal_app.schema_migrations TO {role}")
        connection.commit()
    print(json.dumps({
        "status": "applied" if not existing else "already_applied",
        "migration": MIGRATION_VERSION,
        "checksum": checksum,
        "database": args.database,
        "app_role": args.app_role,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
