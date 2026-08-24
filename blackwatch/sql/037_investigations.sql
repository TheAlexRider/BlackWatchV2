-- Analyst-owned investigation notebooks and immutable result references.
-- Search input is never stored as SQL; all result queries are parameterized.

CREATE TABLE IF NOT EXISTS investigations (
    id              UUID PRIMARY KEY,
    title           TEXT NOT NULL,
    status          TEXT NOT NULL DEFAULT 'ready',
    priority        TEXT NOT NULL DEFAULT 'medium',
    owner           TEXT NOT NULL,
    time_start      TIMESTAMPTZ NOT NULL,
    time_end        TIMESTAMPTZ NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at    TIMESTAMPTZ,
    CHECK (status IN ('ready', 'investigating', 'contained', 'confirmed_malicious', 'confirmed_expected', 'false_positive', 'inconclusive', 'closed')),
    CHECK (priority IN ('low', 'medium', 'high', 'critical')),
    CHECK (time_end >= time_start)
);

CREATE TABLE IF NOT EXISTS investigation_observables (
    id              BIGSERIAL PRIMARY KEY,
    investigation_id UUID NOT NULL REFERENCES investigations(id) ON DELETE CASCADE,
    observable_type TEXT NOT NULL,
    observable_value TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (investigation_id, observable_type, observable_value)
);

CREATE TABLE IF NOT EXISTS investigation_notes (
    id              BIGSERIAL PRIMARY KEY,
    investigation_id UUID NOT NULL REFERENCES investigations(id) ON DELETE CASCADE,
    author          TEXT NOT NULL,
    body            TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS investigation_results (
    investigation_id UUID NOT NULL REFERENCES investigations(id) ON DELETE CASCADE,
    event_id        UUID NOT NULL REFERENCES events(event_id) ON DELETE CASCADE,
    match_reason    TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (investigation_id, event_id)
);

CREATE INDEX IF NOT EXISTS idx_investigations_owner_updated ON investigations (owner, updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_investigation_observables_value ON investigation_observables (observable_type, observable_value);
CREATE INDEX IF NOT EXISTS idx_investigation_results_investigation ON investigation_results (investigation_id, created_at DESC);
