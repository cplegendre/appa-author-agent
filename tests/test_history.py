from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

import author_agent.web as web
from author_agent.io_utils import load_json, save_json


def _setup(monkeypatch, tmp_path: Path):
    out = tmp_path / "output"
    out.mkdir()
    monkeypatch.setattr(web, "OUTPUT_DIR", out)
    monkeypatch.setattr(web, "UPLOAD_DIR", out / "web_uploads")
    web._PREPARED.clear()
    return out


def test_history_lists_modes_status_and_filters(monkeypatch, tmp_path):
    out = _setup(monkeypatch, tmp_path)
    save_json(
        out / "release.json",
        {
            "date": "2026-09-14",
            "published": True,
            "profile": {"title": "Release"},
            "social": {"facebook": "F", "instagram": "I"},
            "approved": False,
            "website": {"status": "prepared"},
        },
    )
    save_json(
        out / "teaser.json",
        {
            "date": "2026-09-13",
            "published": False,
            "profile": {"title": "Teaser"},
            "social": {"facebook": "F", "instagram": "I", "teaser": "T"},
            "approved": True,
            "website": {"status": "skipped"},
        },
    )
    save_json(
        out / "evergreen.json",
        {
            "date": "2026-09-12",
            "facebook": "F",
            "instagram": "I",
            "approved": False,
        },
    )
    save_json(out / "today-2026-09-14.json", {"mode": "release", "output": "whatever"})
    client = TestClient(web.app)
    all_items = client.get("/api/history").json()["items"]
    assert [x["mode"] for x in all_items] == ["release", "teaser", "evergreen"]
    assert all_items[0]["website_push_status"] == "prepared"
    needs = client.get("/api/history?filter=needs_review").json()["items"]
    assert {x["title"] for x in needs} == {"Release", "evergreen"}
    approved = client.get("/api/history?filter=approved").json()["items"]
    assert [x["title"] for x in approved] == ["Teaser"]


def test_history_invalid_filter(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    client = TestClient(web.app)
    response = client.get("/api/history?filter=bogus")
    assert response.status_code == 400


def test_push_persists_history_status(monkeypatch, tmp_path):
    out = _setup(monkeypatch, tmp_path)
    path = out / "release.json"
    save_json(
        path,
        {
            "date": "2026-09-14",
            "release_date": "2026-09-14",
            "published": True,
            "profile": {"title": "Release"},
            "social": {"facebook": "F", "instagram": "I"},
            "website": {"status": "prepared", "branch": "author-agent/release"},
            "approved": False,
        },
    )
    web._PREPARED["release.json"] = {"token": "token", "branch": "author-agent/release"}
    monkeypatch.setitem(web.SETTINGS, "website", {"repo_path": "/tmp/repo"})
    monkeypatch.setattr(
        web,
        "push_website_branch",
        lambda repo, branch: {"status": "pushed", "branch": branch, "push_performed": True},
    )
    client = TestClient(web.app)
    response = client.post("/api/output/release.json/website/push", json={"push_token": "token"})
    assert response.status_code == 200
    data = load_json(path, {})
    assert data["website"]["push_performed"] is True
    assert data["website"]["pushed_at"]
    history = client.get("/api/history").json()["items"]
    assert history[0]["website_push_status"] == "pushed"


def test_index_contains_review_banner_and_history_tab():
    client = TestClient(web.app)
    text = client.get("/").text
    assert "Needs your review" in text
    assert 'data-tab="history"' in text
