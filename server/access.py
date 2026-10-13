"""Request identity, authorization scope and context propagation.

Databricks Apps terminates authentication at the application proxy.  The
backend trusts only the proxy identity headers and never accepts an actor,
role or territorial scope from a request body.  Local execution is available
only through an explicit, non-published configuration.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable, Iterable
from contextvars import ContextVar, Token, copy_context
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, Request

from .config import COUNTRIES

TRUSTED_EMAIL_HEADERS = (
    "x-forwarded-email",
    "x-databricks-user-email",
)
TRUSTED_USER_HEADER = "x-forwarded-user"
KNOWN_ROLES = frozenset({
    "ADMIN",
    "NOC_OPERATOR",
    "ACTION_APPROVER",
    "CARE_AGENT",
    "EXECUTIVE_VIEWER",
})
_ACTOR_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9@._+\-]{0,199}$")


@dataclass(frozen=True)
class AccessContext:
    actor: str
    roles: tuple[str, ...] | None
    countries: tuple[str, ...]
    identity_source: str

    @property
    def resolved(self) -> bool:
        return self.roles is not None

    @property
    def cache_partition(self) -> str:
        roles = ",".join(self.roles or ("UNRESOLVED",))
        countries = ",".join(self.countries or ("ALL",))
        return f"{self.actor.casefold()}|{roles}|{countries}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "actor": self.actor,
            "roles": list(self.roles or ()),
            "countries": list(self.countries),
            "identity_source": self.identity_source,
            "execution_identity": "APP_SERVICE_PRINCIPAL_WITH_APP_ENFORCED_SCOPE",
        }


_current_access: ContextVar[AccessContext | None] = ContextVar(
    "quetzal_current_access", default=None
)


def _csv(name: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in os.getenv(name, "").split(",") if item.strip())


def _is_published() -> bool:
    runtime = os.getenv("QUETZAL_RUNTIME", "").strip().lower()
    return bool(os.getenv("DATABRICKS_APP_NAME")) or runtime in {"published", "production"}


def _validated_actor(value: str) -> str:
    actor = value.strip().casefold()
    if not _ACTOR_PATTERN.fullmatch(actor):
        raise HTTPException(401, "La identidad autenticada no es válida.")
    return actor


def _admin_roles() -> tuple[str, ...]:
    return tuple(sorted(KNOWN_ROLES))


def _identity_from_headers(request: Request) -> tuple[str, str] | None:
    email_values = {
        _validated_actor(value)
        for header in TRUSTED_EMAIL_HEADERS
        if (value := request.headers.get(header))
    }
    if len(email_values) > 1:
        raise HTTPException(401, "Los encabezados de identidad son inconsistentes.")
    if email_values:
        # Databricks Apps may also send x-forwarded-user as an opaque subject
        # identifier.  The canonical email header is the governed actor used by
        # RBAC, audit and per-user memory, so the two values are not compared.
        return email_values.pop(), "databricks_app_proxy_email"
    if value := request.headers.get(TRUSTED_USER_HEADER):
        return _validated_actor(value), "databricks_app_proxy_user"
    return None


def _local_identity() -> AccessContext:
    if _is_published() or os.getenv("QUETZAL_LOCAL_MODE", "false").lower() != "true":
        raise HTTPException(401, "Se requiere una identidad autenticada de Databricks Apps.")
    actor = _validated_actor(os.getenv("QUETZAL_LOCAL_ACTOR", ""))
    roles = tuple(sorted({role.upper() for role in _csv("QUETZAL_LOCAL_ROLES") if role.upper() in KNOWN_ROLES}))
    countries = tuple(sorted({country.upper() for country in _csv("QUETZAL_LOCAL_COUNTRIES") if country.upper() in COUNTRIES}))
    if not roles:
        raise HTTPException(403, "El modo local no tiene roles autorizados configurados.")
    return AccessContext(actor, roles, countries, "explicit_local_mode")


def identify_request(request: Request | None) -> AccessContext:
    """Resolve identity only; operational roles are loaded lazily."""
    if request is None:
        current = _current_access.get()
        return current if current is not None else _local_identity()

    header_identity = _identity_from_headers(request)
    if header_identity is None:
        identity = _local_identity()
    else:
        actor, source = header_identity
        admins = {item.casefold() for item in _csv("QUETZAL_ADMIN_USERS")}
        roles = _admin_roles() if actor in admins else None
        identity = AccessContext(actor, roles, (), source)
    request.state.access_context = identity
    return identity


def bind_access(access: AccessContext) -> Token:
    return _current_access.set(access)


def reset_access(token: Token) -> None:
    _current_access.reset(token)


def current_access() -> AccessContext | None:
    return _current_access.get()


def resolve_access(
    request: Request | None,
    role_loader: Callable[..., list[dict[str, Any]]],
) -> AccessContext:
    """Load governed roles and territorial scope for the authenticated actor."""
    access = getattr(getattr(request, "state", None), "access_context", None) if request else None
    access = access or _current_access.get() or identify_request(request)
    if access.resolved:
        return access

    rows = role_loader(
        "SELECT role, country_scope FROM ops_user_roles "
        "WHERE lower(principal) = :principal AND active = true",
        parameters={"principal": access.actor},
        cache_ttl=15,
    )
    roles = tuple(sorted({str(row.get("role") or "").upper() for row in rows if str(row.get("role") or "").upper() in KNOWN_ROLES}))
    # A mixed set of global and territorial role rows is treated conservatively:
    # any explicit country scope restricts the whole request context.
    countries = tuple(sorted({
        str(row.get("country_scope") or "").upper()
        for row in rows
        if str(row.get("country_scope") or "").upper() in COUNTRIES
    }))
    resolved = AccessContext(access.actor, roles, countries, access.identity_source)
    _current_access.set(resolved)
    if request is not None:
        request.state.access_context = resolved
    return resolved


def require_any_role(access: AccessContext) -> AccessContext:
    if not access.roles:
        raise HTTPException(403, "Tu perfil no tiene un rol operativo activo.")
    return access


def require_roles(access: AccessContext, allowed: Iterable[str]) -> AccessContext:
    allowed_roles = {role.upper() for role in allowed}
    require_any_role(access)
    if "ADMIN" not in access.roles and not allowed_roles.intersection(access.roles):
        raise HTTPException(403, "Tu perfil no tiene permiso para realizar esta operación.")
    return access


def assert_country_access(access: AccessContext, country: str | None) -> None:
    if country and access.countries and country.upper() not in access.countries:
        raise HTTPException(403, "El país solicitado está fuera de tu alcance operativo.")


def country_predicate(access: AccessContext, column: str) -> tuple[str, dict[str, str]]:
    """Return an app-controlled SQL predicate for an allowlisted column."""
    if access.countries:
        return f"array_contains(split(:authorized_country_scope, ','), {column})", {
            "authorized_country_scope": ",".join(access.countries),
        }
    return "TRUE", {}


def require_unrestricted_service(access: AccessContext, service: str) -> None:
    """Fail closed where an upstream service cannot enforce territorial scope."""
    require_any_role(access)
    if access.countries:
        raise HTTPException(
            403,
            f"{service} está deshabilitado para perfiles con alcance territorial porque la consulta usa la identidad del App.",
        )


def submit_with_context(executor, function, *args, **kwargs):
    """Propagate the current authorization partition into worker threads."""
    context = copy_context()
    return executor.submit(context.run, function, *args, **kwargs)
