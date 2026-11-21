import os

import numpy as np
import pytest
from PIL import Image

from mediamesh_ml.config import Settings
from mediamesh_ml.embeddings import ClipEngine


@pytest.mark.skipif(os.getenv("ML_RUN_MODEL_TESTS") != "1", reason="explicit real-model opt-in")
def test_real_pinned_model_dimensions_and_normalization(tmp_path):
    engine = ClipEngine(Settings(model_offline=True))
    path = tmp_path / "image.png"
    Image.new("RGB", (64, 64), (50, 150, 200)).save(path)
    image_vector = engine.encode_images([path])[0]
    text_vector = engine.encode_text("blue sky over water")
    assert len(image_vector) == len(text_vector) == 512
    assert np.linalg.norm(image_vector) == pytest.approx(1, abs=1e-4)
    assert np.linalg.norm(text_vector) == pytest.approx(1, abs=1e-4)
