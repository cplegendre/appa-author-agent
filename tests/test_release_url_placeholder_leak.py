"""Regression test for a bug found in real usage (v0.17): a Facebook draft printed
the literal template placeholder `[RELEASE_URL]` twice instead of substituting the
real supplied URL (or omitting it). The URL-presence validator only checked for
`https?://` links, so this specific failure mode slipped through undetected.
"""
import pytest

from author_agent.errors import ValidationError
from author_agent.orchestration import _validate_release_field_contract


@pytest.mark.parametrize(
    "leaked_text",
    [
        "Now available in paperback on Amazon: [RELEASE_URL]",
        "Grab your copy here: {{RELEASE_URL}}",
        "Link: <RELEASE_URL>",
        "See {RELEASE_URL} for details",
        "see [release_url] for details",  # case-insensitive
    ],
)
def test_leaked_release_url_placeholder_is_rejected_on_facebook(leaked_text):
    with pytest.raises(ValidationError, match="leaked the raw RELEASE_URL placeholder"):
        _validate_release_field_contract(
            "facebook", leaked_text, status="published", release_url="https://amazon.example/book"
        )


def test_leaked_release_url_placeholder_is_rejected_regardless_of_strict_mode():
    # This must fire even when require_release_metadata (the opt-in strictness flag)
    # is off — it's a correctness bug, not a style/strictness preference.
    with pytest.raises(ValidationError, match="leaked the raw RELEASE_URL placeholder"):
        _validate_release_field_contract(
            "facebook",
            "Available now: [RELEASE_URL]",
            status="published",
            release_url="https://amazon.example/book",
            require_release_metadata=False,
        )


def test_leaked_placeholder_check_also_applies_to_instagram_and_teaser():
    with pytest.raises(ValidationError, match="leaked the raw RELEASE_URL placeholder"):
        _validate_release_field_contract(
            "instagram", "Link in bio, or see [RELEASE_URL]", status="published", release_url="x"
        )
    with pytest.raises(ValidationError, match="leaked the raw RELEASE_URL placeholder"):
        _validate_release_field_contract(
            "teaser", "Coming soon: {{RELEASE_URL}}", status="scheduled", release_url=""
        )


def test_real_url_present_does_not_trigger_false_positive():
    # Sanity check: a normal, correctly-substituted URL must not be flagged.
    _validate_release_field_contract(
        "facebook",
        "Now available in paperback on Amazon: https://amazon.example/book",
        status="published",
        release_url="https://amazon.example/book",
    )
