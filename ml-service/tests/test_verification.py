import json
from unittest.mock import patch
from uuid import UUID

import pytest

from mediamesh_ml.config import Settings
from mediamesh_ml.contracts import Match
from mediamesh_ml.verification import CaptionVerifier


def response(supported):
    return json.dumps({"supported": supported})


def test_verification_rejects_unsupported_query_and_caches_by_query_and_evidence():
    verifier = CaptionVerifier(Settings())
    match = Match(UUID(int=1), 0.9, None)
    captions = {match.asset_id: "A tiger lying on dirt beneath green vegetation."}
    with patch("mediamesh_ml.verification.complete", side_effect=[
        response([]), response([0]), response([0]),
    ]) as generate:
        assert verifier.filter("tiger in sky", [match], captions) == []
        assert verifier.filter("tiger on land", [match], captions) == [match]
        assert verifier.filter("tiger in sky", [match], captions) == []
        assert generate.call_count == 2
        # A changed caption must invalidate a previously rejected result.
        captions[match.asset_id] = "An illustration of a tiger floating in the sky."
        assert verifier.filter("tiger in sky", [match], captions) == [match]
        assert generate.call_count == 3


@pytest.mark.parametrize("indexes", [[1], [-1], [True], [0, 0], "all"])
def test_invalid_model_decisions_do_not_return_unverified_results(indexes):
    verifier = CaptionVerifier(Settings())
    match = Match(UUID(int=1), 0.9, None)
    with patch("mediamesh_ml.verification.complete", return_value=response(indexes)):
        with pytest.raises(RuntimeError, match="Invalid search verification"):
            verifier.filter("tiger", [match], {match.asset_id: "A tiger on grass."})


def test_missing_visual_evidence_is_excluded_without_a_model_request():
    verifier = CaptionVerifier(Settings())
    with patch("mediamesh_ml.verification.complete") as generate:
        assert verifier.filter("tiger", [Match(UUID(int=1), 0.99, None)], {}) == []
        generate.assert_not_called()


def test_candidates_below_display_cutoff_do_not_require_verification():
    verifier = CaptionVerifier(Settings(search_min_similarity=0.67))
    match = Match(UUID(int=1), 0.669, None)
    with patch("mediamesh_ml.verification.complete") as generate:
        assert verifier.filter("tiger", [match], {match.asset_id: "A tiger on grass."}) == []
        generate.assert_not_called()


@pytest.mark.parametrize("query", [
    "pink lion", "Pink Lion", "pink Lion", "pink lion on grass", "a lion with pink fur",
])
def test_explicit_color_requires_caption_evidence_even_if_model_might_accept(query):
    verifier = CaptionVerifier(Settings())
    match = Match(UUID(int=1), 0.9, None)
    captions = {match.asset_id: "A tawny lion resting on grass beneath a blue sky."}
    with patch("mediamesh_ml.verification.complete") as generate:
        assert verifier.filter(query, [match], captions) == []
        generate.assert_not_called()


def test_supported_color_still_requires_model_check_and_case_variants_share_cache():
    verifier = CaptionVerifier(Settings())
    match = Match(UUID(int=1), 0.9, None)
    captions = {match.asset_id: "A pink toy lion on a white table."}
    with patch("mediamesh_ml.verification.complete", return_value=response([0])) as generate:
        assert verifier.filter("Pink Lion", [match], captions) == [match]
        assert verifier.filter("  PINK   LION ", [match], captions) == [match]
        assert generate.call_count == 1


def test_background_color_does_not_bypass_model_verification():
    verifier = CaptionVerifier(Settings())
    match = Match(UUID(int=1), 0.9, None)
    captions = {match.asset_id: "A brown lion in front of a pink wall."}
    with patch("mediamesh_ml.verification.complete", return_value=response([])) as generate:
        assert verifier.filter("pink lion", [match], captions) == []
        generate.assert_called_once()


@pytest.mark.parametrize("query", [
    "not a pink lion", "lion without pink fur", "pink or brown lion",
])
def test_negated_or_alternative_colors_are_left_to_model(query):
    from mediamesh_ml.verification import positive_query_colors

    assert positive_query_colors(query) == set()
