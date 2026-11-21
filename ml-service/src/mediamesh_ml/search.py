"""Internal semantic retrieval; authorization and metadata enrichment stay in Spring Boot."""

import logging
import threading

from mediamesh_ml.contracts import EmbeddingEngine, embedding_version

logger = logging.getLogger(__name__)


class SearchUnavailable(RuntimeError):
    """Model/schema/database dependencies are unavailable."""


class SearchService:
    def __init__(self, engine: EmbeddingEngine, repository):
        self.engine = engine
        self.repository = repository
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

    def search(self, query: str, limit: int):
        if not self.is_ready():
            raise SearchUnavailable("Search dependencies are unavailable")
        with self._inference_lock:
            vector = self.engine.encode_text(query)
        return self.repository.search_assets(vector, embedding_version(self.engine.identity), limit)
