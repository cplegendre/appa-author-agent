from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

import author_agent.web as web
from author_agent.io_utils import save_json


def _release_data():
    return {
        "date": "2026-09-14",
        "release_date": "2026-09-14",
        "published": True,
        "book": "/tmp/book.txt",
        "image": "",
        "url": "https://example.test/book",
        "profile": {"title": "Book Four"},
        "social": {"facebook": "FB", "instagram": "IG", "teaser": "Tomorrow"},
        "duplicate_check": {
            "facebook": {"max_similarity": 0.2, "warning": False},
            "instagram": {"max_similarity": 0.3, "warning": False},
            "teaser": {"max_similarity": None, "warning": False},
        },
        "website": {"status": "dry-run", "diff": "diff", "format": "HTML", "file": "calendar/index.html"},
        "approved": False,
    }


def _configure_tmp(monkeypatch, tmp_path: Path):
    output = tmp_path / "output"
    uploads = output / "web_uploads"
    output.mkdir()
    monkeypatch.setattr(web, "OUTPUT_DIR", output)
    monkeypatch.setattr(web, "UPLOAD_DIR", uploads)
    web._PREPARED.clear()
    return output


def test_index_is_local_spa():
    client = TestClient(web.app)
    response = client.get("/")
    assert response.status_code == 200
    assert "Author Agent" in response.text
    assert "127.0.0.1 only" in response.text


def test_release_route_calls_existing_release_cmd(monkeypatch, tmp_path):
    output = _configure_tmp(monkeypatch, tmp_path)
    seen = {}

    def fake_release(args, *, emit=False):
        seen["args"] = args
        path = output / "release-2026-09-14.json"
        save_json(path, _release_data())
        return _release_data(), path

    monkeypatch.setattr(web, "release_cmd", fake_release)
    client = TestClient(web.app)
    response = client.post(
        "/api/release",
        data={"release_date": "2026-09-14", "book_url": "https://example.test/book", "published": "true"},
        files={"book": ("book.txt", b"hello book", "text/plain")},
    )
    assert response.status_code == 200
    assert response.json()["data"]["social"]["facebook"] == "FB"
    assert seen["args"].website_dry_run is True
    assert seen["args"].published is True


def test_evergreen_route_calls_existing_command(monkeypatch, tmp_path):
    output = _configure_tmp(monkeypatch, tmp_path)

    def fake_evergreen(args, *, emit=False):
        path = output / "evergreen-2026-09-15.json"
        data = {"date": "2026-09-15", "facebook": "FB e", "instagram": "IG e", "duplicate_check": {}}
        save_json(path, data)
        return data, path

    monkeypatch.setattr(web, "evergreen_cmd", fake_evergreen)
    client = TestClient(web.app)
    response = client.post("/api/evergreen", data={"post_date": "2026-09-15"})
    assert response.status_code == 200
    assert response.json()["data"]["facebook"] == "FB e"


def test_regenerate_route_delegates(monkeypatch, tmp_path):
    output = _configure_tmp(monkeypatch, tmp_path)
    path = output / "release.json"
    save_json(path, _release_data())
    monkeypatch.setattr(
        web,
        "regenerate_output_field",
        lambda p, f: {"field": f, "text": "new FB", "duplicate_check": {"max_similarity": 0.1, "warning": False}},
    )
    client = TestClient(web.app)
    response = client.post("/api/output/release.json/regenerate/facebook")
    assert response.status_code == 200
    assert response.json()["text"] == "new FB"


def test_save_drafts_preserves_other_fields(monkeypatch, tmp_path):
    output = _configure_tmp(monkeypatch, tmp_path)
    path = output / "release.json"
    save_json(path, _release_data())
    client = TestClient(web.app)
    response = client.patch("/api/output/release.json/drafts", json={"drafts": {"facebook": "manual"}})
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["social"]["facebook"] == "manual"
    assert data["social"]["instagram"] == "IG"


def test_preview_route_uses_current_output(monkeypatch, tmp_path):
    output = _configure_tmp(monkeypatch, tmp_path)
    path = output / "release.json"
    data = _release_data()
    data["social"]["facebook"] = "Edited in UI"
    save_json(path, data)
    client = TestClient(web.app)
    response = client.get("/api/output/release.json/preview")
    assert response.status_code == 200
    assert "Edited in UI" in response.text
    assert "Nothing has been published" in response.text


def test_push_is_gated_by_prepare_in_same_server_session(monkeypatch, tmp_path):
    output = _configure_tmp(monkeypatch, tmp_path)
    path = output / "release.json"
    save_json(path, _release_data())
    client = TestClient(web.app)

    blocked = client.post("/api/output/release.json/website/push", json={"push_token": "nope"})
    assert blocked.status_code == 400
    assert "Prepare" in blocked.json()["detail"]

    monkeypatch.setattr(
        web,
        "prepare_website_update",
        lambda *a, **k: {
            "status": "prepared",
            "branch": "author-agent/2026-09-14-book-four",
            "file": "calendar/index.html",
            "format": "HTML",
            "diff": "+ published",
        },
    )
    monkeypatch.setattr(
        web,
        "push_website_branch",
        lambda repo, branch: {"status": "pushed", "branch": branch, "push_performed": True},
    )
    prepared = client.post("/api/output/release.json/website/prepare")
    assert prepared.status_code == 200
    token = prepared.json()["push_token"]

    pushed = client.post("/api/output/release.json/website/push", json={"push_token": token})
    assert pushed.status_code == 200
    assert pushed.json()["push_performed"] is True
    again = client.post("/api/output/release.json/website/push", json={"push_token": token})
    assert again.status_code == 400


def test_approve_delegates_to_existing_rag_approval(monkeypatch, tmp_path):
    output = _configure_tmp(monkeypatch, tmp_path)
    path = output / "release.json"
    save_json(path, _release_data())
    monkeypatch.setattr(web, "approve_output_file", lambda p: {"file": str(p), "registered": ["facebook", "instagram"]})
    client = TestClient(web.app)
    response = client.post("/api/output/release.json/approve")
    assert response.status_code == 200
    assert response.json()["registered"] == ["facebook", "instagram"]


def test_today_route_reuses_today_cmd(monkeypatch, tmp_path):
    output = _configure_tmp(monkeypatch, tmp_path)
    path = output / "evergreen-2026-09-15.json"
    save_json(path, {"date": "2026-09-15", "facebook": "F", "instagram": "I", "duplicate_check": {}})
    seen = {}

    def fake_today(args):
        seen["args"] = args
        return {"date": "2026-09-15", "mode": "evergreen", "output": str(path)}

    monkeypatch.setattr(web, "today_cmd", fake_today)
    client = TestClient(web.app)
    response = client.post("/api/today", json={"date": "2026-09-15", "window": 2, "force": True})
    assert response.status_code == 200
    assert response.json()["manifest"]["mode"] == "evergreen"
    assert seen["args"].website_dry_run is True
