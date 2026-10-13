"""Versioned Lakebase schema for the operational retention workflow."""

MIGRATION_VERSION = "001_retention_cases"

DDL_STATEMENTS = (
    """
    CREATE SCHEMA IF NOT EXISTS quetzal_app
    """,
    """
    CREATE TABLE IF NOT EXISTS quetzal_app.schema_migrations (
      version TEXT PRIMARY KEY,
      checksum TEXT NOT NULL,
      applied_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      applied_by TEXT NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS quetzal_app.retention_cases (
      case_id TEXT PRIMARY KEY,
      customer_id TEXT NOT NULL,
      country TEXT NOT NULL CHECK (char_length(country) = 2),
      status TEXT NOT NULL CHECK (status IN (
        'PENDING_APPROVAL','APPROVED','REJECTED','IN_PROGRESS','RESOLVED','CLOSED'
      )),
      priority TEXT NOT NULL CHECK (priority IN ('LOW','MEDIUM','HIGH','CRITICAL')),
      title TEXT NOT NULL,
      rationale TEXT NOT NULL,
      recommendation_type TEXT NOT NULL,
      source_recommendation_id TEXT,
      requested_by TEXT NOT NULL,
      approved_by TEXT,
      assigned_to TEXT NOT NULL,
      requested_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      approved_at TIMESTAMPTZ,
      started_at TIMESTAMPTZ,
      resolved_at TIMESTAMPTZ,
      closed_at TIMESTAMPTZ,
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      sla_due_at TIMESTAMPTZ NOT NULL,
      churn_probability DOUBLE PRECISION NOT NULL CHECK (
        churn_probability >= 0 AND churn_probability <= 1
      ),
      churn_model_name TEXT NOT NULL,
      churn_model_version TEXT NOT NULL,
      churn_model_run_id TEXT NOT NULL,
      churn_scored_at TIMESTAMPTZ,
      customer_snapshot JSONB NOT NULL,
      recommendation_snapshot JSONB NOT NULL,
      idempotency_key TEXT NOT NULL UNIQUE,
      request_fingerprint TEXT NOT NULL,
      version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_retention_cases_customer_updated
      ON quetzal_app.retention_cases (customer_id, updated_at DESC)
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_retention_cases_country_status_sla
      ON quetzal_app.retention_cases (country, status, sla_due_at)
    """,
    """
    CREATE TABLE IF NOT EXISTS quetzal_app.retention_case_events (
      event_id TEXT PRIMARY KEY,
      case_id TEXT NOT NULL REFERENCES quetzal_app.retention_cases(case_id) ON DELETE CASCADE,
      event_type TEXT NOT NULL,
      from_status TEXT,
      to_status TEXT NOT NULL,
      actor TEXT NOT NULL,
      note TEXT NOT NULL DEFAULT '',
      evidence JSONB NOT NULL DEFAULT '{}'::jsonb,
      idempotency_key TEXT NOT NULL UNIQUE,
      request_fingerprint TEXT NOT NULL,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now()
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_retention_case_events_case_created
      ON quetzal_app.retention_case_events (case_id, created_at, event_id)
    """,
    """
    COMMENT ON TABLE quetzal_app.retention_cases IS
      'Operational source of truth for governed Quetzal customer-retention cases.'
    """,
    """
    COMMENT ON TABLE quetzal_app.retention_case_events IS
      'Immutable transition ledger for retention-case state, approval and evidence.'
    """,
)
