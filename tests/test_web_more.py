from __future__ import annotations

import asyncio

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import author_agent.main as main
import author_agent.web as web
from author_agent.io_utils import save_json
from author_agent.ollama_client import OllamaError
from author_agent.website import WebsiteError


def _release_data(**overrides):
    data = {
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
    data.update(overrides)
    return data


def _configure_tmp(monkeypatch, tmp_path: Path):
    output = tmp_path / "output"
    uploads = output / "web_uploads"
    output.mkdir()
    monkeypatch.setattr(web, "OUTPUT_DIR", output)
    monkeypatch.setattr(web, "UPLOAD_DIR", uploads)
    web._PREPARED.clear()
    return output


# ---------------------------------------------------------------------------
# _safe_output guard rails (path traversal / bad names / missing files)
# ---------------------------------------------------------------------------


def test_safe_output_rejects_non_json_suffix(monkeypatch, tmp_path):
    _configure_tmp(monkeypatch, tmp_path)
    client = TestClient(web.app)
    response = client.get("/api/output/notes.txt")
    assert response.status_code == 404


def test_safe_output_rejects_path_traversal(monkeypatch, tmp_path):
    _configure_tmp(monkeypatch, tmp_path)
    client = TestClient(web.app)
    response = client.get("/api/output/..%2Fsecrets.json")
    assert response.status_code in (404, 400)


def test_safe_output_rejects_missing_file(monkeypatch, tmp_path):
    _configure_tmp(monkeypatch, tmp_path)
    client = TestClient(web.app)
    response = client.get("/api/output/does-not-exist.json")
    assert response.status_code == 404
    assert "not found" in response.json()["detail"]


def test_save_upload_raises_when_required_and_missing(monkeypatch, tmp_path):
    _configure_tmp(monkeypatch, tmp_path)
    with pytest.raises(ValueError, match="manuscript file is required"):
        asyncio.run(web._save_upload(None, required=True))


def test_health_endpoint(monkeypatch, tmp_path):
    _configure_tmp(monkeypatch, tmp_path)
    client = TestClient(web.app)
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["local_only"] is True
    assert body["config_loaded"] is True
    assert body["rag_db_reachable"] is True
    assert client.get("/health").status_code == 200


# ---------------------------------------------------------------------------
# Global exception handlers
# ---------------------------------------------------------------------------


def test_ollama_error_from_release_surfaces_as_503(monkeypatch, tmp_path):
    _configure_tmp(monkeypatch, tmp_path)

    def boom(args, *, emit=False):
        raise OllamaError("Ollama is not reachable at http://localhost:11434.")

    monkeypatch.setattr(web, "release_cmd", boom)
    client = TestClient(web.app)
    response = client.post(
        "/api/release",
        data={"release_date": "2026-09-14", "published": "true"},
        files={"book": ("book.txt", b"hello book", "text/plain")},
    )
    assert response.status_code == 503
    assert "not reachable" in response.json()["detail"]


def test_regenerate_route_accepts_platform_key_payload(monkeypatch, tmp_path):
    output = _configure_tmp(monkeypatch, tmp_path)
    path = output / "release.json"
    save_json(path, _release_data())

    class Store:
        def search(self, *args, **kwargs):
            return []

    monkeypatch.setattr(main, "rag_store", lambda: Store())
    monkeypatch.setattr(main, "generate_json", lambda *a, **k: {"facebook": "Regenerated FB"})
    monkeypatch.setattr(
        main,
        "_duplicate_report",
        lambda store, text, platform: {"max_similarity": None, "warning": False, "hits": [], "llm_review": None},
    )

    client = TestClient(web.app)
    response = client.post("/api/output/release.json/regenerate/facebook")

    assert response.status_code == 200
    assert response.json()["text"] == "Regenerated FB"
    saved = __import__("json").loads(path.read_text())
    assert saved["social"]["facebook"] == "Regenerated FB"


def test_website_error_from_regenerate_surfaces_as_400(monkeypatch, tmp_path):
    output = _configure_tmp(monkeypatch, tmp_path)
    path = output / "release.json"
    save_json(path, _release_data())

    def boom(p, f):
        raise WebsiteError("calendar file is malformed")

    monkeypatch.setattr(web, "regenerate_output_field", boom)
    client = TestClient(web.app)
    response = client.post("/api/output/release.json/regenerate/facebook")
    # WebsiteError isn't in the caught tuple for regenerate, so it propagates to the
    # global exception_handler registered for WebsiteError (400).
    assert response.status_code == 400


def test_release_route_rejects_missing_manuscript(monkeypatch, tmp_path):
    _configure_tmp(monkeypatch, tmp_path)
    client = TestClient(web.app)
    # An empty filename/content-type pair is rejected by FastAPI's multipart parsing
    # itself (422) before our handler's `required=True` check ever runs; that inner
    # check is exercised directly instead, since the route requires `book` regardless.
    response = client.post(
        "/api/release",
        data={"release_date": "2026-09-14"},
        files={"book": ("", b"", "text/plain")},
    )
    assert response.status_code in (400, 422)


def test_evergreen_route_wraps_value_error(monkeypatch, tmp_path):
    _configure_tmp(monkeypatch, tmp_path)

    def boom(args, *, emit=False):
        raise ValueError("bad date")

    monkeypatch.setattr(web, "evergreen_cmd", boom)
    client = TestClient(web.app)
    response = client.post("/api/evergreen", data={"post_date": "not-a-date"})
    assert response.status_code == 400
    assert "bad date" in response.json()["detail"]


# ---------------------------------------------------------------------------
# /api/today edge cases
# ---------------------------------------------------------------------------


def test_today_route_reports_missing_output_file(monkeypatch, tmp_path):
    _configure_tmp(monkeypatch, tmp_path)

    def fake_today(args):
        return {"date": "2026-09-15", "mode": "evergreen", "output": "/nowhere/evergreen.json"}

    monkeypatch.setattr(web, "today_cmd", fake_today)
    client = TestClient(web.app)
    response = client.post("/api/today", json={})
    assert response.status_code == 400
    assert "was not found" in response.json()["detail"]


def test_today_route_defaults_when_payload_empty(monkeypatch, tmp_path):
    output = _configure_tmp(monkeypatch, tmp_path)
    path = output / "evergreen-2026-09-15.json"
    save_json(path, {"date": "2026-09-15", "facebook": "F", "instagram": "I", "duplicate_check": {}})
    seen = {}

    def fake_today(args):
        seen["args"] = args
        return {"date": "2026-09-15", "mode": "evergreen", "output": str(path)}

    monkeypatch.setattr(web, "today_cmd", fake_today)
    client = TestClient(web.app)
    response = client.post("/api/today", json={})
    assert response.status_code == 200
    assert seen["args"].force is False
    assert seen["args"].date == ""


# ---------------------------------------------------------------------------
# drafts validation
# ---------------------------------------------------------------------------


def test_save_drafts_rejects_non_object_payload(monkeypatch, tmp_path):
    output = _configure_tmp(monkeypatch, tmp_path)
    path = output / "release.json"
    save_json(path, _release_data())
    client = TestClient(web.app)
    response = client.patch("/api/output/release.json/drafts", json={"drafts": "not-an-object"})
    assert response.status_code == 400


# ---------------------------------------------------------------------------
# duplicate-check route
# ---------------------------------------------------------------------------


def test_duplicate_check_rejects_unknown_field(monkeypatch, tmp_path):
    output = _configure_tmp(monkeypatch, tmp_path)
    path = output / "release.json"
    save_json(path, _release_data())
    client = TestClient(web.app)
    response = client.post("/api/output/release.json/check/bogus", json={"text": "hi"})
    assert response.status_code == 400
    assert "facebook, instagram, or teaser" in response.json()["detail"]


def test_duplicate_check_persists_text_and_report(monkeypatch, tmp_path):
    output = _configure_tmp(monkeypatch, tmp_path)
    path = output / "release.json"
    save_json(path, _release_data())
    monkeypatch.setattr(web, "rag_store", lambda: object())
    monkeypatch.setattr(
        web,
        "_duplicate_report",
        lambda store, text, platform: {"max_similarity": 0.9, "warning": True, "checked_platform": platform},
    )
    client = TestClient(web.app)
    response = client.post("/api/output/release.json/check/teaser", json={"text": "new teaser copy"})
    assert response.status_code == 200
    body = response.json()
    assert body["warning"] is True
    assert body["checked_platform"] == "instagram"  # teaser checks against the instagram corpus
    saved = __import__("json").loads(path.read_text())
    assert saved["social"]["teaser"] == "new teaser copy"
    assert saved["duplicate_check"]["teaser"]["warning"] is True


def test_duplicate_check_wraps_ollama_error(monkeypatch, tmp_path):
    output = _configure_tmp(monkeypatch, tmp_path)
    path = output / "release.json"
    save_json(path, _release_data())
    monkeypatch.setattr(web, "rag_store", lambda: object())

    def boom(store, text, platform):
        raise OllamaError("down")

    monkeypatch.setattr(web, "_duplicate_report", boom)
    client = TestClient(web.app)
    response = client.post("/api/output/release.json/check/facebook", json={"text": "x"})
    assert response.status_code == 503


# ---------------------------------------------------------------------------
# preview + image routes
# ---------------------------------------------------------------------------


def test_preview_route_missing_output_is_404(monkeypatch, tmp_path):
    _configure_tmp(monkeypatch, tmp_path)
    client = TestClient(web.app)
    response = client.get("/api/output/missing.json/preview")
    assert response.status_code == 404


def test_output_image_missing_file_is_404(monkeypatch, tmp_path):
    output = _configure_tmp(monkeypatch, tmp_path)
    path = output / "release.json"
    save_json(path, _release_data(image="/does/not/exist.png"))
    client = TestClient(web.app)
    response = client.get("/api/output/release.json/image")
    assert response.status_code == 404
    assert "not available" in response.json()["detail"]


def test_output_image_rejects_unsupported_format(monkeypatch, tmp_path):
    output = _configure_tmp(monkeypatch, tmp_path)
    bad_image = output / "cover.svg"
    bad_image.write_text("<svg></svg>", encoding="utf-8")
    path = output / "release.json"
    save_json(path, _release_data(image=str(bad_image)))
    client = TestClient(web.app)
    response = client.get("/api/output/release.json/image")
    assert response.status_code == 404
    assert "Unsupported" in response.json()["detail"]


def test_output_image_serves_valid_file(monkeypatch, tmp_path):
    output = _configure_tmp(monkeypatch, tmp_path)
    good_image = output / "cover.png"
    good_image.write_bytes(b"\x89PNG\r\n\x1a\n")
    path = output / "release.json"
    save_json(path, _release_data(image=str(good_image)))
    client = TestClient(web.app)
    response = client.get("/api/output/release.json/image")
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# website prepare guard rails
# ---------------------------------------------------------------------------


def test_website_prepare_rejects_non_release_output(monkeypatch, tmp_path):
    output = _configure_tmp(monkeypatch, tmp_path)
    path = output / "evergreen.json"
    save_json(path, {"date": "2026-09-15", "facebook": "F", "instagram": "I"})
    client = TestClient(web.app)
    response = client.post("/api/output/evergreen.json/website/prepare")
    assert response.status_code == 400
    assert "release outputs" in response.json()["detail"]


def test_website_prepare_rejects_unpublished_teaser(monkeypatch, tmp_path):
    output = _configure_tmp(monkeypatch, tmp_path)
    path = output / "release.json"
    save_json(path, _release_data(published=False))
    client = TestClient(web.app)
    response = client.post("/api/output/release.json/website/prepare")
    assert response.status_code == 400
    assert "published release" in response.json()["detail"]


def test_website_prepare_surfaces_failure_reason(monkeypatch, tmp_path):
    output = _configure_tmp(monkeypatch, tmp_path)
    path = output / "release.json"
    save_json(path, _release_data())
    monkeypatch.setattr(
        web,
        "prepare_website_update",
        lambda *a, **k: {"status": "error", "reason": "calendar file not found in repo"},
    )
    client = TestClient(web.app)
    response = client.post("/api/output/release.json/website/prepare")
    assert response.status_code == 400
    assert "calendar file not found" in response.json()["detail"]
    # No push token should have been issued for a failed prepare.
    assert "release.json" not in web._PREPARED


def test_website_prepare_accepts_unchanged_status(monkeypatch, tmp_path):
    output = _configure_tmp(monkeypatch, tmp_path)
    path = output / "release.json"
    save_json(path, _release_data())
    monkeypatch.setattr(
        web,
        "prepare_website_update",
        lambda *a, **k: {"status": "unchanged", "branch": "author-agent/x", "diff": ""},
    )
    client = TestClient(web.app)
    response = client.post("/api/output/release.json/website/prepare")
    assert response.status_code == 200
    assert "push_token" in response.json()


def test_website_push_rejects_wrong_token(monkeypatch, tmp_path):
    output = _configure_tmp(monkeypatch, tmp_path)
    path = output / "release.json"
    save_json(path, _release_data())
    monkeypatch.setattr(
        web,
        "prepare_website_update",
        lambda *a, **k: {"status": "prepared", "branch": "author-agent/x", "diff": "+x"},
    )
    client = TestClient(web.app)
    prepared = client.post("/api/output/release.json/website/prepare")
    assert prepared.status_code == 200

    wrong = client.post("/api/output/release.json/website/push", json={"push_token": "totally-wrong"})
    assert wrong.status_code == 400
    assert "Invalid or expired" in wrong.json()["detail"]


def test_website_push_wraps_website_error(monkeypatch, tmp_path):
    output = _configure_tmp(monkeypatch, tmp_path)
    path = output / "release.json"
    save_json(path, _release_data())
    monkeypatch.setattr(
        web,
        "prepare_website_update",
        lambda *a, **k: {"status": "prepared", "branch": "author-agent/x", "diff": "+x"},
    )
    client = TestClient(web.app)
    prepared = client.post("/api/output/release.json/website/prepare")
    token = prepared.json()["push_token"]

    def boom(repo, branch):
        raise WebsiteError("remote rejected the push")

    monkeypatch.setattr(web, "push_website_branch", boom)
    response = client.post("/api/output/release.json/website/push", json={"push_token": token})
    assert response.status_code == 400
    assert "remote rejected" in response.json()["detail"]


# ---------------------------------------------------------------------------
# approve route error path
# ---------------------------------------------------------------------------


def test_approve_wraps_ollama_error(monkeypatch, tmp_path):
    output = _configure_tmp(monkeypatch, tmp_path)
    path = output / "release.json"
    save_json(path, _release_data())

    def boom(p):
        raise OllamaError("embedding service unavailable")

    monkeypatch.setattr(web, "approve_output_file", boom)
    client = TestClient(web.app)
    response = client.post("/api/output/release.json/approve")
    assert response.status_code == 503
