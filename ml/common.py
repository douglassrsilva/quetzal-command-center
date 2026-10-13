from __future__ import annotations

import re
from collections.abc import Iterable

from mlflow import MlflowClient

_UC_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*\.[A-Za-z_][A-Za-z0-9_]*$")


def uc_identifier(value: str) -> str:
    """Accept only three-part UC identifiers before interpolating Spark SQL/table APIs."""
    if not _UC_IDENTIFIER.fullmatch(value):
        raise ValueError(f"Invalid Unity Catalog identifier: {value!r}")
    return value


def require_columns(actual: Iterable[str], required: Iterable[str], *, source: str) -> None:
    missing = sorted(set(required) - set(actual))
    if missing:
        raise ValueError(f"{source} is missing required columns: {', '.join(missing)}")


def model_version_by_alias(model_name: str, alias: str):
    client = MlflowClient()
    version = client.get_model_version_by_alias(model_name, alias)
    if not version.run_id:
        raise RuntimeError(f"Model {model_name}@{alias} does not expose an MLflow run_id")
    return client, version
