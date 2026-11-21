import pytest

from mediamesh_ml.config import Settings
from mediamesh_ml.embeddings import ClipEngine


def test_model_identity_is_pinned_and_construction_is_lazy():
    engine = ClipEngine(Settings())
    assert engine.identity.dimensions == 512
    assert len(engine.identity.revision) == 40
    assert "model" not in engine.__dict__
    assert engine.identity.revision in engine.model_version


def test_mutable_model_revision_is_rejected():
    with pytest.raises(ValueError, match="immutable"):
        ClipEngine(Settings(model_revision="main"))
