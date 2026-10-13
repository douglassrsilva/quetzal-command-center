"""Databricks authentication and SQL execution primitives."""

from __future__ import annotations

import hashlib
import logging
import time
from collections import OrderedDict
from copy import deepcopy
from functools import lru_cache
from threading import RLock
from typing import Any

from databricks.sdk import WorkspaceClient
from databricks.sdk.service.sql import StatementParameterListItem, StatementState

from .access import current_access
from .config import settings

log = logging.getLogger("quetzal.platform")


class SqlExecutionError(RuntimeError):
    """A Databricks SQL statement failed."""


class SqlExecutionTimeout(SqlExecutionError):
    """A Databricks SQL statement exceeded the configured deadline."""


@lru_cache(maxsize=1)
def workspace_client() -> WorkspaceClient:
    return WorkspaceClient()


def auth_headers() -> dict[str, str]:
    # OAuth credentials are short-lived; authenticate on every upstream call
    # so the SDK can refresh them instead of caching an expired bearer token.
    headers = dict(workspace_client().config.authenticate() or {})
    headers["Content-Type"] = "application/json"
    headers["User-Agent"] = "Quetzal-Command-Center/2.0"
    return headers


class _QueryCache:
    def __init__(self, max_entries: int = 128):
        self._max_entries = max_entries
        self._items: OrderedDict[str, tuple[float, list[dict[str, Any]]]] = OrderedDict()
        self._lock = RLock()

    def get(self, key: str) -> list[dict[str, Any]] | None:
        now = time.monotonic()
        with self._lock:
            item = self._items.get(key)
            if item is None:
                return None
            expires_at, value = item
            if expires_at <= now:
                self._items.pop(key, None)
                return None
            self._items.move_to_end(key)
            return deepcopy(value)

    def put(self, key: str, value: list[dict[str, Any]], ttl_seconds: int) -> None:
        with self._lock:
            self._items[key] = (time.monotonic() + ttl_seconds, deepcopy(value))
            self._items.move_to_end(key)
            while len(self._items) > self._max_entries:
                self._items.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


_cache = _QueryCache()


def _cache_key(query: str, parameters: dict[str, Any] | None = None) -> str:
    access = current_access()
    partition = access.cache_partition if access else "INTERNAL_NO_REQUEST_CONTEXT"
    normalized = partition + "|" + " ".join(query.split())
    if parameters:
        normalized += "|" + _stable_parameter_key(parameters)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _stable_parameter_key(parameters: dict[str, Any]) -> str:
    return "|".join(f"{name}={value!s}" for name, value in sorted(parameters.items()))


def _statement_parameters(parameters: dict[str, Any] | None) -> list[StatementParameterListItem] | None:
    if not parameters:
        return None
    items = []
    for name, value in parameters.items():
        if value is None:
            items.append(StatementParameterListItem(name=name, value=None, type="STRING"))
        elif isinstance(value, bool):
            items.append(StatementParameterListItem(name=name, value=str(value).lower(), type="BOOLEAN"))
        elif isinstance(value, int):
            # Databricks Workflow and statement identifiers exceed the
            # 32-bit INT range. BIGINT is safe for both ordinary counters and
            # platform-generated IDs and prevents silent empty joins.
            items.append(StatementParameterListItem(name=name, value=str(value), type="BIGINT"))
        elif isinstance(value, float):
            items.append(StatementParameterListItem(name=name, value=str(value), type="DOUBLE"))
        else:
            items.append(StatementParameterListItem(name=name, value=str(value), type="STRING"))
    return items


def run_sql(
    query: str,
    *,
    parameters: dict[str, Any] | None = None,
    cache_ttl: int | None = None,
) -> list[dict[str, Any]]:
    """Execute a statement with named parameters, bounded polling and optional cache."""
    ttl = settings.sql_cache_ttl_seconds if cache_ttl is None else cache_ttl
    key = _cache_key(query, parameters)
    if ttl > 0:
        cached = _cache.get(key)
        if cached is not None:
            return cached

    client = workspace_client()
    started = time.monotonic()
    response = client.statement_execution.execute_statement(
        statement=query,
        warehouse_id=settings.warehouse_id,
        catalog=settings.catalog,
        schema=settings.schema,
        byte_limit=10_000_000,
        parameters=_statement_parameters(parameters),
    )
    deadline = started + settings.sql_timeout_seconds
    while response.status.state in (StatementState.PENDING, StatementState.RUNNING):
        if time.monotonic() >= deadline:
            try:
                client.statement_execution.cancel_execution(response.statement_id)
            except Exception:
                log.warning("Unable to cancel timed-out statement %s", response.statement_id, exc_info=True)
            raise SqlExecutionTimeout(f"SQL statement {response.statement_id} timed out")
        time.sleep(0.25)
        response = client.statement_execution.get_statement(response.statement_id)

    if response.status.state != StatementState.SUCCEEDED:
        detail = response.status.error.message if response.status.error else "unknown Databricks SQL error"
        raise SqlExecutionError(detail)

    columns = []
    if response.manifest and response.manifest.schema and response.manifest.schema.columns:
        columns = [column.name for column in response.manifest.schema.columns]
    rows = [dict(zip(columns, row)) for row in ((response.result and response.result.data_array) or [])]
    if ttl > 0:
        _cache.put(key, rows, ttl)
    log.info("SQL succeeded statement_id=%s rows=%s duration_ms=%s", response.statement_id, len(rows), round((time.monotonic() - started) * 1000))
    return rows


def execute_sql(query: str, *, parameters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Execute a mutating statement and invalidate all cached analytical reads."""
    rows = run_sql(query, parameters=parameters, cache_ttl=0)
    _cache.clear()
    return rows


def clear_query_cache() -> None:
    _cache.clear()
