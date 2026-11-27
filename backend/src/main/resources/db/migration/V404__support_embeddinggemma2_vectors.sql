ALTER TABLE asset_vectors DROP CONSTRAINT asset_vectors_model_dimensions;
ALTER TABLE asset_vectors ADD CONSTRAINT asset_vectors_model_dimensions CHECK (
    vector_dims(embedding) = CASE
        WHEN model_version LIKE 'google/embeddinggemma-2@%:gemma2-rgb768-searchquery-l2-v1' THEN 768
        WHEN model_version LIKE 'Qwen/Qwen3-VL-Embedding-2B@%:qwen-vl-rgb336-l2-v1' THEN 2048
        WHEN model_version LIKE 'google/siglip2-base-patch16-224@%:siglip2-rgb-l2-v1' THEN 768
        ELSE 512
    END
);
