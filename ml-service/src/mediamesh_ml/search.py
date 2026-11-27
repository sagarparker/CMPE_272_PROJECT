"""Internal semantic retrieval; authorization and metadata enrichment stay in Spring Boot."""

import logging
import threading

from mediamesh_ml.contracts import EmbeddingEngine, embedding_version

logger = logging.getLogger(__name__)


class SearchUnavailable(RuntimeError):
    """Model/schema/database dependencies are unavailable."""


class SearchService:
    def __init__(self, engine: EmbeddingEngine, repository, *, hybrid_text=False, verifier=None):
        self.engine = engine
        self.repository = repository
        self.hybrid_text = hybrid_text
        self.verifier = verifier
        self.model_loaded = False
        self._inference_lock = threading.Lock()

    def initialize(self):
        self.engine.load()
        self.model_loaded = True

    def is_ready(self) -> bool:
        try:
            return self.model_loaded and self.repository.is_ready()
        except Exception as error:
            logger.warning("Search dependency unavailable: %s", type(error).__name__)
            return False

    def search(self, query: str, limit: int, asset_ids=None):
        if not self.is_ready():
            raise SearchUnavailable("Search dependencies are unavailable")
        with self._inference_lock:
            vector = self.engine.encode_text(query)
            if self.hybrid_text:
                self.repository.refresh_metadata_vectors(
                    embedding_version(self.engine.identity), self.engine.encode_document, asset_ids
                )
        if self.hybrid_text:
            matches = self.repository.search_hybrid(
                vector, embedding_version(self.engine.identity), query, limit, asset_ids
            )
            if self.verifier is not None:
                captions = self.repository.caption_evidence([m.asset_id for m in matches])
                return self.verifier.filter(query, matches, captions)
            return matches
        if asset_ids is None:
            return self.repository.search_assets(
                vector, embedding_version(self.engine.identity), limit
            )
        return self.repository.search_assets(
            vector, embedding_version(self.engine.identity), limit, asset_ids
        )

    def similar(self, asset_id, limit, asset_ids=None):
        if not self.is_ready():
            raise SearchUnavailable("Search dependencies are unavailable")
        return self.repository.similar(
            asset_id, embedding_version(self.engine.identity), limit, asset_ids
        )
