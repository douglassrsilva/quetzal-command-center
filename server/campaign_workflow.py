"""Transactional Lakebase repository for governed campaign planning."""

from __future__ import annotations

import hashlib
import json
import uuid
from typing import Any

from .campaign_schema import MIGRATION_VERSION
from .memory import conversation_store

CAMPAIGN_NAMESPACE = uuid.UUID("024b5015-2a39-4b9b-8374-4701b74c35b6")

TRANSITIONS = {
    "DRAFT": frozenset({"PENDING_APPROVAL", "CANCELLED"}),
    "PENDING_APPROVAL": frozenset({"APPROVED", "REJECTED", "CANCELLED"}),
    "APPROVED": frozenset(),
    "REJECTED": frozenset(),
    "CANCELLED": frozenset(),
}


class CampaignStoreUnavailable(RuntimeError):
    """Lakebase is missing or its campaign schema is unavailable."""


class CampaignNotFound(LookupError):
    """The requested campaign does not exist."""


class CampaignConflict(RuntimeError):
    """An idempotency, ownership, transition or version contract failed."""


def _fingerprint(value: dict[str, Any]) -> str:
    body = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(body.encode("utf-8")).hexdigest()


def _campaign_id(actor: str, idempotency_key: str) -> str:
    return "CMP-" + uuid.uuid5(
        CAMPAIGN_NAMESPACE, f"{actor.casefold()}:{idempotency_key}",
    ).hex[:16].upper()


def _event_id(value: str) -> str:
    return "CPE-" + uuid.uuid5(CAMPAIGN_NAMESPACE, value).hex[:16].upper()


