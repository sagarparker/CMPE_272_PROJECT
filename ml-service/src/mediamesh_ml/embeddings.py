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
