"""Versioned Lakebase schema for governed campaign planning."""

MIGRATION_VERSION = "002_campaign_workflow"

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
    CREATE TABLE IF NOT EXISTS quetzal_app.campaign_drafts (
      campaign_id TEXT PRIMARY KEY,
      source_draft_id TEXT NOT NULL,
      title TEXT NOT NULL,
      requested_country TEXT NOT NULL,
      country_scope TEXT[] NOT NULL CHECK (cardinality(country_scope) > 0),
      objective TEXT NOT NULL CHECK (objective IN ('RETENTION','CROSS_SELL')),
      channel TEXT NOT NULL CHECK (channel IN ('EMAIL','SMS','WHATSAPP','CALL')),
      source_theme_id TEXT,
      status TEXT NOT NULL CHECK (status IN (
        'DRAFT','PENDING_APPROVAL','APPROVED','REJECTED','CANCELLED'
      )),
      requested_by TEXT NOT NULL,
      assigned_to TEXT NOT NULL,
      decided_by TEXT,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      submitted_at TIMESTAMPTZ,
      decided_at TIMESTAMPTZ,
      cancelled_at TIMESTAMPTZ,
      audience_fingerprint TEXT NOT NULL,
      selected_customers INTEGER NOT NULL CHECK (selected_customers > 0),
      estimated_net_impact_usd DOUBLE PRECISION NOT NULL,
      estimated_roi_pct DOUBLE PRECISION,
      break_even_response_rate_pct DOUBLE PRECISION,
      campaign_request JSONB NOT NULL,
      campaign_snapshot JSONB NOT NULL,
      campaign_sent BOOLEAN NOT NULL DEFAULT false CHECK (campaign_sent = false),
      idempotency_key TEXT NOT NULL UNIQUE,
      request_fingerprint TEXT NOT NULL,
      version INTEGER NOT NULL DEFAULT 1 CHECK (version > 0),
      snapshot_version INTEGER NOT NULL DEFAULT 1 CHECK (snapshot_version > 0)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_campaign_drafts_scope_status_updated
      ON quetzal_app.campaign_drafts USING GIN (country_scope)
    """,
    """
    CREATE INDEX IF NOT EXISTS ix_campaign_drafts_status_updated
      ON quetzal_app.campaign_drafts (status, updated_at DESC)
    """,
    """
    CREATE TABLE IF NOT EXISTS quetzal_app.campaign_draft_versions (
      campaign_id TEXT NOT NULL REFERENCES quetzal_app.campaign_drafts(campaign_id) ON DELETE CASCADE,
      snapshot_version INTEGER NOT NULL CHECK (snapshot_version > 0),
      source_draft_id TEXT NOT NULL,
      actor TEXT NOT NULL,
      campaign_request JSONB NOT NULL,
      campaign_snapshot JSONB NOT NULL,
      snapshot_fingerprint TEXT NOT NULL,
      created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
      PRIMARY KEY (campaign_id, snapshot_version)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS quetzal_app.campaign_events (
      event_id TEXT PRIMARY KEY,
      campaign_id TEXT NOT NULL REFERENCES quetzal_app.campaign_drafts(campaign_id) ON DELETE CASCADE,
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
    CREATE INDEX IF NOT EXISTS ix_campaign_events_campaign_created
      ON quetzal_app.campaign_events (campaign_id, created_at, event_id)
    """,
    """
    COMMENT ON TABLE quetzal_app.campaign_drafts IS
      'Operational source of truth for governed campaign planning; delivery is intentionally excluded.'
    """,
    """
    COMMENT ON TABLE quetzal_app.campaign_draft_versions IS
      'Immutable economic and audience snapshots for each saved campaign revision.'
    """,
    """
    COMMENT ON TABLE quetzal_app.campaign_events IS
      'Immutable audit ledger for campaign submission, approval, rejection and cancellation.'
    """,
)
