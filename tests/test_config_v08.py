from pathlib import Path

import pytest

from author_agent.config import load_settings
from author_agent.errors import ConfigError
from author_agent.web_push_gate import consume, get_prepared, issue_token


def _write_settings(root: Path, extra: str = "") -> None:
    config = root / "config"
    config.mkdir(parents=True)
    (config / "settings.yaml").write_text(
        """
ollama:
  base_url: http://localhost:11434
  marketing_model: qwen3:14b
  coding_model: devstral-small-2:latest
  review_model: gemma4:12b
  embedding_model: embeddinggemma:latest
  timeout_seconds: 240
orchestrator:
  window_days: 1
  daily_run_time: "09:00"
"""
        + extra,
        encoding="utf-8",
    )


def test_typed_settings_merge_local_and_environment(tmp_path, monkeypatch):
    _write_settings(tmp_path)
    (tmp_path / "config/settings.local.yaml").write_text(
        "orchestrator:\n  window_days: 3\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("AUTHOR_AGENT__OLLAMA__TIMEOUT_SECONDS", "123")
    settings = load_settings(tmp_path)
    assert settings.orchestrator.window_days == 3
    assert settings.ollama.timeout_seconds == 123


def test_typed_settings_fail_fast_on_bad_time(tmp_path):
    _write_settings(tmp_path)
    (tmp_path / "config/settings.local.yaml").write_text(
        "orchestrator:\n  daily_run_time: tomorrow\n",
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="daily_run_time"):
        load_settings(tmp_path)


def test_push_gate_survives_cache_restart(tmp_path):
    cache: dict[str, dict] = {}
    token = issue_token(tmp_path, cache, "release.json", "author-agent/x", ttl_seconds=300)
    restarted_cache: dict[str, dict] = {}
    prepared = get_prepared(tmp_path, restarted_cache, "release.json")
    assert prepared is not None
    assert prepared["token"] == token
    assert prepared["branch"] == "author-agent/x"
    consume(tmp_path, restarted_cache, "release.json")
    assert get_prepared(tmp_path, {}, "release.json") is None


def test_typed_settings_reject_bad_rag_threshold_order(tmp_path):
    _write_settings(
        tmp_path,
        "\nrag:\n  db_path: data/rag.sqlite3\n  warning_threshold: 0.9\n  duplicate_threshold: 0.8\n",
    )
    with pytest.raises(ConfigError, match="duplicate_threshold"):
        load_settings(tmp_path)


def test_typed_settings_reject_empty_required_local_fields(tmp_path):
    _write_settings(
        tmp_path,
        '\nrag:\n  db_path: ""\nwebsite:\n  branch_prefix: ""\n',
    )
    with pytest.raises(ConfigError, match="db_path"):
        load_settings(tmp_path)
