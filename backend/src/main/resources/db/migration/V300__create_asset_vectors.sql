-- Teammate 3. Requires teammate 2's assets(id UUID) prerequisite.
-- CLIP 512-dimensional, normalized rgb-l2-v1 vectors; exact cosine search for MVP.
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE asset_vectors (
    id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    asset_id UUID NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
    frame_timestamp_seconds DOUBLE PRECISION,
    model_version TEXT NOT NULL CHECK (length(btrim(model_version)) > 0),
    embedding VECTOR(512) NOT NULL,
    CONSTRAINT asset_vectors_timestamp_valid CHECK (
        frame_timestamp_seconds IS NULL OR
        (frame_timestamp_seconds >= 0 AND frame_timestamp_seconds < 'Infinity'::DOUBLE PRECISION)
    ),
    CONSTRAINT asset_vectors_unit_norm CHECK (abs(vector_norm(embedding) - 1.0) < 0.001),
    CONSTRAINT asset_vectors_unique_frame UNIQUE NULLS NOT DISTINCT
        (asset_id, model_version, frame_timestamp_seconds)
);

-- Unique constraint serves asset/FK lookups. Filter model versions before exact search.
CREATE INDEX asset_vectors_model_version_idx ON asset_vectors(model_version);
