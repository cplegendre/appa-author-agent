from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from author_agent import main


class FakeStore:
    def __init__(self):
        self.rows = []

    def search(self, *args, **kwargs):
        return []

    def upsert(self, **kwargs):
        self.rows.append(kwargs)
        return len(self.rows)

    def stats(self):
        return {"total": len(self.rows), "by_kind": {}, "by_platform": {}}


def _config(tmp_path, content="releases: []\n"):
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    (tmp_path / "config/releases.yaml").write_text(content)


def test_today_idempotent(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(main, "ROOT", tmp_path)
    (tmp_path / "output").mkdir()
    _config(tmp_path)
    (tmp_path / "output/today-2026-09-13.json").write_text('{"output":"x"}')
    got = main.today_cmd(SimpleNamespace(date="2026-09-13", window=1, force=False, dry_run=False))
    assert got["output"] == "x"
    assert "Already generated" in capsys.readouterr().out


def test_today_evergreen_when_no_release(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "ROOT", tmp_path)
    _config(tmp_path)
    with patch.object(main, "evergreen_cmd", return_value=({"x": 1}, tmp_path / "output/e.json")) as evergreen:
        got = main.today_cmd(SimpleNamespace(date="2026-09-13", window=1, force=False, dry_run=False))
        evergreen.assert_called_once()
        assert got["mode"] == "evergreen"


def test_today_release_day_selected(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "ROOT", tmp_path)
    _config(tmp_path, "releases:\n  - date: 2026-09-13\n    book: /book.txt\n    image: /promo.png\n")
    with patch.object(main, "release_cmd", return_value=({}, tmp_path / "output/r.json")) as release:
        got = main.today_cmd(SimpleNamespace(date="2026-09-13", window=2, force=False, dry_run=True))
        args = release.call_args.args[0]
        assert args.published is True
        assert args.dry_run is True
        assert got["mode"] == "release"
        assert "output/dry-run" in str(tmp_path / "output/dry-run")


def test_today_future_release_in_window_is_teaser(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "ROOT", tmp_path)
    _config(tmp_path, "releases:\n  - date: 2026-09-14\n    book: /book.txt\n")
    with patch.object(main, "release_cmd", return_value=({}, tmp_path / "output/r.json")) as release:
        got = main.today_cmd(SimpleNamespace(date="2026-09-13", window=1, force=False, dry_run=False))
        assert release.call_args.args[0].published is False
        assert got["mode"] == "teaser"


def test_today_release_outside_window_is_evergreen(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "ROOT", tmp_path)
    _config(tmp_path, "releases:\n  - date: 2026-09-20\n    book: /book.txt\n")
    with patch.object(main, "evergreen_cmd", return_value=({}, tmp_path / "output/e.json")) as evergreen:
        got = main.today_cmd(SimpleNamespace(date="2026-09-13", window=1, force=False, dry_run=False))
        evergreen.assert_called_once()
        assert got["mode"] == "evergreen"


def test_today_force_bypasses_manifest(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "ROOT", tmp_path)
    (tmp_path / "output").mkdir()
    _config(tmp_path)
    (tmp_path / "output/today-2026-09-13.json").write_text('{"output":"old"}')
    with patch.object(main, "evergreen_cmd", return_value=({}, tmp_path / "output/new.json")) as evergreen:
        got = main.today_cmd(SimpleNamespace(date="2026-09-13", window=1, force=True, dry_run=False))
        evergreen.assert_called_once()
        assert got["output"].endswith("new.json")


def test_today_errors_on_invalid_release_date(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "ROOT", tmp_path)
    _config(tmp_path, "releases:\n  - date: nope\n    book: x\n")
    with pytest.raises(ValueError, match="Invalid release date"):
        main.today_cmd(SimpleNamespace(date="2026-09-13", window=1, force=False, dry_run=False))


def test_today_errors_on_missing_book(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "ROOT", tmp_path)
    _config(tmp_path, "releases:\n  - date: 2026-09-13\n    title: Missing Book Path\n")
    with pytest.raises(ValueError, match="missing `book`"):
        main.today_cmd(SimpleNamespace(date="2026-09-13", window=1, force=False, dry_run=False))


def test_release_cmd_generates_report_preview_and_dry_run_output(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "ROOT", tmp_path)
    book = tmp_path / "book.txt"
    book.write_text("A tiny story")
    image = tmp_path / "promo.png"
    image.write_bytes(b"png")
    fake = FakeStore()
    monkeypatch.setattr(main, "rag_store", lambda: fake)
    monkeypatch.setattr(
        main,
        "analyze_book",
        lambda p: {"title": "Tiny Book", "themes": ["kindness"], "plot_summary": "x"},
    )
    monkeypatch.setattr(
        main,
        "generate_json",
        lambda *a, **k: {"facebook": "FB", "instagram": "IG #tag", "teaser": "T", "primary_angle": "kindness"},
    )
    website = patch.object(
        main,
        "prepare_website_update",
        return_value={"status": "dry-run", "diff": "d", "branch": "b"},
    )
    with website as website_call:
        args = SimpleNamespace(
            book=str(book), image=str(image), date="2026-09-13", url="https://x", published=True, dry_run=True
        )
        result, out = main.release_cmd(args, emit=False)
    assert out.parent.name == "dry-run"
    assert result["approved"] is False
    assert out.with_suffix(".md").exists()
    assert Path(result["preview"]).exists()
    assert website_call.call_args.kwargs["dry_run"] is True


def test_release_input_validation_happens_before_llm(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "ROOT", tmp_path)
    llm = patch.object(main, "analyze_book")
    with llm as mocked:
        with pytest.raises(ValueError, match="Book file not found"):
            main.release_cmd(
                SimpleNamespace(
                    book=str(tmp_path / "missing.pdf"),
                    image="",
                    date="2026-09-13",
                    url="",
                    published=False,
                    dry_run=False,
                ),
                emit=False,
            )
        mocked.assert_not_called()


def test_mark_approved_upserts_social_posts(tmp_path, monkeypatch):
    fake = FakeStore()
    monkeypatch.setattr(main, "rag_store", lambda: fake)
    p = tmp_path / "release.json"
    p.write_text(
        '{"date":"2026-09-13","social":{"facebook":"FB","instagram":"IG","primary_angle":"kindness"},"approved":false}'
    )
    got = main._approve_file(p, True)
    assert got["registered"] == ["facebook", "instagram"]
    assert len(fake.rows) == 2
    assert main.load_json(p, {})["rag_registered"] is True


def test_dry_run_cannot_be_marked_approved(tmp_path):
    p = tmp_path / "dry.json"
    p.write_text('{"date":"2026-09-13","social":{"facebook":"FB"},"approved":false,"dry_run":true}')
    with pytest.raises(ValueError, match="Dry-run outputs cannot be approved"):
        main._approve_file(p, True)


def test_release_candidates_reject_negative_window():
    with pytest.raises(ValueError, match="zero or greater"):
        main._release_candidates(main.date(2026, 9, 13), [], -1)
