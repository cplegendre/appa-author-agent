from __future__ import annotations

from author_agent import main
from author_agent.errors import ValidationError
from author_agent.orchestration import (
    _current_release_facts,
    _validate_release_field_contract,
)


def test_style_sanitizer_masks_urls_footer_title_series_and_numbers():
    text = (
        "Yok's bilingual journey continues!\n\n"
        "📚 Yok Has Big Feelings\n"
        "A Bilingual Yok Story · Book 3 of 6\n\n"
        "Yok Has Big Feelings is now available here:\n"
        "https://www.amazon.com/dp/B0HGB8DSHB"
    )
    sanitized = main._sanitize_style_text(text)
    assert "B0HGB8DSHB" not in sanitized
    assert "Yok Has Big Feelings" not in sanitized
    assert "A Bilingual Yok Story" not in sanitized
    assert "Book 3 of 6" not in sanitized
    assert "[BOOK_TITLE]" in sanitized
    assert "[SERIES_NAME]" in sanitized
    assert "Book [BOOK_NUMBER] of [SERIES_TOTAL]" in sanitized
    assert "[RELEASE_URL]" in sanitized


def test_current_release_facts_are_explicit_and_authoritative():
    facts = _current_release_facts(
        {
            "title": "Yok's First Friend",
            "series": "A Yok Story",
            "book_number": "1",
            "series_total": "10",
        },
        status="published",
        release_date="2026-09-13",
        release_url="https://www.amazon.com/dp/B0H72C7X1N",
    )
    assert facts == {
        "title": "Yok's First Friend",
        "series": "A Yok Story",
        "book_number": "1",
        "series_total": "10",
        "status": "published",
        "release_date": "2026-09-13",
        "release_url": "https://www.amazon.com/dp/B0H72C7X1N",
    }


def test_strict_metadata_rejects_historical_title_leak():
    facts = {
        "title": "Yok's First Friend",
        "series": "A Yok Story",
        "book_number": "1",
        "series_total": "10",
        "status": "published",
        "release_date": "2026-09-13",
        "release_url": "https://www.amazon.com/dp/B0H72C7X1N",
    }
    bad = (
        "Yok Takes a Step — A Yok Story, Book 7\n"
        "Now available: https://www.amazon.com/dp/B0H72C7X1N"
    )
    try:
        _validate_release_field_contract(
            "facebook",
            bad,
            status="published",
            release_url=facts["release_url"],
            require_release_metadata=True,
            release_facts=facts,
        )
    except ValidationError as exc:
        assert "current book title" in str(exc) or "wrong book number" in str(exc)
    else:
        raise AssertionError("historical title/book-number leakage must be rejected")


def test_strict_metadata_accepts_exact_current_release_metadata():
    facts = {
        "title": "Yok's First Friend",
        "series": "A Yok Story",
        "book_number": "1",
        "series_total": "10",
        "status": "published",
        "release_date": "2026-09-13",
        "release_url": "https://www.amazon.com/dp/B0H72C7X1N",
    }
    good = (
        "Yok's First Friend\n"
        "A Yok Story · Book 1 of 10\n"
        "Now available in paperback on Amazon:\n"
        "https://www.amazon.com/dp/B0H72C7X1N"
    )
    _validate_release_field_contract(
        "facebook",
        good,
        status="published",
        release_url=facts["release_url"],
        require_release_metadata=True,
        release_facts=facts,
    )
