"""Pinned, lazy CLIP inference. Importing this module does not download weights."""

import re
from functools import cached_property

from mediamesh_ml.config import Settings
from mediamesh_ml.contracts import InvalidQuery, ModelIdentity, embedding_version

SIGLIP2_ID = ModelIdentity(
    "google/siglip2-base-patch16-224",
    "75de2d55ec2d0b4efc50b3e9ad70dba96a7b2fa2",
    768,
    "siglip2-rgb-l2-v1",
)


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
            processor_kwargs={"use_fast": False},
        )
        if model.get_embedding_dimension() != self.settings.embedding_dimensions:
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
        return embedding_version(self.identity)

    def load(self) -> None:
        """Explicit download/load step; may be run offline against a populated cache."""
        _ = self.model

    def _encode(self, inputs):
        import torch

        with torch.inference_mode():
            output = self.model.encode(
                inputs,
                batch_size=self.settings.embedding_batch_size,
                convert_to_numpy=True,
                normalize_embeddings=True,
                show_progress_bar=False,
            )
        return self._validated_vectors(output, len(inputs))

    def _validated_vectors(self, output, count):
        import numpy as np

        output = np.asarray(output, dtype=np.float32)
        if output.shape != (count, self.identity.dimensions):
            raise ValueError("Unexpected embedding shape")
        if not np.isfinite(output).all():
            raise ValueError("Non-finite embedding")
        norms = np.linalg.norm(output, axis=1)
        if not np.allclose(norms, 1.0, atol=1e-4):
            raise ValueError("Expected unit-normalized embeddings")
        return [tuple(float(value) for value in row) for row in output]

    def encode_text(self, text: str):
        if not text.strip():
            raise InvalidQuery("Query must not be blank")
        tokenizer = self.model[0].tokenizer
        tokens = tokenizer(text, truncation=False, max_length=tokenizer.model_max_length)[
            "input_ids"
        ]
        if len(tokens) > tokenizer.model_max_length:
            raise InvalidQuery("Query exceeds the pinned CLIP token budget")
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


class Siglip2Engine(ClipEngine):
    @property
    def identity(self) -> ModelIdentity:
        return SIGLIP2_ID

    @cached_property
    def model(self):
        from transformers import AutoModel, AutoProcessor

        options = {
            "revision": self.identity.revision,
            "cache_dir": self.settings.model_cache,
            "local_files_only": self.settings.model_offline,
        }
        processor = AutoProcessor.from_pretrained(self.identity.name, **options)
        model = AutoModel.from_pretrained(self.identity.name, **options).to(self.settings.device)
        return model.eval(), processor

    def _encode(self, inputs):
        import torch

        model, processor = self.model
        with torch.inference_mode():
            if isinstance(inputs[0], str):
                features = processor(text=inputs, padding="max_length", return_tensors="pt")
                output = model.get_text_features(**features.to(self.settings.device))
            else:
                features = processor(images=inputs, return_tensors="pt")
                output = model.get_image_features(**features.to(self.settings.device))
            if not torch.is_tensor(output):
                output = output.pooler_output
            vectors = torch.nn.functional.normalize(output.float(), dim=-1).cpu().numpy()
        return self._validated_vectors(vectors, len(inputs))

    def encode_text(self, text: str):
        if not text.strip():
            raise InvalidQuery("Query must not be blank")
        model, processor = self.model
        max_tokens = model.config.text_config.max_position_embeddings
        if len(processor.tokenizer(text, truncation=False)["input_ids"]) > max_tokens:
            raise InvalidQuery("Query exceeds the pinned SigLIP 2 token budget")
        return self._encode([text])[0]


def create_engine(settings: Settings):
    if settings.embedding_model == "embeddinggemma2":
        from mediamesh_ml.gemma_embeddings import GemmaEngine

        return GemmaEngine(settings)
    if settings.embedding_model == "siglip2":
        return Siglip2Engine(settings)
    return ClipEngine(settings)


if __name__ == "__main__":
    import json

    engine = create_engine(Settings())
    engine.load()
    print(
        json.dumps({"modelVersion": engine.model_version, "dimensions": engine.identity.dimensions})
    )
