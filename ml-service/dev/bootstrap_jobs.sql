-- Standalone Compose fixtures ONLY. Not a V2xx production migration.
CREATE SCHEMA IF NOT EXISTS ml_dev;
CREATE TABLE IF NOT EXISTS ml_dev.asset_states (
    asset_id UUID PRIMARY KEY REFERENCES public.assets(id) ON DELETE CASCADE,
    processing_status TEXT NOT NULL CHECK (processing_status IN ('PROCESSING','READY','FAILED'))
);
CREATE TABLE IF NOT EXISTS ml_dev.index_jobs (
    id UUID PRIMARY KEY,
    asset_id UUID NOT NULL REFERENCES public.assets(id) ON DELETE CASCADE,
    media_reference TEXT NOT NULL,
    media_type TEXT NOT NULL CHECK (media_type IN ('image','video')),
    status TEXT NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING','PROCESSING','SUCCEEDED','FAILED')),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    max_attempts INTEGER NOT NULL CHECK (max_attempts > 0),
    available_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    claim_token UUID,
    lease_expires_at TIMESTAMPTZ,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    CHECK ((status = 'PROCESSING') = (claim_token IS NOT NULL AND lease_expires_at IS NOT NULL))
);
CREATE UNIQUE INDEX IF NOT EXISTS local_one_active_job_per_asset
    ON ml_dev.index_jobs(asset_id) WHERE status IN ('PENDING','PROCESSING');
CREATE INDEX IF NOT EXISTS local_jobs_available ON ml_dev.index_jobs(status, available_at, created_at);
