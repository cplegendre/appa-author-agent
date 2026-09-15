from __future__ import annotations


import pytest

from author_agent.errors import ValidationError
from author_agent.orchestration import (
    OrchestrationDeps,
    _validate_factual_grounding,
    _validate_release_field_contract,
)


def test_strict_facebook_requires_exact_supplied_url():
    with pytest.raises(ValidationError, match="omitted the supplied RELEASE_URL"):
        _validate_release_field_contract(
            "facebook",
            "Now available in paperback on Amazon:",
            status="published",
            release_url="https://amazon.example/book",
            require_release_metadata=True,
        )


def test_strict_facebook_accepts_exact_supplied_url():
    _validate_release_field_contract(
        "facebook",
        "Now available in paperback on Amazon:\nhttps://amazon.example/book",
        status="published",
        release_url="https://amazon.example/book",
        require_release_metadata=True,
    )


def test_instagram_enforces_link_in_bio_and_hashtag_range():
    with pytest.raises(ValidationError, match="link in bio"):
        _validate_release_field_contract(
            "instagram",
            "Published today. " + " ".join(f"#Tag{i}" for i in range(12)),
            status="published",
            release_url="https://amazon.example/book",
            require_release_metadata=True,
            hashtag_min=12,
            hashtag_max=16,
        )
    with pytest.raises(ValidationError, match="17 hashtags"):
        _validate_release_field_contract(
            "instagram",
            "Now available on Amazon — link in bio " + " ".join(f"#Tag{i}" for i in range(17)),
            status="published",
            release_url="https://amazon.example/book",
            require_release_metadata=True,
            hashtag_min=12,
            hashtag_max=16,
        )


def test_instagram_accepts_12_to_16_hashtags():
    _validate_release_field_contract(
        "instagram",
        "Now available on Amazon — link in bio " + " ".join(f"#Tag{i}" for i in range(14)),
        status="published",
        release_url="https://amazon.example/book",
        require_release_metadata=True,
        hashtag_min=12,
        hashtag_max=16,
    )


def _deps(review_payload):
    return OrchestrationDeps(
        root=None,  # type: ignore[arg-type]
        settings={},
        rag_store=lambda: None,
        analyze_book=lambda _p: {},
        generate_json=lambda *_a, **_k: review_payload,
        render=lambda *_a, **_k: "review prompt",
        prepare_website_update=lambda *_a, **_k: {},
        duplicate_report=lambda *_a, **_k: {},
        rag_context=lambda *_a, **_k: [],
        style_examples=lambda *_a, **_k: {},
        brand_voice={"factual_review_enabled": True},
        user_output=lambda _v: None,
    )


def test_factual_reviewer_blocks_unsupported_scene_detail():
    deps = _deps(
        {
            "supported": False,
            "unsupported_claims": ["The draft invents a sunlit park and a shared smile."],
            "notes": "Not in profile",
        }
    )
    with pytest.raises(ValidationError, match="unsupported story detail"):
        _validate_factual_grounding(
            deps,
            {"base_url": "http://localhost", "marketing_model": "qwen", "review_model": "gemma"},
            {"title": "Book", "plot_summary": "Yok meets Tom."},
            {"facebook": "A sunlit park..."},
        )


def test_factual_reviewer_allows_supported_copy():
    deps = _deps({"supported": True, "unsupported_claims": [], "notes": "Grounded"})
    _validate_factual_grounding(
        deps,
        {"base_url": "http://localhost", "marketing_model": "qwen", "review_model": "gemma"},
        {"title": "Book", "plot_summary": "Yok meets Tom."},
        {"facebook": "Yok meets Tom."},
    )
