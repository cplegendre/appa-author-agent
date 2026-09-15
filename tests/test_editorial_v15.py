from __future__ import annotations

from pathlib import Path

import pytest

from author_agent.brand_voice import load_brand_voice
from author_agent.errors import ValidationError
from author_agent.orchestration import _validate_release_field_contract
from author_agent.prompts import render


def test_brand_voice_has_factual_grounding_and_real_instagram_range():
    voice = load_brand_voice(Path(__file__).resolve().parents[1])
    assert voice.instagram.hashtag_min == 12
    assert voice.instagram.hashtag_max == 16
    joined = " ".join(voice.factual_grounding).lower()
    assert "never invent" in joined
    assert "pronoun" in joined
    assert "url" in joined


def test_release_prompt_requires_grounding_metadata_and_platform_specific_cta():
    prompt = render(
        "social_release.txt",
        RELEASE_STATUS="published",
        RELEASE_DATE="2026-09-13",
        RELEASE_URL="https://example.test/book",
        CURRENT_RELEASE_FACTS={
            "title": "Book",
            "series": "Series",
            "book_number": "1",
            "series_total": "6",
            "release_url": "https://example.test/book",
        },
        BOOK_PROFILE={"title": "Book", "series": "Series", "book_number": "1", "series_total": "6"},
        BOOK_EVIDENCE=[{"page": 4, "text": "Yok meets Tom."}],
        BRAND_VOICE={},
        RAG_CONTEXT=[],
        STYLE_EXAMPLES={},
    )
    assert "RETRIEVED PASSAGES FROM THE ACTUAL BOOK" in prompt
    assert "CURRENT RELEASE FACTS — AUTHORITATIVE" in prompt
    assert "override every value appearing in historical style examples" in prompt
    assert "Never infer character gender or pronouns" in prompt
    assert "Now available in paperback on Amazon:" in prompt
    assert "Now available on Amazon — link in bio" in prompt
    assert "12-16 relevant hashtags" in prompt
    assert "Do not summarize the book" in prompt


def test_facebook_rejects_invented_or_altered_url():
    with pytest.raises(ValidationError, match="invented or altered a URL"):
        _validate_release_field_contract(
            "facebook",
            "Read it here: https://wrong.example/book",
            status="published",
            release_url="https://right.example/book",
        )


def test_facebook_allows_exact_release_url():
    _validate_release_field_contract(
        "facebook",
        "Now available: https://right.example/book",
        status="published",
        release_url="https://right.example/book",
    )


def test_facebook_rejects_url_when_none_supplied():
    with pytest.raises(ValidationError, match="URLs must never be guessed"):
        _validate_release_field_contract(
            "facebook",
            "Now available: https://guessed.example/book",
            status="published",
            release_url="",
        )


def test_instagram_rejects_raw_url():
    with pytest.raises(ValidationError, match="must not print a raw URL"):
        _validate_release_field_contract(
            "instagram",
            "Link: https://example.test/book",
            status="published",
            release_url="https://example.test/book",
        )


def test_teaser_availability_rules_are_enforced():
    with pytest.raises(ValidationError, match="must not say `available now`"):
        _validate_release_field_contract("teaser", "Available now tomorrow!", status="scheduled", release_url="")
    with pytest.raises(ValidationError, match="reads as not-yet-available"):
        _validate_release_field_contract("teaser", "Coming soon!", status="published", release_url="")
