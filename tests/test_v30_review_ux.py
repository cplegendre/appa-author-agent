from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from author_agent import daemon, main
from author_agent.dashboard import build_dashboard
from author_agent.persistence import AutomationStore
from author_agent.publishing import PublishingService
from author_agent.workflow import WorkflowService, WorkflowState


class FakePublisher:
    def publish_post(self, request):
        raise AssertionError("rejected workflow must never reach the publisher")

    def schedule_post(self, request):
        raise AssertionError("rejected workflow must never reach the publisher")


class RagStore:
    def recent_posts(self):
        return []


def _service(tmp_path):
    store = AutomationStore(tmp_path / "automation.sqlite3")
    return store, WorkflowService(store)


def test_reject_requires_reason_and_records_terminal_transition(tmp_path):
    _store, service = _service(tmp_path)
    wid = service.create(book="Yok", platform="facebook", state=WorkflowState.REVIEW_REQUIRED)
    with pytest.raises(ValueError, match="reason"):
        service.reject(wid, "")
    row = service.reject(wid, "Needs a different launch angle")
    assert row["state"] == "REJECTED"
    last = service.history(wid)[-1]
    assert last["from_state"] == "REVIEW_REQUIRED"
    assert last["to_state"] == "REJECTED"
    assert last["reason"] == "Needs a different launch angle"
    assert last["at"]
    with pytest.raises(ValueError, match="Invalid workflow transition"):
        service.transition(wid, WorkflowState.DRAFTED, reason="try to reopen")


def test_rejected_workflow_cannot_be_published(tmp_path):
    store, service = _service(tmp_path)
    wid = service.create(state=WorkflowState.REVIEW_REQUIRED)
    service.reject(wid, "Do not publish")
    publisher = PublishingService(store, service, FakePublisher())
    with pytest.raises(ValueError, match="not approved/scheduled"):
        publisher.publish(wid, platform="facebook", text="never publish")


def test_review_edit_is_audited_and_forces_factual_recheck(tmp_path):
    _store, service = _service(tmp_path)
    wid = service.create(
        book="Yok",
        platform="facebook",
        state=WorkflowState.REVIEW_REQUIRED,
        metadata={"drafts": {"facebook_text": "Old copy"}},
    )
    row = service.edit_draft(wid, field="facebook_text", value="New copy", edited_by="cedric")
    assert row["state"] == "DRAFTED"
    edits = service.edits(wid)
    assert edits[-1]["field"] == "facebook_text"
    assert edits[-1]["old_text"] == "Old copy"
    assert edits[-1]["new_text"] == "New copy"
    assert edits[-1]["edited_by"] == "cedric"
    assert edits[-1]["factual_recheck_required"] == 1
    assert "factual recheck required" in service.history(wid)[-1]["reason"]


def test_review_queue_filters_sorts_and_exposes_role(tmp_path):
    store, service = _service(tmp_path)
    old = service.create(
        book="Yok Helps a Friend",
        platform="facebook",
        state=WorkflowState.REVIEW_REQUIRED,
        metadata={"post_role": "launch"},
    )
    fresh = service.create(
        book="Another Book",
        platform="instagram",
        state=WorkflowState.IN_REVIEW,
        metadata={"kind": "inside_the_book"},
    )
    old_at = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
    with store.connect() as con:
        con.execute(
            "UPDATE workflow_transitions SET at=? WHERE workflow_id=? AND to_state='REVIEW_REQUIRED'", (old_at, old)
        )
    rows = service.review_queue(sort_by="age")
    assert [row["id"] for row in rows][:2] == [old, fresh]
    assert rows[0]["post_role"] == "launch"
    assert rows[1]["post_role"] == "reminder"
    assert service.review_queue(book="Yok") == [rows[0]]
    assert service.review_queue(platform="instagram")[0]["id"] == fresh
    assert service.review_queue(min_age_days=3)[0]["id"] == old


def test_dashboard_includes_human_review_queue(tmp_path):
    out = build_dashboard(
        RagStore(),
        [],
        tmp_path / "dashboard.html",
        datetime.now().date(),
        review_queue=[{"id": "w1", "book": "Yok", "platform": "facebook", "post_role": "teaser", "age_days": 4}],
    )
    text = out.read_text()
    assert "Human review queue" in text
    assert "teaser" in text
    assert "w1" in text


