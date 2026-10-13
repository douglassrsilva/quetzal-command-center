"""Conversation ledger for Quetzal IQ backed by Lakebase Autoscaling.

Managed Agent Memory is intentionally used for durable semantic memories. This
store keeps the recoverable short-term transcript, sources and tool trace.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

log = logging.getLogger("quetzal.memory")
SESSION_NAMESPACE = uuid.UUID("966e9e9d-39cc-4bad-b9ce-e08f3a69f844")


DDL = """
CREATE SCHEMA IF NOT EXISTS quetzal_app;

CREATE TABLE IF NOT EXISTS quetzal_app.chat_sessions (
  session_id UUID PRIMARY KEY,
  external_conversation_id TEXT NOT NULL,
  actor_id TEXT NOT NULL,
  title TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'active' CHECK (status IN ('active','closed')),
  context JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_activity_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (actor_id, external_conversation_id)
);
CREATE INDEX IF NOT EXISTS ix_quetzal_sessions_actor_activity
  ON quetzal_app.chat_sessions (actor_id, last_activity_at DESC);

CREATE TABLE IF NOT EXISTS quetzal_app.chat_messages (
  message_id UUID PRIMARY KEY,
  session_id UUID NOT NULL REFERENCES quetzal_app.chat_sessions(session_id) ON DELETE CASCADE,
  sequence_number BIGINT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('user','assistant')),
  content TEXT NOT NULL,
  model_endpoint TEXT,
  trace_id TEXT,
  citations JSONB NOT NULL DEFAULT '[]'::jsonb,
  tools JSONB NOT NULL DEFAULT '[]'::jsonb,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (session_id, sequence_number)
);
CREATE INDEX IF NOT EXISTS ix_quetzal_messages_session_sequence
  ON quetzal_app.chat_messages (session_id, sequence_number);
CREATE INDEX IF NOT EXISTS ix_quetzal_messages_trace
  ON quetzal_app.chat_messages (trace_id) WHERE trace_id IS NOT NULL;

COMMENT ON SCHEMA quetzal_app IS
  'Quetzal IQ LTAP ledger. Semantic long-term memory remains in Managed Agent Memory.';
