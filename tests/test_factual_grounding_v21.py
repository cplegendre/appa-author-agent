from __future__ import annotations

from pathlib import Path

import pytest

from author_agent.book_evidence import retrieve_book_evidence
from author_agent.orchestration import (
    FactualGroundingError,
    OrchestrationDeps,
    _factual_rejections,
    _generate_social_with_retry,
    _validate_factual_grounding,
)


class FakeStore:
    embedding_model = "fake"

    def embed(self, text: str) -> list[float]:
        lowered = text.lower()
        return [float(lowered.count("tom") + lowered.count("wait")), float(lowered.count("park"))]

    @staticmethod
    def _cosine(a, b):
        # Deliberately simple deterministic score for the retrieval unit test.
        return sum(x * y for x, y in zip(a, b))


def test_book_evidence_retrieves_relevant_current_book_passage(tmp_path: Path):
    book = tmp_path / "book.txt"
    book.write_text(
        "Yok stays near the tree at the park.\n\n"
        "Tom waited patiently while Yok found her courage.\n\n"
        "The family went home.",
        encoding="utf-8",
    )
    hits = retrieve_book_evidence(FakeStore(), book, "Tom does not rush Yok; he waits", top_k=1)
    assert len(hits) == 1
    assert "waited patiently" in hits[0]["text"]


def test_claim_classifier_accepts_paraphrase_and_rejects_only_bad_statuses():
    review = {
        "claims": [
            {"text": "Tom doesn't rush her", "status": "supported_paraphrase"},
            {"text": "Tom nods", "status": "unsupported", "reason": "No nod in evidence"},
            {"text": "first time at park", "status": "contradicted", "evidence": "I've seen you here before."},
        ],
        "unsupported_claims": ["legacy duplicate should not be added"],
    }
    rejected = _factual_rejections(review)
    assert [item["text"] for item in rejected] == ["Tom nods", "first time at park"]
    assert rejected[1]["status"] == "contradicted"


def _deps(review_payload, evidence):
    return OrchestrationDeps(
        root=Path("."),
        settings={},
        rag_store=lambda: object(),
        analyze_book=lambda _p: {},
        generate_json=lambda *_a, **_k: review_payload,
        render=lambda *_a, **_k: "review prompt",
        prepare_website_update=lambda *_a, **_k: {},
        duplicate_report=lambda *_a, **_k: {},
        rag_context=lambda *_a, **_k: [],
        style_examples=lambda *_a, **_k: {},
        brand_voice={"factual_review_enabled": True},
        user_output=lambda _v: None,
        book_evidence=lambda *_a, **_k: evidence,
    )


def test_grounding_reviewer_uses_book_evidence_and_allows_supported_paraphrase(tmp_path: Path):
    book = tmp_path / "book.txt"
    book.write_text("Tom waited patiently while Yok found her courage.", encoding="utf-8")
    captured = {}

    def render(_template, **kwargs):
        captured.update(kwargs)
        return "review"

    deps = _deps(
        {
            "supported": True,
            "claims": [
                {
                    "text": "Tom doesn't rush her",
                    "status": "supported_paraphrase",
                    "evidence": "Tom waited patiently while Yok found her courage.",
                    "reason": "Faithful paraphrase",
                }
            ],
            "unsupported_claims": [],
        },
        [{"page": 18, "text": "Tom waited patiently while Yok found her courage."}],
    )
    object.__setattr__(deps, "render", render)
    _validate_factual_grounding(
        deps,
        {"base_url": "http://localhost", "marketing_model": "qwen", "review_model": "gemma"},
        {"title": "Book"},
        {"facebook": "Tom doesn't rush her."},
        book_path=book,
    )
    assert captured["BOOK_EVIDENCE"][0]["page"] == 18


def test_grounding_error_distinguishes_unsupported_and_contradicted(tmp_path: Path):
    book = tmp_path / "book.txt"
    book.write_text("I've seen you here before.", encoding="utf-8")
    deps = _deps(
        {
            "supported": False,
            "claims": [
                {"text": "Tom nods", "status": "unsupported", "reason": "Not in evidence"},
                {
                    "text": "Yok's first time at the park",
                    "status": "contradicted",
                    "evidence": "I've seen you here before.",
                    "reason": "Explicit contradiction",
                },
            ],
            "unsupported_claims": [],
        },
        [{"page": 13, "text": "I've seen you here before."}],
    )
    with pytest.raises(FactualGroundingError) as exc_info:
        _validate_factual_grounding(
            deps,
            {"base_url": "http://localhost", "marketing_model": "qwen", "review_model": "gemma"},
            {"title": "Book"},
            {"facebook": "Tom nods. This is Yok's first time at the park."},
            book_path=book,
        )
    correction = exc_info.value.corrective_prompt()
    assert "[unsupported] Tom nods" in correction
    assert "[contradicted] Yok's first time at the park" in correction
    assert "Do NOT replace a rejected detail with a different invented detail" in correction
    assert "[page 13]" in correction


def test_retry_prompt_contains_claim_level_correction_and_verified_evidence():
    prompts = []
    calls = {"count": 0}

    def generate_json(_url, _model, prompt, _timeout):
        prompts.append(prompt)
        calls["count"] += 1
        return {"facebook": "draft one"} if calls["count"] == 1 else {"facebook": "draft two"}

    deps = OrchestrationDeps(
        root=Path("."),
        settings={},
        rag_store=lambda: None,
        analyze_book=lambda _p: {},
        generate_json=generate_json,
        render=lambda *_a, **_k: "BASE PROMPT",
        prepare_website_update=lambda *_a, **_k: {},
        duplicate_report=lambda *_a, **_k: {},
        rag_context=lambda *_a, **_k: [],
        style_examples=lambda *_a, **_k: {},
        brand_voice={},
        user_output=lambda _v: None,
    )
    validations = {"count": 0}

    def validate(_payload):
        validations["count"] += 1
        if validations["count"] == 1:
            raise FactualGroundingError(
                [{"text": "Tom nods", "status": "unsupported", "reason": "Not in book", "evidence": ""}],
                [{"page": 18, "text": "Tom waited patiently while Yok found her courage."}],
            )

    result = _generate_social_with_retry(
        deps,
        {"base_url": "http://localhost", "marketing_model": "qwen", "timeout_seconds": 10},
        "social_release.txt",
        ("facebook",),
        {},
        label="release",
        post_validate=validate,
    )
    assert result["facebook"] == "draft two"
    assert "REJECTED CLAIMS" in prompts[1]
    assert "Tom nods" in prompts[1]
    assert "VERIFIED BOOK PASSAGES" in prompts[1]
    assert "Tom waited patiently" in prompts[1]
