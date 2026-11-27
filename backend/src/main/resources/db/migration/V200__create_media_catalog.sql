CREATE TABLE assets (
    id UUID PRIMARY KEY,
    owner_id UUID NOT NULL,
    s3_key TEXT NOT NULL UNIQUE,
    media_type TEXT NOT NULL CHECK (media_type IN ('image', 'video')),
    title TEXT NOT NULL,
    description TEXT,
    species TEXT,
    location TEXT,
    captured_at DATE,
    contributor TEXT,
    usage_note TEXT,
    processing_status TEXT NOT NULL
        CHECK (processing_status IN ('UPLOADING', 'PROCESSING', 'READY', 'FAILED')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE index_jobs (
    id UUID PRIMARY KEY,
    asset_id UUID NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
    media_reference TEXT NOT NULL,
    media_type TEXT NOT NULL CHECK (media_type IN ('image', 'video')),
    status TEXT NOT NULL DEFAULT 'PENDING'
        CHECK (status IN ('PENDING', 'PROCESSING', 'SUCCEEDED', 'FAILED')),
    attempts INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 3,
    available_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    claim_token UUID,
    lease_expires_at TIMESTAMPTZ,
    last_error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    CONSTRAINT index_jobs_attempts_valid CHECK (attempts >= 0),
    CONSTRAINT index_jobs_max_attempts_valid CHECK (max_attempts > 0)
);

CREATE UNIQUE INDEX one_active_job_per_asset
    ON index_jobs(asset_id)
    WHERE status IN ('PENDING', 'PROCESSING');
CREATE INDEX index_jobs_available_idx
    ON index_jobs(status, available_at, created_at);
