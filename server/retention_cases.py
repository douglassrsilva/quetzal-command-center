"""Transactional Lakebase repository for customer-retention cases."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from .memory import conversation_store
from .retention_schema import MIGRATION_VERSION

CASE_NAMESPACE = uuid.UUID("7f4b9f98-cafd-4da4-9105-c9ca231f943c")

TRANSITIONS = {
    "PENDING_APPROVAL": frozenset({"APPROVED", "REJECTED"}),
    "APPROVED": frozenset({"IN_PROGRESS"}),
    "IN_PROGRESS": frozenset({"RESOLVED"}),
    "RESOLVED": frozenset({"CLOSED"}),
    "REJECTED": frozenset(),
    "CLOSED": frozenset(),
}

SLA_HOURS = {"CRITICAL": 4, "HIGH": 12, "MEDIUM": 24, "LOW": 72}


class RetentionStoreUnavailable(RuntimeError):
    """Lakebase is missing or its operational schema is not reachable."""


class RetentionCaseNotFound(LookupError):
    """The requested operational case does not exist."""


class RetentionConflict(RuntimeError):
    """An idempotency, transition or optimistic-concurrency contract failed."""


def _fingerprint(value: dict[str, Any]) -> str:
    body = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _event_id(idempotency_key: str) -> str:
    return "RCE-" + uuid.uuid5(CASE_NAMESPACE, idempotency_key).hex[:16].upper()


def _case_id(actor: str, idempotency_key: str) -> str:
    return "RET-" + uuid.uuid5(CASE_NAMESPACE, f"{actor.casefold()}:{idempotency_key}").hex[:16].upper()


class LakebaseRetentionCaseStore:
    @property
    def enabled(self) -> bool:
        return conversation_store.enabled

    def _require_enabled(self) -> None:
        if not self.enabled:
            raise RetentionStoreUnavailable("Lakebase is not configured for the retention workflow")

    @staticmethod
    def _dict_cursor(connection):
        from psycopg.rows import dict_row

        return connection.cursor(row_factory=dict_row)

    def schema_status(self) -> dict[str, Any]:
        self._require_enabled()
        with conversation_store._connection() as connection, self._dict_cursor(connection) as cursor:
            cursor.execute(
                """
                SELECT to_regclass('quetzal_app.retention_cases') IS NOT NULL AS cases_ready,
                       to_regclass('quetzal_app.retention_case_events') IS NOT NULL AS events_ready,
                       EXISTS (
                         SELECT 1 FROM quetzal_app.schema_migrations WHERE version = %s
                       ) AS migration_ready
                """,
                (MIGRATION_VERSION,),
            )
            row = cursor.fetchone() or {}
        return {
            "version": MIGRATION_VERSION,
            "cases_ready": bool(row.get("cases_ready")),
            "events_ready": bool(row.get("events_ready")),
            "migration_ready": bool(row.get("migration_ready")),
        }

    @staticmethod
    def _attach_events(cursor, cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not cases:
            return cases
        ids = [item["case_id"] for item in cases]
        cursor.execute(
            """
            SELECT event_id, case_id, event_type, from_status, to_status,
                   actor, note, evidence, created_at
            FROM quetzal_app.retention_case_events
            WHERE case_id = ANY(%s)
            ORDER BY created_at, event_id
            """,
            (ids,),
        )
        events: dict[str, list[dict[str, Any]]] = {case_id: [] for case_id in ids}
        for row in cursor.fetchall():
            event = dict(row)
            events.setdefault(event.pop("case_id"), []).append(event)
        for item in cases:
            item["events"] = events.get(item["case_id"], [])
        return cases

    def list_for_customer(self, customer_id: str, limit: int = 25) -> list[dict[str, Any]]:
        self._require_enabled()
        with conversation_store._connection() as connection, self._dict_cursor(connection) as cursor:
            cursor.execute(
                """
                SELECT * FROM quetzal_app.retention_cases
                WHERE customer_id = %s
                ORDER BY updated_at DESC, case_id DESC
                LIMIT %s
                """,
                (customer_id, limit),
            )
            cases = [dict(row) for row in cursor.fetchall()]
            return self._attach_events(cursor, cases)

    def list_for_scope(self, countries: tuple[str, ...], limit: int = 25) -> list[dict[str, Any]]:
        self._require_enabled()
        where = "WHERE country = ANY(%s)" if countries else ""
        parameters: tuple[Any, ...] = (list(countries), limit) if countries else (limit,)
        with conversation_store._connection() as connection, self._dict_cursor(connection) as cursor:
            cursor.execute(
                f"""
                SELECT * FROM quetzal_app.retention_cases
                {where}
                ORDER BY CASE status
                           WHEN 'PENDING_APPROVAL' THEN 0
                           WHEN 'APPROVED' THEN 1
                           WHEN 'IN_PROGRESS' THEN 2
                           ELSE 3 END,
                         sla_due_at, updated_at DESC
                LIMIT %s
                """,
                parameters,
            )
            cases = [dict(row) for row in cursor.fetchall()]
            return self._attach_events(cursor, cases)

    def get_case(self, case_id: str) -> dict[str, Any]:
        self._require_enabled()
        with conversation_store._connection() as connection, self._dict_cursor(connection) as cursor:
            cursor.execute("SELECT * FROM quetzal_app.retention_cases WHERE case_id = %s", (case_id,))
            row = cursor.fetchone()
            if not row:
                raise RetentionCaseNotFound(case_id)
            return self._attach_events(cursor, [dict(row)])[0]

    def create_case(
        self,
        *,
        actor: str,
        customer: dict[str, Any],
        model: dict[str, Any],
        recommendation: dict[str, Any],
        idempotency_key: str,
    ) -> dict[str, Any]:
        self._require_enabled()
        priority = str(recommendation["priority"])
        case_id = _case_id(actor, idempotency_key)
        request = {
            "actor": actor,
            "customer_id": customer["cliente_id"],
            "model_run_id": model["model_run_id"],
            "recommendation": recommendation,
        }
        fingerprint = _fingerprint(request)
        due_at = datetime.now(UTC) + timedelta(hours=SLA_HOURS[priority])
        create_event_key = f"create:{actor.casefold()}:{idempotency_key}"
        with conversation_store._connection() as connection, self._dict_cursor(connection) as cursor:
            cursor.execute(
                """
                INSERT INTO quetzal_app.retention_cases (
                  case_id, customer_id, country, status, priority, title, rationale,
                  recommendation_type, source_recommendation_id, requested_by,
                  assigned_to, sla_due_at, churn_probability, churn_model_name,
                  churn_model_version, churn_model_run_id, churn_scored_at,
                  customer_snapshot, recommendation_snapshot, idempotency_key,
                  request_fingerprint
                ) VALUES (
                  %s, %s, %s, 'PENDING_APPROVAL', %s, %s, %s, %s, %s, %s,
                  %s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s
                )
                ON CONFLICT (idempotency_key) DO NOTHING
                RETURNING case_id
                """,
                (
                    case_id,
                    customer["cliente_id"],
                    customer["pais_codigo"],
                    priority,
                    recommendation["title"],
                    recommendation["rationale"],
                    recommendation["recommendation_type"],
                    recommendation.get("source_recommendation_id"),
                    actor,
                    recommendation.get("assignee") or actor,
                    due_at,
                    model["churn_probability"],
                    model["model_name"],
                    str(model["model_version"]),
                    model["model_run_id"],
                    model.get("scored_at"),
                    json.dumps(customer, ensure_ascii=False, default=str),
                    json.dumps(recommendation, ensure_ascii=False, default=str),
                    idempotency_key,
                    fingerprint,
                ),
            )
            inserted = cursor.fetchone()
            cursor.execute(
                "SELECT case_id, request_fingerprint FROM quetzal_app.retention_cases WHERE idempotency_key = %s",
                (idempotency_key,),
            )
            existing = cursor.fetchone()
            if not existing or existing["request_fingerprint"] != fingerprint:
                connection.rollback()
                raise RetentionConflict("The idempotency key was already used for a different request")
            case_id = existing["case_id"]
            if inserted:
                event_fingerprint = _fingerprint({"case_id": case_id, "status": "PENDING_APPROVAL", "actor": actor})
                cursor.execute(
                    """
                    INSERT INTO quetzal_app.retention_case_events (
                      event_id, case_id, event_type, from_status, to_status,
                      actor, note, evidence, idempotency_key, request_fingerprint
                    ) VALUES (%s, %s, 'CASE_CREATED', NULL, 'PENDING_APPROVAL',
                              %s, %s, %s::jsonb, %s, %s)
                    ON CONFLICT (idempotency_key) DO NOTHING
                    """,
                    (
                        _event_id(create_event_key),
                        case_id,
                        actor,
                        recommendation.get("note") or recommendation["rationale"],
                        json.dumps({"model_run_id": model["model_run_id"]}),
                        create_event_key,
                        event_fingerprint,
                    ),
                )
            connection.commit()
            cursor.execute("SELECT * FROM quetzal_app.retention_cases WHERE case_id = %s", (case_id,))
            return self._attach_events(cursor, [dict(cursor.fetchone())])[0]

    def transition_case(
        self,
        *,
        case_id: str,
        to_status: str,
        expected_version: int,
        actor: str,
        note: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        self._require_enabled()
        request = {
            "case_id": case_id,
            "to_status": to_status,
            "expected_version": expected_version,
            "actor": actor,
            "note": note,
        }
        fingerprint = _fingerprint(request)
        event_key = f"transition:{actor.casefold()}:{idempotency_key}"
        with conversation_store._connection() as connection, self._dict_cursor(connection) as cursor:
            cursor.execute(
                "SELECT request_fingerprint FROM quetzal_app.retention_case_events WHERE idempotency_key = %s",
                (event_key,),
            )
            previous = cursor.fetchone()
            if previous:
                if previous["request_fingerprint"] != fingerprint:
                    raise RetentionConflict("The idempotency key was already used for a different transition")
                cursor.execute("SELECT * FROM quetzal_app.retention_cases WHERE case_id = %s", (case_id,))
                row = cursor.fetchone()
                if not row:
                    raise RetentionCaseNotFound(case_id)
                return self._attach_events(cursor, [dict(row)])[0]

            cursor.execute("SELECT * FROM quetzal_app.retention_cases WHERE case_id = %s FOR UPDATE", (case_id,))
            current = cursor.fetchone()
            if not current:
                raise RetentionCaseNotFound(case_id)
            from_status = current["status"]
            if current["version"] != expected_version:
                raise RetentionConflict(
                    f"Case version changed from {expected_version} to {current['version']}; reload before retrying"
                )
            if to_status not in TRANSITIONS.get(from_status, frozenset()):
                raise RetentionConflict(f"Transition {from_status} -> {to_status} is not allowed")
            if to_status in {"APPROVED", "REJECTED"} and current["requested_by"].casefold() == actor.casefold():
                raise RetentionConflict("The requester cannot decide their own retention case")

            cursor.execute(
                """
                UPDATE quetzal_app.retention_cases SET
                  status = %s,
                  approved_by = CASE WHEN %s = 'APPROVED' THEN %s ELSE approved_by END,
                  approved_at = CASE WHEN %s = 'APPROVED' THEN now() ELSE approved_at END,
                  started_at = CASE WHEN %s = 'IN_PROGRESS' THEN now() ELSE started_at END,
                  resolved_at = CASE WHEN %s = 'RESOLVED' THEN now() ELSE resolved_at END,
                  closed_at = CASE WHEN %s = 'CLOSED' THEN now() ELSE closed_at END,
                  updated_at = now(), version = version + 1
                WHERE case_id = %s
                """,
                (to_status, to_status, actor, to_status, to_status, to_status, to_status, case_id),
            )
            cursor.execute(
                """
                INSERT INTO quetzal_app.retention_case_events (
                  event_id, case_id, event_type, from_status, to_status,
                  actor, note, evidence, idempotency_key, request_fingerprint
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, '{}'::jsonb, %s, %s)
                """,
                (
                    _event_id(event_key),
                    case_id,
                    f"STATUS_{to_status}",
                    from_status,
                    to_status,
                    actor,
                    note,
                    event_key,
                    fingerprint,
                ),
            )
            connection.commit()
            cursor.execute("SELECT * FROM quetzal_app.retention_cases WHERE case_id = %s", (case_id,))
            return self._attach_events(cursor, [dict(cursor.fetchone())])[0]


retention_case_store = LakebaseRetentionCaseStore()
