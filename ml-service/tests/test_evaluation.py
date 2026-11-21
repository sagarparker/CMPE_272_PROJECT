import pytest

from mediamesh_ml.evaluate import rank


def test_cosine_ranking_has_stable_ties():
    assert rank((1, 0), [(0, 1), (1, 0), (1, 0)], ["c", "b", "a"], 2) == [("a", 1), ("b", 1)]


def test_ranking_rejects_mismatched_sample_counts():
    with pytest.raises(ValueError):
        rank((1, 0), [(1, 0)], [], 2)
