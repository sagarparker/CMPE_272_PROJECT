from unittest.mock import patch

import pytest

from mediamesh_ml.config import Settings
from mediamesh_ml.contracts import InvalidQuery, embedding_version
from mediamesh_ml.embeddings import create_engine
from mediamesh_ml.gemma_embeddings import GEMMA_ID, GemmaEngine


def test_gemma_configuration_matches_vector_contract():
    settings = Settings(embedding_model="embeddinggemma2")
    engine = create_engine(settings)
    assert isinstance(engine, GemmaEngine)
    assert settings.vector_dimensions == engine.identity.dimensions == 768
    with patch.object(engine, "_request", return_value={"modelVersion": "wrong-model"}):
        with pytest.raises(OSError, match="does not match"):
            engine.load()
    expected = {"modelVersion": embedding_version(GEMMA_ID)}
    with patch.object(engine, "_request", return_value=expected):
        engine.load()


def test_gemma_rejects_wrong_dimension_response_and_blank_query():
    engine = GemmaEngine(Settings(embedding_model="embeddinggemma2"))
    with patch.object(engine, "_request", return_value={"embedding": [1.0, 0.0]}):
        with pytest.raises(ValueError):
            engine.encode_text("a zebra")
    with pytest.raises(InvalidQuery):
        engine.encode_text(" ")
