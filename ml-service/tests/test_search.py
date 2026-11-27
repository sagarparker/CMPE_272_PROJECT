from uuid import UUID

import pytest

from mediamesh_ml.contracts import Match, ModelIdentity
from mediamesh_ml.search import SearchService, SearchUnavailable


class Engine:
    identity = ModelIdentity("test-model", "revision", 512)

    def load(self):
        pass

    def encode_document(self, text):
        return self.encode_text(text)

    def encode_text(self, query):
        return (1.0,) + (0.0,) * 511


class Repository:
    def is_ready(self):
        return True

    def search_assets(self, vector, model_version, limit):
        assert len(vector) == 512
        assert model_version == "test-model@revision:rgb-l2-v1"
        return [Match(UUID(int=1), 0.8, None)]


def test_uninitialized_model_cannot_serve_search():
    service = SearchService(Engine(), Repository())
    assert not service.is_ready()
    with pytest.raises(SearchUnavailable):
        service.search("elephants", 5)


def test_search_passes_compatible_model_version():
    service = SearchService(Engine(), Repository())
    service.initialize()
    assert service.search("elephants", 5)[0].asset_id == UUID(int=1)


def test_database_outage_is_not_empty_success():
    class Offline(Repository):
        def is_ready(self):
            raise OSError("Database unavailable")

    service = SearchService(Engine(), Offline())
    service.initialize()
    with pytest.raises(SearchUnavailable):
        service.search("elephants", 5)


def test_catalog_search_passes_query_and_scope_to_hybrid_ranking():
    class HybridRepository(Repository):
        def refresh_metadata_vectors(self, version, encode_document, asset_ids):
            assert asset_ids == [UUID(int=1)]

        def search_hybrid(self, vector, version, query, limit, asset_ids):
            assert version == "test-model@revision:rgb-l2-v1"
            assert query == "zebras near trees"
            assert asset_ids == [UUID(int=1)]
            return [Match(UUID(int=1), 0.73, None)]

    service = SearchService(Engine(), HybridRepository(), hybrid_text=True)
    service.initialize()
    assert service.search("zebras near trees", 5, [UUID(int=1)])[0].score == 0.73
