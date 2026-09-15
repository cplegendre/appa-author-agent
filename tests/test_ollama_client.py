from unittest.mock import Mock, patch

import pytest
import requests

from author_agent.ollama_client import OllamaError, post_json


def test_retry_then_success():
    ok = Mock(status_code=200)
    ok.raise_for_status.return_value = None
    with (
        patch(
            "author_agent.ollama_client.requests.post",
            side_effect=[requests.ConnectionError("x"), ok],
        ) as post,
        patch("author_agent.ollama_client.time.sleep"),
    ):
        assert post_json("http://localhost:11434", "/api/generate", {}, retries=3) is ok
        assert post.call_count == 2


def test_actionable_after_three_failures():
    with (
        patch(
            "author_agent.ollama_client.requests.post",
            side_effect=requests.ConnectionError("down"),
        ),
        patch("author_agent.ollama_client.time.sleep"),
    ):
        with pytest.raises(OllamaError, match="ollama serve"):
            post_json("http://localhost:11434", "/api/generate", {}, retries=3)
