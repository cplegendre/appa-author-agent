from pathlib import Path
import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from author_agent import main
from author_agent.rag import RagHit


class Store:
    def __init__(self, hits=None):
        self.hits = hits or []
        self.rows = []

    def search(self, *args, **kwargs):
        return self.hits

    def upsert(self, **kwargs):
        self.rows.append(kwargs)
        return 7

    def stats(self):
        return {"total": len(self.rows)}


def test_configure_logging_and_parser_flags(monkeypatch):
    with patch("author_agent.main.logging.basicConfig") as basic:
        main.configure_logging("DEBUG")
        assert basic.call_args.kwargs["level"] == main.logging.DEBUG
    args = main.parser().parse_args(["release", "--book", "b.txt", "--dry-run", "--published"])
    assert args.dry_run is True and args.published is True
    today = main.parser().parse_args(["today", "--dry-run", "--force", "--window", "2"])
    assert today.dry_run and today.force and today.window == 2


def test_analyze_book_uses_llm(tmp_path, monkeypatch):
    p = tmp_path / "book.txt"
    p.write_text("hello")
    monkeypatch.setattr(main, "generate_json", lambda *a, **k: {"title": "T"})
    assert main.analyze_book(p)["title"] == "T"


def test_duplicate_report_empty_no_hits_and_review(monkeypatch):
    assert main._duplicate_report(Store(), "", "facebook")["max_similarity"] is None
    assert main._duplicate_report(Store(), "abc", "facebook")["max_similarity"] is None
    hit = RagHit(1, "post", "s", "e", "", "old", "2026-01-01", "facebook", "topic", 0.90, {})
    monkeypatch.setattr(main, "generate_json", lambda *a, **k: {"redundant": True})
    got = main._duplicate_report(Store([hit]), "new", "facebook")
    assert got["warning"] is True and got["llm_review"]["redundant"] is True


def test_evergreen_generates_preview_and_report(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "ROOT", tmp_path)
    (tmp_path / "data").mkdir()
    (tmp_path / "data/post_history.json").write_text("[]")
    monkeypatch.setattr(main, "rag_store", lambda: Store())
    monkeypatch.setattr(
        main,
        "generate_json",
        lambda *a, **k: {"facebook": "FB", "instagram": "IG", "primary_angle": "reading"},
    )
    result, out = main.evergreen_cmd(SimpleNamespace(date="2026-09-13", image="", dry_run=True), emit=False)
    assert out.parent.name == "dry-run"
    assert Path(result["preview"]).exists() and Path(result["report"]).exists()


def test_load_releases_missing_and_malformed(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "ROOT", tmp_path)
    with pytest.raises(ValueError, match="Missing config/releases.yaml"):
        main._load_releases()
    (tmp_path / "config").mkdir()
    (tmp_path / "config/releases.yaml").write_text("releases: nope\n")
    with pytest.raises(ValueError, match="releases.*list"):
        main._load_releases()


def test_ingest_rows_and_meta_auto_error(tmp_path, monkeypatch, capsys):
    store = Store()
    monkeypatch.setattr(main, "rag_store", lambda: store)
    main._ingest_rows([{"text": ""}, {"text": "Hello", "id": "1"}], "facebook", "src")
    assert len(store.rows) == 1
    assert '"ingested": 1' in capsys.readouterr().out
    p = tmp_path / "unknown.json"
    p.write_text("[]")
    with pytest.raises(ValueError, match="Could not detect"):
        main.rag_import_meta_cmd(SimpleNamespace(file=str(p), platform="auto"))


def test_rag_simple_commands(monkeypatch, capsys):
    store = Store()
    monkeypatch.setattr(main, "rag_store", lambda: store)
    main.rag_stats_cmd(SimpleNamespace())
    assert "total" in capsys.readouterr().out
    main.rag_search_cmd(SimpleNamespace(query="x", top_k=2, kind=None, platform=None))
    assert capsys.readouterr().out.strip() == "[]"
    main.rag_check_cmd(SimpleNamespace(text="x", platform="facebook"))
    assert "max_similarity" in capsys.readouterr().out


