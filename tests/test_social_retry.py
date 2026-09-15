"""Regression tests for the bug reported against v0.10/v0.11:

    social_payload_missing_fields
    "The model response is missing usable social draft(s): facebook, instagram,
    teaser (keys=)."

`keys=` with nothing after the `=` meant Ollama returned a syntactically valid but
*empty* JSON object (`{}`) for the social-copy prompt. This happens occasionally with
`format: json` mode, especially under a tight timeout or with certain marketing
models, and previously failed the whole release/evergreen run on the very first miss.

These tests cover the fix: one automatic retry with a corrective follow-up prompt,
and a raw-response sample surfaced in both the log line and the raised error so this
is diagnosable from the CLI/web UI output alone next time.
"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from author_agent import main
from author_agent.errors import ValidationError
from tests.test_main import FakeStore


def _book(tmp_path: Path) -> Path:
    book = tmp_path / "book.txt"
    book.write_text("A tiny story")
    return book


def _base_release_args(tmp_path: Path, book: Path) -> SimpleNamespace:
    return SimpleNamespace(book=str(book), image="", date="2026-09-13", url="https://x", published=True, dry_run=True)


def _patch_common(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(main, "ROOT", tmp_path)
    monkeypatch.setattr(main, "rag_store", lambda: FakeStore())
    monkeypatch.setattr(
        main, "analyze_book", lambda p: {"title": "Tiny Book", "themes": ["kindness"], "plot_summary": "x"}
    )


def test_release_retries_once_after_empty_payload_then_succeeds(tmp_path, monkeypatch):
    _patch_common(monkeypatch, tmp_path)
    book = _book(tmp_path)
    calls = []

    def fake_generate_json(base_url, model, prompt, timeout):
        calls.append(prompt)
        if len(calls) == 1:
            return {}  # exactly what the real bug report showed: keys=
        return {"facebook": "FB", "instagram": "IG #tag", "teaser": "T"}

    monkeypatch.setattr(main, "generate_json", fake_generate_json)
    with patch.object(main, "prepare_website_update", return_value={"status": "dry-run", "diff": "d", "branch": "b"}):
        result, _ = main.release_cmd(_base_release_args(tmp_path, book), emit=False)

    assert len(calls) == 2, "expected exactly one retry after the empty first response"
    assert result["social"]["facebook"] == "FB"
    # The retry prompt must be corrective, not an identical repeat of the first one.
    assert "your previous response was invalid" in calls[1]
    assert "facebook, instagram, teaser" in calls[1]


def test_release_fails_after_retry_still_empty_with_diagnostic_sample(tmp_path, monkeypatch):
    _patch_common(monkeypatch, tmp_path)
    book = _book(tmp_path)
    monkeypatch.setattr(main, "generate_json", lambda *a, **k: {})

    with pytest.raises(ValidationError) as excinfo:
        main.release_cmd(_base_release_args(tmp_path, book), emit=False)

    message = str(excinfo.value)
    # Must no longer be the old, undiagnosable "keys=" with nothing else to go on.
    assert "sample=" in message
    assert "Model response after retry" in message


def test_release_second_attempt_uses_corrective_prompt_not_plain_retry(tmp_path, monkeypatch):
    _patch_common(monkeypatch, tmp_path)
    book = _book(tmp_path)
    calls = []

    def fake_generate_json(base_url, model, prompt, timeout):
        calls.append(prompt)
        return {"facebook": "FB"} if len(calls) == 1 else {"facebook": "FB", "instagram": "IG", "teaser": "T"}

    monkeypatch.setattr(main, "generate_json", fake_generate_json)
    with patch.object(main, "prepare_website_update", return_value={"status": "dry-run", "diff": "d", "branch": "b"}):
        result, _ = main.release_cmd(_base_release_args(tmp_path, book), emit=False)

    assert result["social"]["instagram"] == "IG"
    assert "instagram" in calls[1] and "teaser" in calls[1]


def test_evergreen_retries_once_after_empty_payload(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "ROOT", tmp_path)
    monkeypatch.setattr(main, "rag_store", lambda: FakeStore())
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "post_history.json").write_text("[]", encoding="utf-8")
    calls = []

    def fake_generate_json(base_url, model, prompt, timeout):
        calls.append(prompt)
        if len(calls) == 1:
            return {}
        return {"facebook": "FB", "instagram": "IG"}

    monkeypatch.setattr(main, "generate_json", fake_generate_json)
    result, _ = main.evergreen_cmd(SimpleNamespace(date="2026-09-13", dry_run=True), emit=False)
    assert len(calls) == 2
    assert result["facebook"] == "FB"


def test_still_only_retries_once_not_indefinitely(tmp_path, monkeypatch):
    """Guard against an infinite-retry regression: three empty responses must still
    fail after exactly two total attempts, not loop."""
    _patch_common(monkeypatch, tmp_path)
    book = _book(tmp_path)
    calls = []

    def fake_generate_json(base_url, model, prompt, timeout):
        calls.append(prompt)
        return {}

    monkeypatch.setattr(main, "generate_json", fake_generate_json)
    with pytest.raises(ValidationError):
        main.release_cmd(_base_release_args(tmp_path, book), emit=False)
    assert len(calls) == 2
