from uuid import UUID

import pytest

from mediamesh_ml.contracts import Match, ModelIdentity
from mediamesh_ml.search import SearchService, SearchUnavailable


class Engine:
    identity = ModelIdentity("test-model", "revision", 512)

    def load(self):
        pass

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