def test_generation_exposes_explicit_post_roles(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "ROOT", tmp_path)
    book = tmp_path / "book.txt"
    book.write_text("A tiny story")
    fake = type("Store", (), {"search": lambda *a, **k: [], "upsert": lambda *a, **k: 1, "stats": lambda *a: {}})()
    monkeypatch.setattr(main, "rag_store", lambda: fake)
    monkeypatch.setattr(
        main, "analyze_book", lambda p: {"title": "Tiny Book", "themes": ["kindness"], "plot_summary": "x"}
    )
    monkeypatch.setattr(
        main,
        "generate_json",
        lambda *a, **k: {"facebook": "FB", "instagram": "IG #tag", "teaser": "T", "primary_angle": "kindness"},
    )
    monkeypatch.setattr(main, "prepare_website_update", lambda *a, **k: {"status": "dry-run"})
    args = SimpleNamespace(book=str(book), image="", date="2026-09-15", url="https://x", published=True, dry_run=True)
    result, _ = main.release_cmd(args, emit=False)
    assert result["post_roles"] == {"facebook": "launch", "instagram": "launch", "teaser": "teaser"}


def test_stale_review_uses_existing_alert_channel(tmp_path, monkeypatch):
    db = tmp_path / "data" / "automation.sqlite3"
    store = AutomationStore(db)
    service = WorkflowService(store)
    wid = service.create(book="Yok", platform="instagram", state=WorkflowState.REVIEW_REQUIRED)
    old_at = (datetime.now(timezone.utc) - timedelta(days=6)).isoformat()
    with store.connect() as con:
        con.execute(
            "UPDATE workflow_transitions SET at=? WHERE workflow_id=? AND to_state='REVIEW_REQUIRED'", (old_at, wid)
        )

    monkeypatch.setattr(daemon, "ROOT", tmp_path)
    settings = dict(daemon.SETTINGS)
    settings["automation"] = {"db_path": "data/automation.sqlite3"}
    settings["notifications"] = {
        "stale_review_days": 3,
        "alert_webhook_env": "AUTHOR_AGENT_ALERT_WEBHOOK",
        "alert_timeout_seconds": 5,
    }
    monkeypatch.setattr(daemon, "SETTINGS", settings)
    monkeypatch.setenv("AUTHOR_AGENT_ALERT_WEBHOOK", "https://hooks.example.test/stale")
    captured = []

    class Response:
        def raise_for_status(self):
            return None

    def fake_post(url, *, json, timeout):
        captured.append((url, json, timeout))
        return Response()

    monkeypatch.setattr("author_agent.alerting.httpx.post", fake_post)
    stale = daemon.alert_stale_reviews()
    assert stale[0]["id"] == wid
    assert captured
    assert "stale review" in captured[0][1]["text"].lower()
    assert f"workflow={wid}" in captured[0][1]["text"]


def test_workflow_cli_operations_reject_edit_and_queue(tmp_path):
    from author_agent.cli import operations

    store = AutomationStore(tmp_path / "cli.sqlite3")
    service = WorkflowService(store)
    outputs = []

    def factory():
        return store

    edit_id = service.create(
        book="Yok",
        platform="facebook",
        state=WorkflowState.REVIEW_REQUIRED,
        metadata={"drafts": {"facebook_text": "old"}, "post_role": "launch"},
    )
    operations.workflow_edit(
        SimpleNamespace(id=edit_id, field="facebook_text", value="new", actor="editor"),
        store_factory=factory,
        output=outputs.append,
    )
    assert '"edited_by": "editor"' in outputs[-1]

    reject_id = service.create(book="Yok", platform="instagram", state=WorkflowState.REVIEW_REQUIRED)
    operations.workflow_reject(
        SimpleNamespace(id=reject_id, reason="not suitable"), store_factory=factory, output=outputs.append
    )
    assert '"state": "REJECTED"' in outputs[-1]

    queue_id = service.create(
        book="Yok Queue",
        platform="facebook",
        state=WorkflowState.REVIEW_REQUIRED,
        metadata={"post_role": "teaser"},
    )
    operations.workflow_queue(
        SimpleNamespace(book="Yok", platform="", min_age_days=None, max_age_days=None, sort="age"),
        store_factory=factory,
        output=outputs.append,
    )
    assert outputs[-2].startswith("ID\tBOOK") or any(line.startswith("ID\tBOOK") for line in outputs)
    assert any(queue_id in line and "teaser" in line for line in outputs)


def test_queue_validation_and_edit_guard(tmp_path):
    _store, service = _service(tmp_path)
    wid = service.create(state=WorkflowState.INGESTED)
    with pytest.raises(ValueError, match="only be edited"):
        service.edit_draft(wid, field="facebook_text", value="x", edited_by="u")
    service.create(state=WorkflowState.REVIEW_REQUIRED)
    with pytest.raises(ValueError, match="sort"):
        service.review_queue(sort_by="unknown")
    with pytest.raises(ValueError, match="at least 1 day"):
        service.stale_reviews(0)
    with pytest.raises(ValueError, match="cannot be rejected"):
        service.reject(service.create(state=WorkflowState.PUBLISHED), "too late")
