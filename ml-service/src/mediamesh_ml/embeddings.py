"""Pinned, lazy CLIP inference. Importing this module does not download weights."""

import re
from functools import cached_property

from mediamesh_ml.config import Settings
from mediamesh_ml.contracts import ModelIdentity


class ClipEngine:
    def __init__(self, settings: Settings):
        if not re.fullmatch(r"[0-9a-f]{40}", settings.model_revision):
            raise ValueError("A full immutable model revision is required")
        self.settings = settings

    @cached_property
    def model(self):
        from sentence_transformers import SentenceTransformer

        model = SentenceTransformer(
            self.settings.model_name,
            revision=self.settings.model_revision,
            device=self.settings.device,
            cache_folder=str(self.settings.model_cache),
            local_files_only=self.settings.model_offline,
            trust_remote_code=False,
        )
        if model.get_sentence_embedding_dimension() != self.settings.embedding_dimensions:
            raise ValueError("Loaded model dimensions do not match configured dimensions")
        model.eval()
        return model

    @property
    def identity(self) -> ModelIdentity:
        return ModelIdentity(
            self.settings.model_name,
            self.settings.model_revision,
            self.settings.embedding_dimensions,
        )

    @property
    def model_version(self) -> str:
        return f"{self.identity.name}@{self.identity.revision}:rgb-l2-v1"

    def load(self) -> None:
        """Explicit download/load step; may be run offline against a populated cache."""
        _ = self.model

    def _encode(self, inputs):
        import numpy as np
        import torch

        with torch.inference_mode():
            output = self.model.encode(
                inputs,
                batch_size=self.settings.embedding_batch_size,
                convert_to_numpy=True,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
        output = np.asarray(output, dtype=np.float32)
        if output.shape != (len(inputs), self.identity.dimensions):
            raise ValueError("Unexpected embedding shape")
        if not np.isfinite(output).all():
            raise ValueError("Non-finite embedding")
        norms = np.linalg.norm(output, axis=1)
        if not np.allclose(norms, 1.0, atol=1e-4):
            raise ValueError("Expected unit-normalized embeddings")
        return [tuple(float(value) for value in row) for row in output]

    def encode_text(self, text: str):
        if not text.strip():
            raise ValueError("Query must not be blank")
        return self._encode([text])[0]

    def encode_images(self, paths):
        from mediamesh_ml.images import prepare_image

        vectors = []
        batch_size = self.settings.embedding_batch_size
        for start in range(0, len(paths), batch_size):
            images = []
            try:
                for path in paths[start : start + batch_size]:
                    images.append(prepare_image(path))
                vectors.extend(self._encode(images))
            finally:
                for image in images:
                    image.close()
        return vectors
