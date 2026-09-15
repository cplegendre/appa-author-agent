from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock, patch

import pytest

from author_agent.errors import OllamaError
from author_agent.ollama_client import FACTUAL_REVIEW_SCHEMA, generate_factual_review_json
from author_agent.orchestration import OrchestrationDeps, _validate_factual_grounding


def _response(text: str, *, done_reason: str = "stop") -> Mock:
    response = Mock(status_code=200)
    response.json.return_value = {"response": text, "done_reason": done_reason}
    return response


def test_factual_review_uses_compact_schema_large_budget_and_no_thinking():
    good = _response('{"supported": true, "claims": []}')
    with patch("author_agent.ollama_client.post_json", return_value=good) as mocked:
        result = generate_factual_review_json("http://localhost:11434", "gemma4:12b", "review")
    assert result == {"supported": True, "claims": []}
    sent = mocked.call_args.args[2]
    assert sent["format"] == FACTUAL_REVIEW_SCHEMA
    assert sent["think"] is False
    assert sent["options"]["temperature"] == 0
    assert sent["options"]["num_predict"] == 4096


def test_factual_review_retries_once_after_truncated_json():
    truncated = _response(
        '{"supported": false, "claims": [{"text": "Luma is Lila", "status": "contradicted",',
        done_reason="length",
    )
    good = _response(
        '{"supported": false, "claims": '
        '[{"text": "Luma is Lila", "status": "contradicted", "reason": "The protagonist is Luma."}]}'
    )
    with patch("author_agent.ollama_client.post_json", side_effect=[truncated, good]) as mocked:
        result = generate_factual_review_json("http://localhost:11434", "gemma4:12b", "review")
    assert mocked.call_count == 2
    assert result["supported"] is False
    assert result["claims"][0]["status"] == "contradicted"
    retry_prompt = mocked.call_args_list[1].args[2]["prompt"]
    assert "previous response was incomplete or invalid JSON" in retry_prompt
    assert "Do not include supported claims" in retry_prompt


def test_factual_review_discards_supported_claims_if_model_ignores_schema():
    verbose = _response(
        '{"supported": false, "claims": ['
        '{"text": "Book 7", "status": "direct_fact", "evidence": "Book 7", "reason": "Supported"},'
        '{"text": "Lila is the protagonist", "status": "contradicted", "evidence": "Luma", '
        '"reason": "The protagonist is Luma."}'
        ']}'
    )
    with patch("author_agent.ollama_client.post_json", return_value=verbose):
        result = generate_factual_review_json("http://localhost:11434", "gemma4:12b", "review")
    assert result == {
        "supported": False,
        "claims": [
            {
                "text": "Lila is the protagonist",
                "status": "contradicted",
                "reason": "The protagonist is Luma.",
            }
        ],
    }


def test_factual_review_fails_after_exactly_one_parser_retry():
    bad1 = _response('{"supported": false, "claims": [', done_reason="length")
    bad2 = _response('{"supported": false, "claims": [', done_reason="length")
    with patch("author_agent.ollama_client.post_json", side_effect=[bad1, bad2]) as mocked:
        with pytest.raises(OllamaError, match="after one retry"):
            generate_factual_review_json("http://localhost:11434", "gemma4:12b", "review")
    assert mocked.call_count == 2


def test_orchestration_prefers_specialized_factual_review_generator(tmp_path: Path):
    book = tmp_path / "book.txt"
    book.write_text("The protagonist is Luma.", encoding="utf-8")
    calls = {"generic": 0, "review": 0}

    def generic(*_args, **_kwargs):
        calls["generic"] += 1
        return {"supported": True, "claims": []}

    def review(*_args, **_kwargs):
        calls["review"] += 1
        return {"supported": True, "claims": []}

    deps = OrchestrationDeps(
        root=tmp_path,
        settings={},
        rag_store=lambda: object(),
        analyze_book=lambda _p: {},
        generate_json=generic,
        render=lambda *_a, **_k: "review prompt",
        prepare_website_update=lambda *_a, **_k: {},
        duplicate_report=lambda *_a, **_k: {},
        rag_context=lambda *_a, **_k: [],
        style_examples=lambda *_a, **_k: {},
        brand_voice={"factual_review_enabled": True},
        user_output=lambda _v: None,
        book_evidence=lambda *_a, **_k: [{"page": 1, "text": "The protagonist is Luma."}],
        factual_review_json=review,
    )
    _validate_factual_grounding(
        deps,
        {"base_url": "http://localhost", "marketing_model": "qwen", "review_model": "gemma"},
        {"title": "Luma"},
        {"facebook": "Luma explores."},
        book_path=book,
    )
    assert calls == {"generic": 0, "review": 1}