class LakebaseCampaignStore:
    @property
    def enabled(self) -> bool:
        return conversation_store.enabled

    def _require_enabled(self) -> None:
        if not self.enabled:
            raise CampaignStoreUnavailable("Lakebase is not configured for campaign planning")

    @staticmethod
    def _dict_cursor(connection):
        from psycopg.rows import dict_row

        return connection.cursor(row_factory=dict_row)

    def schema_status(self) -> dict[str, Any]:
        self._require_enabled()
        with conversation_store._connection() as connection, self._dict_cursor(connection) as cursor:
            cursor.execute(
                """
                SELECT to_regclass('quetzal_app.campaign_drafts') IS NOT NULL AS drafts_ready,
                       to_regclass('quetzal_app.campaign_draft_versions') IS NOT NULL AS versions_ready,
                       to_regclass('quetzal_app.campaign_events') IS NOT NULL AS events_ready,
                       EXISTS (
                         SELECT 1 FROM quetzal_app.schema_migrations WHERE version = %s
                       ) AS migration_ready
                """,
                (MIGRATION_VERSION,),
            )
            row = cursor.fetchone() or {}
        return {
            "version": MIGRATION_VERSION,
            "drafts_ready": bool(row.get("drafts_ready")),
            "versions_ready": bool(row.get("versions_ready")),
            "events_ready": bool(row.get("events_ready")),
            "migration_ready": bool(row.get("migration_ready")),
        }

    @staticmethod
    def _attach_events(cursor, campaigns: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if not campaigns:
            return campaigns
        ids = [item["campaign_id"] for item in campaigns]
        cursor.execute(
            """
            SELECT event_id, campaign_id, event_type, from_status, to_status,
                   actor, note, evidence, created_at
            FROM quetzal_app.campaign_events
            WHERE campaign_id = ANY(%s)
            ORDER BY created_at, event_id
            """,
            (ids,),
        )
        events: dict[str, list[dict[str, Any]]] = {campaign_id: [] for campaign_id in ids}
        for row in cursor.fetchall():
            event = dict(row)
            events.setdefault(event.pop("campaign_id"), []).append(event)
        for item in campaigns:
            item["events"] = events.get(item["campaign_id"], [])
        return campaigns

    def list_for_scope(self, countries: tuple[str, ...], limit: int = 25) -> list[dict[str, Any]]:
        self._require_enabled()
        where = "WHERE country_scope <@ %s::text[]" if countries else ""
        parameters: tuple[Any, ...] = (list(countries), limit) if countries else (limit,)
        with conversation_store._connection() as connection, self._dict_cursor(connection) as cursor:
            cursor.execute(
                f"""
                SELECT campaign_id, source_draft_id, title, requested_country,
                       country_scope, objective, channel, source_theme_id, status,
                       requested_by, assigned_to, decided_by, created_at, updated_at,
                       submitted_at, decided_at, cancelled_at, audience_fingerprint,
                       selected_customers, estimated_net_impact_usd, estimated_roi_pct,
                       break_even_response_rate_pct, campaign_sent, version, snapshot_version
                FROM quetzal_app.campaign_drafts
                {where}
                ORDER BY CASE status
                           WHEN 'PENDING_APPROVAL' THEN 0
                           WHEN 'DRAFT' THEN 1
                           WHEN 'APPROVED' THEN 2
                           ELSE 3 END,
                         updated_at DESC, campaign_id DESC
                LIMIT %s
                """,
                parameters,
            )
            return self._attach_events(cursor, [dict(row) for row in cursor.fetchall()])

    def get_campaign(self, campaign_id: str) -> dict[str, Any]:
        self._require_enabled()
        with conversation_store._connection() as connection, self._dict_cursor(connection) as cursor:
            cursor.execute(
                "SELECT * FROM quetzal_app.campaign_drafts WHERE campaign_id = %s",
                (campaign_id,),
            )
            row = cursor.fetchone()
            if not row:
                raise CampaignNotFound(campaign_id)
            return self._attach_events(cursor, [dict(row)])[0]

    @staticmethod
    def _campaign_values(snapshot: dict[str, Any], campaign_request: dict[str, Any]) -> dict[str, Any]:
        selected = int(snapshot.get("reconciliation", {}).get("selected_customers") or 0)
        if selected <= 0:
            raise CampaignConflict("An empty audience cannot enter the operational campaign workflow")
        scope = [str(item) for item in (snapshot.get("scope", {}).get("effective_countries") or [])]
        if not scope:
            raise CampaignConflict("The campaign has no governed territorial scope")
        impact = snapshot.get("impact") or {}
        return {
            "source_draft_id": str(snapshot.get("draft_id") or ""),
            "requested_country": str(campaign_request.get("country") or "ALL"),
            "country_scope": scope,
            "objective": str(campaign_request.get("objective") or "RETENTION"),
            "channel": str(campaign_request.get("channel") or "EMAIL"),
            "source_theme_id": campaign_request.get("source_theme_id"),
            "audience_fingerprint": str(snapshot.get("reconciliation", {}).get("audience_fingerprint") or ""),
            "selected_customers": selected,
            "estimated_net_impact_usd": float(impact.get("estimated_net_impact_usd") or 0),
            "estimated_roi_pct": impact.get("estimated_roi_pct"),
            "break_even_response_rate_pct": impact.get("break_even_response_rate_pct"),
        }

    def create_campaign(
        self,
        *,
        actor: str,
        title: str,
        assigned_to: str,
        campaign_request: dict[str, Any],
        snapshot: dict[str, Any],
        idempotency_key: str,
    ) -> dict[str, Any]:
        self._require_enabled()
        values = self._campaign_values(snapshot, campaign_request)
        campaign_id = _campaign_id(actor, idempotency_key)
        stored_key = f"create:{actor.casefold()}:{idempotency_key}"
        request = {
            "actor": actor,
            "title": title,
            "assigned_to": assigned_to,
            "campaign_request": campaign_request,
            "source_draft_id": values["source_draft_id"],
        }
        fingerprint = _fingerprint(request)
        snapshot_fingerprint = _fingerprint(snapshot)
        with conversation_store._connection() as connection, self._dict_cursor(connection) as cursor:
            cursor.execute(
                """
                INSERT INTO quetzal_app.campaign_drafts (
                  campaign_id, source_draft_id, title, requested_country, country_scope,
                  objective, channel, source_theme_id, status, requested_by, assigned_to,
                  audience_fingerprint, selected_customers, estimated_net_impact_usd,
                  estimated_roi_pct, break_even_response_rate_pct, campaign_request,
                  campaign_snapshot, idempotency_key, request_fingerprint
                ) VALUES (
                  %s, %s, %s, %s, %s, %s, %s, %s, 'DRAFT', %s, %s,
                  %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s, %s
                )
                ON CONFLICT (idempotency_key) DO NOTHING
                RETURNING campaign_id
                """,
                (
                    campaign_id, values["source_draft_id"], title,
                    values["requested_country"], values["country_scope"],
                    values["objective"], values["channel"], values["source_theme_id"],
                    actor, assigned_to, values["audience_fingerprint"],
                    values["selected_customers"], values["estimated_net_impact_usd"],
                    values["estimated_roi_pct"], values["break_even_response_rate_pct"],
                    json.dumps(campaign_request, ensure_ascii=False, default=str),
                    json.dumps(snapshot, ensure_ascii=False, default=str),
                    stored_key, fingerprint,
                ),
            )
            inserted = cursor.fetchone()
            cursor.execute(
                "SELECT campaign_id, request_fingerprint FROM quetzal_app.campaign_drafts WHERE idempotency_key = %s",
                (stored_key,),
            )
            existing = cursor.fetchone()
            if not existing or existing["request_fingerprint"] != fingerprint:
                connection.rollback()
                raise CampaignConflict("The idempotency key was already used for a different campaign")
            campaign_id = existing["campaign_id"]
            if inserted:
                cursor.execute(
                    """
                    INSERT INTO quetzal_app.campaign_draft_versions (
                      campaign_id, snapshot_version, source_draft_id, actor,
                      campaign_request, campaign_snapshot, snapshot_fingerprint
                    ) VALUES (%s, 1, %s, %s, %s::jsonb, %s::jsonb, %s)
                    """,
                    (
                        campaign_id, values["source_draft_id"], actor,
                        json.dumps(campaign_request, ensure_ascii=False, default=str),
                        json.dumps(snapshot, ensure_ascii=False, default=str),
                        snapshot_fingerprint,
                    ),
                )
                event_key = f"event:{stored_key}"
                cursor.execute(
                    """
                    INSERT INTO quetzal_app.campaign_events (
                      event_id, campaign_id, event_type, from_status, to_status,
                      actor, note, evidence, idempotency_key, request_fingerprint
                    ) VALUES (%s, %s, 'CAMPAIGN_SAVED', NULL, 'DRAFT', %s, %s,
                              %s::jsonb, %s, %s)
                    """,
                    (
                        _event_id(event_key), campaign_id, actor,
                        "Borrador gobernado guardado en Lakebase.",
                        json.dumps({
                            "source_draft_id": values["source_draft_id"],
                            "audience_fingerprint": values["audience_fingerprint"],
                            "campaign_sent": False,
                        }),
                        event_key, _fingerprint({"campaign_id": campaign_id, "event": "CAMPAIGN_SAVED"}),
                    ),
                )
            connection.commit()
            cursor.execute(
                "SELECT * FROM quetzal_app.campaign_drafts WHERE campaign_id = %s",
                (campaign_id,),
            )
            return self._attach_events(cursor, [dict(cursor.fetchone())])[0]

    def revise_campaign(
        self,
        *,
        campaign_id: str,
        expected_version: int,
        actor: str,
        title: str | None,
        assigned_to: str | None,
        note: str,
        campaign_request: dict[str, Any],
        snapshot: dict[str, Any],
        idempotency_key: str,
    ) -> dict[str, Any]:
        self._require_enabled()
        values = self._campaign_values(snapshot, campaign_request)
        event_key = f"revision:{actor.casefold()}:{idempotency_key}"
        request = {
            "campaign_id": campaign_id, "expected_version": expected_version,
            "actor": actor, "title": title, "assigned_to": assigned_to,
            "note": note, "campaign_request": campaign_request,
            "source_draft_id": values["source_draft_id"],
        }
        fingerprint = _fingerprint(request)
        snapshot_fingerprint = _fingerprint(snapshot)
        with conversation_store._connection() as connection, self._dict_cursor(connection) as cursor:
            cursor.execute(
                "SELECT request_fingerprint FROM quetzal_app.campaign_events WHERE idempotency_key = %s",
                (event_key,),
            )
            previous = cursor.fetchone()
            if previous:
                if previous["request_fingerprint"] != fingerprint:
                    raise CampaignConflict("The idempotency key was already used for a different revision")
                cursor.execute(
                    "SELECT * FROM quetzal_app.campaign_drafts WHERE campaign_id = %s",
                    (campaign_id,),
                )
                row = cursor.fetchone()
                if not row:
                    raise CampaignNotFound(campaign_id)
                return self._attach_events(cursor, [dict(row)])[0]

            cursor.execute(
                "SELECT * FROM quetzal_app.campaign_drafts WHERE campaign_id = %s FOR UPDATE",
                (campaign_id,),
            )
            current = cursor.fetchone()
            if not current:
                raise CampaignNotFound(campaign_id)
            if current["status"] != "DRAFT":
                raise CampaignConflict("Only a DRAFT campaign can receive a new audience version")
            if current["version"] != expected_version:
                raise CampaignConflict(
                    f"Campaign version changed from {expected_version} to {current['version']}; reload before retrying"
                )
            if actor.casefold() not in {
                current["requested_by"].casefold(), current["assigned_to"].casefold(),
            }:
                raise CampaignConflict("Only the requester or owner can revise this campaign")
            next_snapshot_version = int(current["snapshot_version"]) + 1
            cursor.execute(
                """
                UPDATE quetzal_app.campaign_drafts SET
                  source_draft_id = %s, title = COALESCE(%s, title),
                  requested_country = %s, country_scope = %s, objective = %s,
                  channel = %s, source_theme_id = %s,
                  assigned_to = COALESCE(%s, assigned_to), audience_fingerprint = %s,
                  selected_customers = %s, estimated_net_impact_usd = %s,
                  estimated_roi_pct = %s, break_even_response_rate_pct = %s,
                  campaign_request = %s::jsonb, campaign_snapshot = %s::jsonb,
                  snapshot_version = %s, version = version + 1, updated_at = now()
                WHERE campaign_id = %s
                """,
                (
                    values["source_draft_id"], title, values["requested_country"],
                    values["country_scope"], values["objective"], values["channel"],
                    values["source_theme_id"], assigned_to, values["audience_fingerprint"],
                    values["selected_customers"], values["estimated_net_impact_usd"],
                    values["estimated_roi_pct"], values["break_even_response_rate_pct"],
                    json.dumps(campaign_request, ensure_ascii=False, default=str),
                    json.dumps(snapshot, ensure_ascii=False, default=str),
                    next_snapshot_version, campaign_id,
                ),
            )
            cursor.execute(
                """
                INSERT INTO quetzal_app.campaign_draft_versions (
                  campaign_id, snapshot_version, source_draft_id, actor,
                  campaign_request, campaign_snapshot, snapshot_fingerprint
                ) VALUES (%s, %s, %s, %s, %s::jsonb, %s::jsonb, %s)
                """,
                (
                    campaign_id, next_snapshot_version, values["source_draft_id"], actor,
                    json.dumps(campaign_request, ensure_ascii=False, default=str),
                    json.dumps(snapshot, ensure_ascii=False, default=str),
                    snapshot_fingerprint,
                ),
            )
            cursor.execute(
                """
                INSERT INTO quetzal_app.campaign_events (
                  event_id, campaign_id, event_type, from_status, to_status,
                  actor, note, evidence, idempotency_key, request_fingerprint
                ) VALUES (%s, %s, 'DRAFT_REVISED', 'DRAFT', 'DRAFT', %s, %s,
                          %s::jsonb, %s, %s)
                """,
                (
                    _event_id(event_key), campaign_id, actor, note,
                    json.dumps({
                        "source_draft_id": values["source_draft_id"],
                        "snapshot_version": next_snapshot_version,
                        "audience_fingerprint": values["audience_fingerprint"],
                        "campaign_sent": False,
                    }),
                    event_key, fingerprint,
                ),
            )
            connection.commit()
            cursor.execute(
                "SELECT * FROM quetzal_app.campaign_drafts WHERE campaign_id = %s",
                (campaign_id,),
            )
            return self._attach_events(cursor, [dict(cursor.fetchone())])[0]

    def transition_campaign(
        self,
        *,
        campaign_id: str,
        to_status: str,
        expected_version: int,
        actor: str,
        note: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        self._require_enabled()
        request = {
            "campaign_id": campaign_id, "to_status": to_status,
            "expected_version": expected_version, "actor": actor, "note": note,
        }
        fingerprint = _fingerprint(request)
        event_key = f"transition:{actor.casefold()}:{idempotency_key}"
        with conversation_store._connection() as connection, self._dict_cursor(connection) as cursor:
            cursor.execute(
                "SELECT request_fingerprint FROM quetzal_app.campaign_events WHERE idempotency_key = %s",
                (event_key,),
            )
            previous = cursor.fetchone()
            if previous:
                if previous["request_fingerprint"] != fingerprint:
                    raise CampaignConflict("The idempotency key was already used for a different transition")
                cursor.execute(
                    "SELECT * FROM quetzal_app.campaign_drafts WHERE campaign_id = %s",
                    (campaign_id,),
                )
                row = cursor.fetchone()
                if not row:
                    raise CampaignNotFound(campaign_id)
                return self._attach_events(cursor, [dict(row)])[0]

            cursor.execute(
                "SELECT * FROM quetzal_app.campaign_drafts WHERE campaign_id = %s FOR UPDATE",
                (campaign_id,),
            )
            current = cursor.fetchone()
            if not current:
                raise CampaignNotFound(campaign_id)
            from_status = current["status"]
            if current["version"] != expected_version:
                raise CampaignConflict(
                    f"Campaign version changed from {expected_version} to {current['version']}; reload before retrying"
                )
            if to_status not in TRANSITIONS.get(from_status, frozenset()):
                raise CampaignConflict(f"Transition {from_status} -> {to_status} is not allowed")
            if to_status in {"APPROVED", "REJECTED"} and current["requested_by"].casefold() == actor.casefold():
                raise CampaignConflict("The requester cannot decide their own campaign")
            if to_status in {"PENDING_APPROVAL", "CANCELLED"} and actor.casefold() not in {
                current["requested_by"].casefold(), current["assigned_to"].casefold(),
            }:
                raise CampaignConflict("Only the requester or owner can submit or cancel this campaign")

            cursor.execute(
                """
                UPDATE quetzal_app.campaign_drafts SET
                  status = %s,
                  submitted_at = CASE WHEN %s = 'PENDING_APPROVAL' THEN now() ELSE submitted_at END,
                  decided_by = CASE WHEN %s IN ('APPROVED','REJECTED') THEN %s ELSE decided_by END,
                  decided_at = CASE WHEN %s IN ('APPROVED','REJECTED') THEN now() ELSE decided_at END,
                  cancelled_at = CASE WHEN %s = 'CANCELLED' THEN now() ELSE cancelled_at END,
                  updated_at = now(), version = version + 1
                WHERE campaign_id = %s
                """,
                (to_status, to_status, to_status, actor, to_status, to_status, campaign_id),
            )
            cursor.execute(
                """
                INSERT INTO quetzal_app.campaign_events (
                  event_id, campaign_id, event_type, from_status, to_status,
                  actor, note, evidence, idempotency_key, request_fingerprint
                ) VALUES (%s, %s, %s, %s, %s, %s, %s,
                          '{"campaign_sent":false}'::jsonb, %s, %s)
                """,
                (
                    _event_id(event_key), campaign_id, f"STATUS_{to_status}",
                    from_status, to_status, actor, note, event_key, fingerprint,
                ),
            )
            connection.commit()
            cursor.execute(
                "SELECT * FROM quetzal_app.campaign_drafts WHERE campaign_id = %s",
                (campaign_id,),
            )
            return self._attach_events(cursor, [dict(cursor.fetchone())])[0]


campaign_store = LakebaseCampaignStore()
