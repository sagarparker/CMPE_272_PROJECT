import math
from uuid import uuid4

import pytest

from mediamesh_ml.contracts import VectorRecord
from mediamesh_ml.vectors import replace_in_transaction, vector_literal


@pytest.mark.parametrize("vector", [(0.0,) * 512, (1.0,) * 511, (math.nan,) * 512])
def test_invalid_vectors_are_rejected(vector):
    with pytest.raises(ValueError):
        vector_literal(vector)


def test_duplicate_null_timestamps_are_rejected_before_writes():
    asset = uuid4()
    row = VectorRecord(asset, (1.0,) + (0.0,) * 511, "model")
    with pytest.raises(ValueError, match="Duplicate"):
        replace_in_transaction(None, asset, "model", [row, row])
