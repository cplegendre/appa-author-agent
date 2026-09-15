from __future__ import annotations

from unittest.mock import Mock, patch

import pytest
import requests

from author_agent.ollama_client import OllamaError, generate_json, post_json


def test_post_json_returns_404_without_retrying(tmp_path=None):
    not_found = Mock(status_code=404)
    with patch("author_agent.ollama_client.requests.post", return_value=not_found) as post:
        result = post_json("http://localhost:11434", "/api/embed", {}, retries=3)
    assert result is not_found
    # 404 is returned immediately to let the caller decide (legacy-endpoint probing).
    assert post.call_count == 1


def test_post_json_retries_on_429_then_succeeds():
    rate_limited = Mock(status_code=429, text="slow down")
    ok = Mock(status_code=200)
    ok.raise_for_status.return_value = None
    with (
        patch("author_agent.ollama_client.requests.post", side_effect=[rate_limited, ok]) as post,
        patch("author_agent.ollama_client.time.sleep") as sleep,
    ):
        result = post_json("http://localhost:11434", "/api/generate", {}, retries=3)
    assert result is ok
    assert post.call_count == 2
    sleep.assert_called_once()


def test_post_json_retries_on_5xx_and_eventually_raises_actionable_error():
    server_error = Mock(status_code=503, text="unavailable")
    with (
        patch("author_agent.ollama_client.requests.post", return_value=server_error),
        patch("author_agent.ollama_client.time.sleep"),
    ):
        with pytest.raises(OllamaError, match="not reachable"):
            post_json("http://localhost:11434", "/api/generate", {}, retries=2)


def test_post_json_uses_exponential_backoff_timing():
    with (
        patch("author_agent.ollama_client.requests.post", side_effect=requests.Timeout("slow")),
        patch("author_agent.ollama_client.time.sleep") as sleep,
    ):
        with pytest.raises(OllamaError):
            post_json("http://localhost:11434", "/api/generate", {}, retries=3, backoff_seconds=2.0)
    # attempts 1 and 2 sleep (2*2^0=2, 2*2^1=4); attempt 3 fails without sleeping again.
    assert [call.args[0] for call in sleep.call_args_list] == [2.0, 4.0]


def test_generate_json_raises_actionable_error_on_404():
    not_found = Mock(status_code=404)
    with patch("author_agent.ollama_client.post_json", return_value=not_found):
        with pytest.raises(OllamaError, match="was not found"):
            generate_json("http://localhost:11434", "qwen3:14b", "prompt")


def test_generate_json_raises_on_invalid_json_body():
    bad = Mock(status_code=200)
    bad.json.return_value = {"response": "not valid json {{{"}
    with patch("author_agent.ollama_client.post_json", return_value=bad):
        with pytest.raises(OllamaError, match="Invalid JSON response"):
            generate_json("http://localhost:11434", "qwen3:14b", "prompt")


def test_generate_json_parses_valid_response():
    good = Mock(status_code=200)
    good.json.return_value = {"response": '{"facebook": "hello"}'}
    with patch("author_agent.ollama_client.post_json", return_value=good):
        result = generate_json("http://localhost:11434", "qwen3:14b", "prompt")
    assert result == {"facebook": "hello"}
