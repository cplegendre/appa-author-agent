"""Regression test for a bug found in real usage (v0.18): Instagram drafts kept
failing validation for having 17 hashtags against an expected 12-16 range, even
after the one automatic corrective retry — because counting to an exact cap is
something LLMs are unreliable at, not something worth spending a retry on.

Fix: deterministically trim excess hashtags in code before validation runs, so
only genuine *undershoot* (too few hashtags) still needs a model retry.
"""
import pytest

from author_agent.orchestration import (
    _trim_excess_hashtags,
    _validate_release_social_contract,
)


def test_trim_excess_hashtags_removes_only_the_overflow():
    text = "Great news! " + " ".join(f"#tag{i}" for i in range(17))
    trimmed = _trim_excess_hashtags(text, max_count=16)
    assert trimmed.count("#") == 16
    # The kept tags are the first 16, in original order.
    assert "#tag16" not in trimmed
    assert "#tag0" in trimmed and "#tag15" in trimmed


def test_trim_excess_hashtags_noop_when_within_limit():
    text = "Great news! #a #b #c"
    assert _trim_excess_hashtags(text, max_count=16) == text


def test_trim_excess_hashtags_noop_when_max_is_zero_or_unset():
    text = "#a #b #c #d #e"
    assert _trim_excess_hashtags(text, max_count=0) == text


def test_trim_excess_hashtags_cleans_up_leftover_whitespace():
    text = "Caption text.\n\n#a #b #c #d"
    trimmed = _trim_excess_hashtags(text, max_count=2)
    assert trimmed.count("#") == 2
    assert "  " not in trimmed  # no doubled spaces left behind
    assert not trimmed.endswith(" ")


def test_release_social_contract_auto_trims_instagram_overflow_instead_of_failing():
    # This is exactly the shape of the real failure report: 17 hashtags against a
    # 12-16 configured range. Previously this raised ValidationError even after a
    # retry; now the payload is silently corrected in place before validation.
    payload = {
        "facebook": "A warm launch note without hashtags.",
        "instagram": "Yok's first friend! " + " ".join(f"#tag{i}" for i in range(17)),
        "teaser": "Coming soon.",
    }
    brand_voice = {
        "enforce_release_metadata": True,
        "instagram": {"hashtag_min": 12, "hashtag_max": 16},
    }
    _validate_release_social_contract(
        payload, status="scheduled", release_url="", brand_voice=brand_voice
    )
    assert payload["instagram"].count("#") == 16


def test_release_social_contract_still_rejects_genuine_undershoot():
    # Too few hashtags can't be safely auto-fixed (we won't invent tags), so this
    # must still raise and go through the normal model-retry path.
    payload = {
        "facebook": "A warm launch note.",
        "instagram": "Only a couple: #a #b",
        "teaser": "Coming soon.",
    }
    brand_voice = {
        "enforce_release_metadata": True,
        "instagram": {"hashtag_min": 12, "hashtag_max": 16},
    }
    with pytest.raises(Exception, match="hashtags; expected"):
        _validate_release_social_contract(
            payload, status="scheduled", release_url="", brand_voice=brand_voice
        )
