CREATE TABLE asset_metadata_vectors (
    asset_id uuid NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
    model_version text NOT NULL,
    metadata_hash text NOT NULL,
    embedding vector NOT NULL CHECK (vector_dims(embedding) = 768),
    PRIMARY KEY (asset_id, model_version)
);
