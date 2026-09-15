"""Regression tests for two bugs found in real usage on a Luma release:

1. Instagram draft included "#YokStories" — a hardcoded example hashtag from the
   prompt's own instructions ("brand/series tags, for example #YokStories") leaked
   verbatim into a post for a completely different series ("Luma's Blue Dreams
   Forest") instead of being replaced with a tag derived from the real series.

2. The teaser said "coming September 13, 2026" while the Instagram draft in the
   SAME release said "now available on Amazon" — a real status contradiction that
   the old check missed because it only matched the literal phrase "coming soon",
   not "coming <date>".
"""
import pytest

from author_agent.errors import ValidationError
from author_agent.orchestration import (
    _reads_as_not_yet_available,
    _validate_current_release_metadata,
    _validate_release_field_contract,
)


def test_yokstories_hashtag_rejected_on_non_yok_series():
    facts = {"title": "Luma's Big-Heart Forest Tales", "series": "Luma's Blue Dreams Forest"}
    text = (
        "Luma's Big-Heart Forest Tales, part of Luma's Blue Dreams Forest, Book 7 of 8. "
        "#LumaStories #YokStories #ChildrensBooks"
    )
    with pytest.raises(ValidationError, match="only an example"):
        _validate_current_release_metadata("instagram", text, facts)


def test_yokstories_hashtag_is_fine_on_an_actual_yok_release():
    facts = {"title": "Yok's First Friend", "series": "A Yok Story"}
    text = "Yok's First Friend, part of A Yok Story, Book 1 of 10. #YokStories #ChildrensBooks"
    # Must not raise for the series it's actually correct for.
    _validate_current_release_metadata("instagram", text, facts)


def test_correct_series_specific_hashtag_is_never_flagged():
    facts = {"title": "Luma's Big-Heart Forest Tales", "series": "Luma's Blue Dreams Forest"}
    text = (
        "Luma's Big-Heart Forest Tales, part of Luma's Blue Dreams Forest, Book 7 of 8. "
        "#LumaStories #BlueDreamsForest"
    )
    _validate_current_release_metadata("instagram", text, facts)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Discover the story, coming September 13, 2026.", True),
        ("Discover the story, coming soon.", True),
        ("Coming 2026!", True),
        ("Now available on Amazon.", False),
        ("Good things are coming her way.", False),
        ("The plot is coming together nicely.", False),
    ],
)
def test_reads_as_not_yet_available_matches_broad_future_language(text, expected):
    assert _reads_as_not_yet_available(text) is expected


def test_published_teaser_with_future_date_is_rejected():
    # This is exactly the shape of the real bug: a published release whose teaser
    # still reads like a pre-launch announcement.
    with pytest.raises(ValidationError, match="reads as not-yet-available"):
        _validate_release_field_contract(
            "teaser",
            "Luma paints stones to mark a path. Discover the story, coming September 13, 2026.",
            status="published",
            release_url="",
        )


def test_scheduled_teaser_with_future_date_is_still_allowed():
    # A scheduled (not-yet-published) release SHOULD read as upcoming — this must
    # not become a false positive for the normal, correct case.
    _validate_release_field_contract(
        "teaser",
        "Discover the story, coming September 13, 2026.",
        status="scheduled",
        release_url="",
    )