"""


@dataclass(frozen=True)
class MemoryStatus:
    status: str
    store: str = "lakebase"
    restored_messages: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "store": self.store,
            "restored_messages": self.restored_messages,
        }


class LakebaseConversationStore:
    def __init__(self) -> None:
        self.project = os.getenv("QUETZAL_LAKEBASE_PROJECT", "").strip()
        self.branch = os.getenv("QUETZAL_LAKEBASE_BRANCH", "production").strip()
        self.endpoint = os.getenv("QUETZAL_LAKEBASE_ENDPOINT", "primary").strip()
        self.database = os.getenv("QUETZAL_LAKEBASE_DATABASE", "").strip()
        self.host = os.getenv("QUETZAL_LAKEBASE_HOST", "").strip()
        self.required = os.getenv("QUETZAL_LAKEBASE_REQUIRED", "false").lower() == "true"
        self._schema_ready = False
        self._schema_lock = threading.Lock()

    @property
    def enabled(self) -> bool:
        return bool(self.project and self.database and self.host)

    @staticmethod
    def session_id(actor: str, conversation_id: str) -> uuid.UUID:
        return uuid.uuid5(SESSION_NAMESPACE, f"{actor.lower()}\x1f{conversation_id}")

    @contextmanager
    def _connection(self) -> Iterator[Any]:
        if not self.enabled:
            raise RuntimeError("Lakebase is not configured")
        import psycopg
        from databricks.sdk import WorkspaceClient

        client = WorkspaceClient()
        endpoint_name = (
            f"projects/{self.project}/branches/{self.branch}/endpoints/{self.endpoint}"
        )
        # Lakebase Autoscaling requires a database credential minted for the
        # endpoint; the generic workspace bearer token fails SASL.
        credential = client.postgres.generate_database_credential(endpoint_name)
        token = credential.token or ""
        principal = client.current_user.me()
        # Lakebase creates an OAuth role named after the Databricks App service
        # principal client ID. current_user.user_name is a display name for a
        # service principal and is not a valid PostgreSQL OAuth role.
        user = (
            os.getenv("QUETZAL_LAKEBASE_USER", "").strip()
            or os.getenv("DATABRICKS_CLIENT_ID", "").strip()
            or getattr(principal, "application_id", None)
            or getattr(principal, "user_name", None)
        )
        if not token or not user:
            raise RuntimeError("Lakebase OAuth identity is incomplete")
        connection = psycopg.connect(
            host=self.host,
            port=5432,
            dbname=self.database,
            user=user,
            password=token,
            sslmode="require",
            connect_timeout=12,
        )
        try:
            yield connection
        finally:
            connection.close()

    def _ensure_schema(self) -> None:
        if self._schema_ready:
            return
        with self._schema_lock:
            if self._schema_ready:
                return
            with self._connection() as connection, connection.cursor() as cursor:
                cursor.execute(DDL)
                connection.commit()
            self._schema_ready = True

    def restore(self, actor: str, conversation_id: str, limit: int = 24) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        self._ensure_schema()
        session_id = self.session_id(actor, conversation_id)
        with self._connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT role, content, tools
                FROM quetzal_app.chat_messages
                WHERE session_id = %s
                ORDER BY sequence_number DESC
                LIMIT %s
                """,
                (session_id, limit),
            )
            rows = list(reversed(cursor.fetchall()))
        return [{
            "role": role,
            "text": content,
            "tools": [
                item if isinstance(item, str) else item.get("tool", "")
                for item in (tools or [])
                if isinstance(item, (str, dict))
            ],
        } for role, content, tools in rows]

    def save_exchange(
        self,
        *,
        actor: str,
        conversation_id: str,
        question: str,
        answer: str,
        trace_id: str,
        model: str,
        citations: list[dict[str, str]],
        tools: list[dict[str, str]],
        metadata: dict[str, Any],
    ) -> None:
        if not self.enabled:
            return
        self._ensure_schema()
        session_id = self.session_id(actor, conversation_id)
        title = question.strip()[:120] or "Nueva conversación"
        with self._connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO quetzal_app.chat_sessions (
                  session_id, external_conversation_id, actor_id, title, context
                ) VALUES (%s, %s, %s, %s, %s::jsonb)
                ON CONFLICT (session_id) DO UPDATE SET
                  updated_at = now(), last_activity_at = now(),
                  context = quetzal_app.chat_sessions.context || EXCLUDED.context
                """,
                (session_id, conversation_id, actor, title, json.dumps(metadata)),
            )
            cursor.execute(
                "SELECT COALESCE(MAX(sequence_number), 0) FROM quetzal_app.chat_messages WHERE session_id = %s",
                (session_id,),
            )
            sequence = int(cursor.fetchone()[0])
            values = [
                ("user", question, [], [], {}),
                ("assistant", answer, citations, tools, metadata),
            ]
            for offset, (role, content, item_citations, item_tools, item_metadata) in enumerate(values, start=1):
                current_sequence = sequence + offset
                message_id = uuid.uuid5(session_id, f"{current_sequence}:{role}:{trace_id}")
                cursor.execute(
                    """
                    INSERT INTO quetzal_app.chat_messages (
                      message_id, session_id, sequence_number, role, content,
                      model_endpoint, trace_id, citations, tools, metadata
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s::jsonb, %s::jsonb, %s::jsonb)
                    ON CONFLICT (message_id) DO NOTHING
                    """,
                    (
                        message_id, session_id, current_sequence, role, content,
                        model if role == "assistant" else None,
                        trace_id if role == "assistant" else None,
                        json.dumps(item_citations, ensure_ascii=False),
                        json.dumps(item_tools, ensure_ascii=False),
                        json.dumps(item_metadata, ensure_ascii=False),
                    ),
                )
            connection.commit()

    def list_sessions(self, actor: str, limit: int = 12) -> list[dict[str, Any]]:
        if not self.enabled:
            return []
        self._ensure_schema()
        with self._connection() as connection, connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT external_conversation_id, title, last_activity_at,
                       (SELECT count(*) FROM quetzal_app.chat_messages m WHERE m.session_id = s.session_id)
                FROM quetzal_app.chat_sessions s
                WHERE actor_id = %s AND status = 'active'
                ORDER BY last_activity_at DESC LIMIT %s
                """,
                (actor, limit),
            )
            rows = cursor.fetchall()
        return [
            {
                "conversation_id": conversation_id,
                "title": title,
                "last_activity_at": last_activity_at,
                "message_count": message_count,
            }
            for conversation_id, title, last_activity_at, message_count in rows
        ]


conversation_store = LakebaseConversationStore()