def test_approve_rejects_invalid_or_unapproved(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("[]")
    with pytest.raises(ValueError, match="Invalid output JSON"):
        main._approve_file(p, False)
    p.write_text('{"approved":false,"social":{"facebook":"FB"}}')
    with pytest.raises(ValueError, match="not approved"):
        main._approve_file(p, False)


def test_rag_sync_approved(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(main, "ROOT", tmp_path)
    (tmp_path / "output").mkdir()
    p = tmp_path / "output/a.json"
    p.write_text('{"approved":true,"social":{"facebook":"FB"}}')
    monkeypatch.setattr(main, "_approve_file", lambda path, set_approved: {"file": str(path)})
    main.rag_sync_approved_cmd(SimpleNamespace())
    assert '"synced": 1' in capsys.readouterr().out


def test_dashboard_cmd(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(main, "ROOT", tmp_path)
    monkeypatch.setattr(main, "rag_store", lambda: Store())
    monkeypatch.setattr(main, "_load_releases", lambda: [])
    monkeypatch.setattr(main, "build_dashboard", lambda store, releases, out, day: out)
    main.dashboard_cmd(SimpleNamespace(date="2026-09-13"))
    assert "dashboard.html" in capsys.readouterr().out


def test_main_turns_known_error_into_exit(monkeypatch, capsys):
    parser = Mock()
    parsed = SimpleNamespace(log_level=None, func=Mock(side_effect=ValueError("bad")))
    parser.parse_args.return_value = parsed
    monkeypatch.setattr(main, "parser", lambda: parser)
    with pytest.raises(SystemExit) as exc:
        main.main()
    assert exc.value.code == 2
    assert "Error: bad" in capsys.readouterr().out


def test_main_turns_unexpected_error_into_exit(monkeypatch, capsys):
    parser = Mock()
    parsed = SimpleNamespace(log_level=None, func=Mock(side_effect=RuntimeError("boom")))
    parser.parse_args.return_value = parsed
    monkeypatch.setattr(main, "parser", lambda: parser)
    with pytest.raises(SystemExit) as exc:
        main.main()
    assert exc.value.code == 1
    assert "Unexpected error" in capsys.readouterr().out


def test_regenerate_release_field_reuses_profile_and_only_updates_one(tmp_path, monkeypatch):
    p = tmp_path / "release.json"
    p.write_text(
        json.dumps(
            {
                "date": "2026-09-14",
                "release_date": "2026-09-14",
                "published": True,
                "profile": {"title": "Book", "summary_short": "A story"},
                "rag_context": [],
                "social": {"facebook": "old FB", "instagram": "keep IG", "teaser": "keep teaser"},
                "duplicate_check": {},
            }
        )
    )
    monkeypatch.setattr(main, "rag_store", lambda: Store())
    monkeypatch.setattr(main, "generate_json", lambda *a, **k: {"text": "new FB"})
    monkeypatch.setattr(
        main,
        "_duplicate_report",
        lambda store, text, platform: {"max_similarity": 0.1, "warning": False},
    )
    result = main.regenerate_output_field(p, "facebook")
    saved = json.loads(p.read_text())
    assert result["text"] == "new FB"
    assert saved["social"]["facebook"] == "new FB"
    assert saved["social"]["instagram"] == "keep IG"
    assert saved["social"]["teaser"] == "keep teaser"


def test_regenerate_evergreen_field_and_reject_teaser(tmp_path, monkeypatch):
    p = tmp_path / "evergreen.json"
    p.write_text(
        json.dumps(
            {
                "date": "2026-09-15",
                "topic": "reading",
                "category": "education",
                "angle": "questions",
                "facebook": "old FB",
                "instagram": "old IG",
                "duplicate_check": {},
            }
        )
    )
    monkeypatch.setattr(main, "rag_store", lambda: Store())
    monkeypatch.setattr(main, "_rag_context", lambda *a, **k: [])
    monkeypatch.setattr(main, "generate_json", lambda *a, **k: {"text": "new IG"})
    monkeypatch.setattr(
        main,
        "_duplicate_report",
        lambda store, text, platform: {"max_similarity": 0.2, "warning": False},
    )
    result = main.regenerate_output_field(p, "instagram")
    assert result["text"] == "new IG"
    assert json.loads(p.read_text())["facebook"] == "old FB"
    with pytest.raises(ValueError, match="do not have a teaser"):
        main.regenerate_output_field(p, "teaser")


def test_regenerate_rejects_bad_field_and_empty_model_output(tmp_path, monkeypatch):
    p = tmp_path / "release.json"
    p.write_text(json.dumps({"published": True, "profile": {}, "social": {"facebook": "x"}, "duplicate_check": {}}))
    with pytest.raises(ValueError, match="Field must"):
        main.regenerate_output_field(p, "x")
    monkeypatch.setattr(main, "rag_store", lambda: Store())
    monkeypatch.setattr(main, "_rag_context", lambda *a, **k: [])
    monkeypatch.setattr(main, "generate_json", lambda *a, **k: {"text": ""})
    with pytest.raises(ValueError, match="empty draft"):
        main.regenerate_output_field(p, "facebook")


def test_regenerate_accepts_common_model_output_keys(tmp_path, monkeypatch):
    p = tmp_path / "release.json"
    p.write_text(
        json.dumps(
            {
                "date": "2026-09-14",
                "release_date": "2026-09-14",
                "published": True,
                "profile": {"title": "Book", "summary_short": "A story"},
                "rag_context": [],
                "social": {"facebook": "old FB", "instagram": "old IG", "teaser": "old teaser"},
                "duplicate_check": {},
            }
        )
    )
    monkeypatch.setattr(main, "rag_store", lambda: Store())
    monkeypatch.setattr(
        main,
        "_duplicate_report",
        lambda store, text, platform: {"max_similarity": 0.1, "warning": False},
    )

    payloads = [
        {"facebook": "platform-key FB"},
        {"caption": "caption IG"},
        {"content": "content teaser"},
        {"unexpected_key": "sole string FB"},
    ]
    monkeypatch.setattr(main, "generate_json", lambda *a, **k: payloads.pop(0))

    assert main.regenerate_output_field(p, "facebook")["text"] == "platform-key FB"
    assert main.regenerate_output_field(p, "instagram")["text"] == "caption IG"
    assert main.regenerate_output_field(p, "teaser")["text"] == "content teaser"
    assert main.regenerate_output_field(p, "facebook")["text"] == "sole string FB"


def test_regenerate_ignores_empty_preferred_key_if_fallback_has_text(tmp_path, monkeypatch):
    p = tmp_path / "release.json"
    p.write_text(
        json.dumps(
            {
                "published": True,
                "profile": {"title": "Book"},
                "rag_context": [],
                "social": {"facebook": "old FB"},
                "duplicate_check": {},
            }
        )
    )
    monkeypatch.setattr(main, "rag_store", lambda: Store())
    monkeypatch.setattr(main, "generate_json", lambda *a, **k: {"text": "", "facebook": "fallback FB"})
    monkeypatch.setattr(
        main,
        "_duplicate_report",
        lambda store, text, platform: {"max_similarity": 0.1, "warning": False},
    )

    assert main.regenerate_output_field(p, "facebook")["text"] == "fallback FB"


def test_update_output_drafts_release_and_evergreen(tmp_path):
    rp = tmp_path / "release.json"
    rp.write_text(json.dumps({"social": {"facebook": "F", "instagram": "I"}}))
    got = main.update_output_drafts(rp, {"facebook": "manual", "unknown": "ignored"})
    assert got["social"] == {"facebook": "manual", "instagram": "I"}
    ep = tmp_path / "evergreen.json"
    ep.write_text(json.dumps({"facebook": "F", "instagram": "I"}))
    got = main.update_output_drafts(ep, {"instagram": "manual"})
    assert got["facebook"] == "F" and got["instagram"] == "manual"


def test_release_normalizes_nested_social_payload(tmp_path, monkeypatch):
    book = tmp_path / "book.txt"
    book.write_text("A tiny story")
    monkeypatch.setattr(main, "ROOT", tmp_path)
    monkeypatch.setattr(main, "rag_store", lambda: Store())
    monkeypatch.setattr(
        main,
        "analyze_book",
        lambda p: {"title": "Nested Book", "themes": ["kindness"], "summary_short": "A story"},
    )
    monkeypatch.setattr(
        main,
        "generate_json",
        lambda *a, **k: {
            "social": {
                "facebook": {"caption": "Nested FB"},
                "instagram": {"content": "Nested IG #books"},
                "teaser": {"text": "Nested teaser"},
            },
            "primary_angle": "kindness",
        },
    )
    monkeypatch.setattr(
        main,
        "_duplicate_report",
        lambda store, text, platform: {"max_similarity": None, "warning": False, "hits": []},
    )
    args = SimpleNamespace(book=str(book), image="", date="2026-09-14", url="", published=False, dry_run=True)
    result, out = main.release_cmd(args, emit=False)
    assert result["social"]["facebook"] == "Nested FB"
    assert result["social"]["instagram"] == "Nested IG #books"
    assert result["social"]["teaser"] == "Nested teaser"
    assert out.exists()


def test_release_rejects_missing_social_drafts_without_saving(tmp_path, monkeypatch):
    book = tmp_path / "book.txt"
    book.write_text("A tiny story")
    monkeypatch.setattr(main, "ROOT", tmp_path)
    monkeypatch.setattr(main, "rag_store", lambda: Store())
    monkeypatch.setattr(main, "analyze_book", lambda p: {"title": "Broken Book"})
    monkeypatch.setattr(main, "generate_json", lambda *a, **k: {"primary_angle": "kindness"})
    args = SimpleNamespace(book=str(book), image="", date="2026-09-14", url="", published=False, dry_run=False)
    with pytest.raises(ValueError, match="missing usable social draft"):
        main.release_cmd(args, emit=False)
    assert not (tmp_path / "output/release-2026-09-14.json").exists()


def test_evergreen_normalizes_nested_social_payload(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "ROOT", tmp_path)
    monkeypatch.setattr(main, "rag_store", lambda: Store())
    monkeypatch.setattr(main, "_rag_context", lambda *a, **k: [])
    monkeypatch.setattr(
        main,
        "generate_json",
        lambda *a, **k: {
            "topic": "reading",
            "category": "education",
            "angle": "questions",
            "posts": {
                "facebook": {"text": "Evergreen FB"},
                "instagram": {"caption": "Evergreen IG"},
            },
        },
    )
    monkeypatch.setattr(
        main,
        "_duplicate_report",
        lambda store, text, platform: {"max_similarity": None, "warning": False, "hits": []},
    )
    args = SimpleNamespace(date="2026-09-15", dry_run=True, image="")
    result, _ = main.evergreen_cmd(args, emit=False)
    assert result["facebook"] == "Evergreen FB"
    assert result["instagram"] == "Evergreen IG"


def test_regenerate_accepts_nested_platform_payload(tmp_path, monkeypatch):
    p = tmp_path / "release-nested.json"
    p.write_text(
        json.dumps(
            {
                "published": True,
                "profile": {"title": "Book", "summary_short": "A story"},
                "rag_context": [],
                "social": {"facebook": "old", "instagram": "keep", "teaser": "keep"},
                "duplicate_check": {},
            }
        )
    )
    monkeypatch.setattr(main, "rag_store", lambda: Store())
    monkeypatch.setattr(main, "generate_json", lambda *a, **k: {"result": {"facebook": {"post": "Nested regen"}}})
    monkeypatch.setattr(
        main,
        "_duplicate_report",
        lambda store, text, platform: {"max_similarity": None, "warning": False, "hits": []},
    )
    result = main.regenerate_output_field(p, "facebook")
    assert result["text"] == "Nested regen"
