from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

import author_agent.rag_commands as commands
from author_agent.errors import ValidationError
from author_agent.io_utils import save_json


class FakeStore:
    def __init__(self):
        self.upserts = []

    def upsert(self, **kwargs):
        self.upserts.append(kwargs)
        return len(self.upserts)

    def stats(self):
        return {"documents": len(self.upserts)}

    def search(self, *args, **kwargs):
        return []


def deps(tmp_path, store=None):
    store = store or FakeStore()
    output = []
    return (
        commands.RagCommandDeps(
            root=tmp_path,
            rag_store=lambda: store,
            analyze_book=lambda path: {"title": "Book title", "themes": ["kindness", "waiting"]},
            duplicate_report=lambda store, text, platform: {"text": text, "platform": platform, "score": 0.4},
            user_output=output.append,
        ),
        store,
        output,
    )


def test_ingest_posts_cmd_uses_file_defaults(monkeypatch, tmp_path):
    path = tmp_path / "posts.json"
    path.write_text("[]", encoding="utf-8")
    d, store, output = deps(tmp_path)
    monkeypatch.setattr(commands, "load_posts_file", lambda _: [{"text": "hello", "platform": "instagram"}])
    commands.ingest_posts_cmd(SimpleNamespace(file=str(path), platform="", source=""), d)
    assert store.upserts[0]["source"] == "posts.json"
    assert output


def test_import_meta_explicit_instagram(monkeypatch, tmp_path):
    path = tmp_path / "anything.json"
    path.write_text("{}", encoding="utf-8")
    d, store, _ = deps(tmp_path)
    monkeypatch.setattr(commands, "parse_meta_instagram", lambda _: [{"text": "IG post"}])
    commands.import_meta_cmd(SimpleNamespace(file=str(path), platform="instagram"), d)
    assert store.upserts[0]["platform"] == "instagram"


def test_import_meta_auto_unknown_rejected(tmp_path):
    path = tmp_path / "export.json"
    path.write_text("{}", encoding="utf-8")
    d, _, _ = deps(tmp_path)
    with pytest.raises(ValidationError, match="Could not detect"):
        commands.import_meta_cmd(SimpleNamespace(file=str(path), platform="auto"), d)


def test_ingest_book_analyzed_and_no_analyze(monkeypatch, tmp_path):
    book = tmp_path / "book.txt"
    book.write_text("book content", encoding="utf-8")
    d, store, output = deps(tmp_path)
    commands.ingest_book_cmd(
        SimpleNamespace(book=str(book), date="2026-09-14", no_analyze=False, source="", id=""),
        d,
    )
    assert store.upserts[0]["title"] == "Book title"
    assert store.upserts[0]["topic"] == "kindness; waiting"
    assert output

    d2, store2, _ = deps(tmp_path)
    commands.ingest_book_cmd(
        SimpleNamespace(book=str(book), date="", no_analyze=True, source="custom", id="book-id"),
        d2,
    )
    assert store2.upserts[0]["title"] == "book"
    assert store2.upserts[0]["external_id"] == "book-id"


def test_mark_approved_cmd_and_sync(monkeypatch, tmp_path):
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    pending = output_dir / "release.json"
    save_json(pending, {"date": "2026-09-14", "social": {"facebook": "FB", "instagram": "IG"}})
    d, store, output = deps(tmp_path)
    commands.mark_approved_cmd(SimpleNamespace(file=str(pending)), d)
    assert len(store.upserts) == 2
    assert json.loads(output[-1])["registered"] == ["facebook", "instagram"]

    another = output_dir / "approved.json"
    save_json(
        another,
        {"approved": True, "date": "2026-09-15", "facebook": "legacy FB", "instagram": "legacy IG"},
    )
    already = output_dir / "done.json"
    save_json(already, {"approved": True, "rag_registered": True, "facebook": "done"})
    commands.sync_approved_cmd(SimpleNamespace(), d)
    payload = json.loads(output[-1])
    assert payload["synced"] == 1


def test_approve_file_rejects_invalid_dry_run_and_unapproved(tmp_path):
    d, _, _ = deps(tmp_path)
    invalid = tmp_path / "invalid.json"
    invalid.write_text("[]", encoding="utf-8")
    with pytest.raises(ValidationError, match="Invalid output JSON"):
        commands.approve_file(invalid, False, d)

    dry = tmp_path / "dry.json"
    save_json(dry, {"dry_run": True})
    with pytest.raises(ValidationError, match="Dry-run outputs"):
        commands.approve_file(dry, False, d)

    pending = tmp_path / "pending.json"
    save_json(pending, {"approved": False})
    with pytest.raises(ValidationError, match="not approved"):
        commands.approve_file(pending, False, d)
