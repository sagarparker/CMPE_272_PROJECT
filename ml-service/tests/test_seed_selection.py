"""Small seed subsets stay representative and safe to grow on subsequent runs."""

from pathlib import Path

import pytest

from mediamesh_ml.dataset import IMAGE_COUNTS, read_manifest, select_images


def test_image_subsets_are_nested_and_exclude_videos():
    items = read_manifest(Path("evaluation/demo-manifest.json"))
    previous = []
    for count in IMAGE_COUNTS:
        selected = select_images(items, count)
        assert len(selected) == count
        assert len({item["id"] for item in selected}) == count
        assert all(item.get("mediaType", "image") == "image" for item in selected)
        assert {item["domain"] for item in selected} == {item["domain"] for item in items}
        assert selected[:len(previous)] == previous
        previous = selected


@pytest.mark.parametrize("count", [0, 21, 501])
def test_invalid_image_count(count):
    with pytest.raises(ValueError, match="Image count"):
        select_images([], count)


def test_manifest_must_contain_enough_images():
    with pytest.raises(ValueError, match="only 0 images"):
        select_images([], 20)
