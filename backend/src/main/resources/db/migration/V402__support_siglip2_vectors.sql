ALTER TABLE asset_vectors ALTER COLUMN embedding TYPE vector;

-- Keep the CLIP index and store SigLIP 2 rows alongside it by model version.
ALTER TABLE asset_vectors ADD CONSTRAINT asset_vectors_model_dimensions CHECK (
    vector_dims(embedding) = CASE
        WHEN model_version LIKE 'google/siglip2-base-patch16-224@%:siglip2-rgb-l2-v1' THEN 768
        ELSE 512
    END
);
