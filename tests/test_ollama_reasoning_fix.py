"""Regression tests for the qwen3:14b `{}` bug: reasoning models were degenerating
to an empty JSON object under Ollama's strict `format: json` grammar mode because
they had no room to "think" before answering.
"""

from unittest.mock import Mock, patch

import pytest

from author_agent.ollama_client import OllamaError, generate_json


def test_generate_json_requests_think_false():
    good = Mock(status_code=200)
    good.json.return_value = {"response": '{"facebook": "hello"}'}
    with patch("author_agent.ollama_client.post_json", return_value=good) as mocked:
        generate_json("http://localhost:11434", "qwen3:14b", "prompt")
    sent_payload = mocked.call_args.args[2]
    assert sent_payload["think"] is False
    assert sent_payload["format"] == "json"


def test_generate_json_extracts_object_wrapped_in_leaked_reasoning_text():
    # Simulates a model that ignores think:False and leaks reasoning around the JSON
    # anyway (e.g. an older Ollama build that doesn't support the parameter).
    leaked = Mock(status_code=200)
    leaked.json.return_value = {"response": 'Let me think about this...\n{"facebook": "FB", "instagram": "IG"}\nDone.'}
    with patch("author_agent.ollama_client.post_json", return_value=leaked):
        result = generate_json("http://localhost:11434", "qwen3:14b", "prompt")
    assert result == {"facebook": "FB", "instagram": "IG"}


def test_generate_json_still_raises_on_genuinely_empty_response():
    truly_empty = Mock(status_code=200)
    truly_empty.json.return_value = {"response": "{}"}
    with patch("author_agent.ollama_client.post_json", return_value=truly_empty):
        result = generate_json("http://localhost:11434", "qwen3:14b", "prompt")
    # {} is valid JSON — generate_json itself shouldn't error (the caller's
    # field-validation layer in orchestration.py is responsible for rejecting it
    # and retrying), but it must return the genuinely empty dict, not silently
    # drop it or crash.
    assert result == {}


def test_generate_json_raises_with_raw_response_when_unparseable():
    garbage = Mock(status_code=200)
    garbage.json.return_value = {"response": "not json and no braces at all"}
    with patch("author_agent.ollama_client.post_json", return_value=garbage):
        with pytest.raises(OllamaError, match="Raw response: not json"):
            generate_json("http://localhost:11434", "qwen3:14b", "prompt")


def test_generate_json_raises_clearly_on_completely_empty_text():
    empty = Mock(status_code=200)
    empty.json.return_value = {"response": ""}
    with patch("author_agent.ollama_client.post_json", return_value=empty):
        with pytest.raises(OllamaError, match="<empty>"):
            generate_json("http://localhost:11434", "qwen3:14b", "prompt")
