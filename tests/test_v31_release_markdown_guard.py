"""Regression test for the v30 bug where a published release post contained
literal Markdown emphasis (`*Title*`) because `release_cmd`'s post_validate
never called `_reject_social_formatting` — that guard was only wired into
`regenerate_output_field` and `evergreen_cmd`, not the main release flow that
actually produced the launch posts.
"""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from author_agent import main
from author_agent.errors import ValidationError
from tests.test_main import FakeStore
from tests.test_social_retry import _base_release_args, _book, _patch_common


def test_release_auto_inserts_paragraph_breaks_after_retries_are_exhausted(tmp_path, monkeypatch):
    """The model keeps returning a long single-block Facebook draft (the exact bug
    reported: 203 words, no \\n\\n) on every retry. After the extended formatting
    retry budget is exhausted, the pipeline should split it into paragraphs at
    sentence boundaries in code, rather than hard-failing the whole release."""
    _patch_common(monkeypatch, tmp_path)
    book = _book(tmp_path)
    calls = []
    sentences = [f"This is sentence number {i} about Yok and Tibo." for i in range(20)]
    long_single_block = " ".join(sentences)  # >80 words, zero \n\n

    def fake_generate_json(base_url, model, prompt, timeout):
        calls.append(prompt)
        return {
            "facebook": long_single_block,
            "instagram": "Now available: Yok Helps a Friend — link in bio. #Books",
            "teaser": "What happens next in Yok Helps a Friend?",
        }

    monkeypatch.setattr(main, "generate_json", fake_generate_json)
    with patch.object(main, "prepare_website_update", return_value={"status": "dry-run", "diff": "d", "branch": "b"}):
        result, _ = main.release_cmd(_base_release_args(tmp_path, book), emit=False)
    assert len(calls) == 4  # extended formatting retry budget, same as the Markdown case
    fb = result["social"]["facebook"]
    assert "\n\n" in fb
    # The auto-fix must never touch the actual words, only insert paragraph breaks.
    assert fb.replace("\n\n", " ") == long_single_block


def test_release_still_fails_if_text_has_no_sentence_boundaries_to_split_on(tmp_path, monkeypatch):
    """Safety valve: if the long block has no recognizable sentence boundaries at
    all, the conservative splitter must refuse to guess and the release must still
    fail loudly rather than silently publish an unreadable wall of text."""
    _patch_common(monkeypatch, tmp_path)
    book = _book(tmp_path)
    calls = []
    no_punctuation_block = " ".join(f"word{i}" for i in range(90))  # >80 words, no . ! ?

    def fake_generate_json(base_url, model, prompt, timeout):
        calls.append(prompt)
        return {
            "facebook": no_punctuation_block,
            "instagram": "Now available: Yok Helps a Friend — link in bio. #Books",
            "teaser": "What happens next in Yok Helps a Friend?",
        }

    monkeypatch.setattr(main, "generate_json", fake_generate_json)
    with pytest.raises(ValidationError):
        main.release_cmd(_base_release_args(tmp_path, book), emit=False)
    assert len(calls) == 4


def test_release_still_fails_if_autostrip_result_breaks_a_different_check(tmp_path, monkeypatch):
    """If stripping the Markdown still leaves text that fails a *different* check
    (here: a long single-block paragraph with no \\n\\n separator and no sentence
    boundaries), the run must still hard-fail rather than silently publish
    something broken."""
    _patch_common(monkeypatch, tmp_path)
    book = _book(tmp_path)
    calls = []
    long_single_block = "*" + " ".join(f"word{i}" for i in range(90)) + "*"

    def fake_generate_json(base_url, model, prompt, timeout):
        calls.append(prompt)
        return {
            "facebook": long_single_block,
            "instagram": "Now available: Yok Helps a Friend — link in bio. #Books",
            "teaser": "What happens next in Yok Helps a Friend?",
        }

    monkeypatch.setattr(main, "generate_json", fake_generate_json)
    with pytest.raises(ValidationError):
        main.release_cmd(_base_release_args(tmp_path, book), emit=False)
    # Markdown failures get the extended retry budget (4 attempts), not just 2.
    assert len(calls) == 4


def test_release_auto_strips_markdown_after_retries_are_exhausted(tmp_path, monkeypatch):
    """The model keeps wrapping the title in asterisks on every retry. After the
    extended markdown retry budget is exhausted, the pipeline should sanitize the
    text in code and still produce a publishable, Markdown-free result instead of
    hard-failing the whole release."""
    _patch_common(monkeypatch, tmp_path)
    book = _book(tmp_path)
    calls = []

    def fake_generate_json(base_url, model, prompt, timeout):
        calls.append(prompt)
        return {
            "facebook": "Now available: *Yok Helps a Friend*, book four in the series.",
            "instagram": "Now available: *Yok Helps a Friend* — link in bio. #Books",
            "teaser": "What happens next in *Yok Helps a Friend*?",
        }

    monkeypatch.setattr(main, "generate_json", fake_generate_json)
    with patch.object(main, "prepare_website_update", return_value={"status": "dry-run", "diff": "d", "branch": "b"}):
        result, _ = main.release_cmd(_base_release_args(tmp_path, book), emit=False)
    # Extended markdown retry budget: 4 attempts, all still markdown, then auto-strip.
    assert len(calls) == 4
    assert "*" not in result["social"]["facebook"]
    assert result["social"]["facebook"] == "Now available: Yok Helps a Friend, book four in the series."


def test_release_accepts_plain_text_social_copy(tmp_path, monkeypatch):
    _patch_common(monkeypatch, tmp_path)
    book = _book(tmp_path)

    def fake_generate_json(base_url, model, prompt, timeout):
        return {
            "facebook": "Now available: Yok Helps a Friend, book four in the series.\n\nIt's a story about listening.",
            "instagram": "Now available: Yok Helps a Friend — link in bio. #Books #Kids",
            "teaser": "What happens next in Yok Helps a Friend?",
        }

    monkeypatch.setattr(main, "generate_json", fake_generate_json)
    with patch.object(main, "prepare_website_update", return_value={"status": "dry-run", "diff": "d", "branch": "b"}):
        result, _ = main.release_cmd(_base_release_args(tmp_path, book), emit=False)
    assert "*" not in result["social"]["facebook"]
