from __future__ import annotations

import json
from pathlib import Path

import pytest

from author_agent.errors import WebsiteError
from author_agent.website_calendar import (
    calendar_format,
    detect_calendar_file,
    patch_calendar,
    patch_calendar_text,
    upsert_release,
    validate_release_list,
)


RELEASE = {"date": "2026-09-14", "title": "Bilingual Yok 4", "status": "published"}


def test_detect_calendar_file_fallback_scan_and_none(tmp_path):
    calendar = tmp_path / "calendar"
    calendar.mkdir()
    fallback = calendar / "custom.htm"
    fallback.write_text("<html></html>", encoding="utf-8")
    assert detect_calendar_file(tmp_path) == fallback
    fallback.unlink()
    assert detect_calendar_file(tmp_path) is None


def test_validate_release_list_rejects_non_list():
    with pytest.raises(WebsiteError, match="must be a list"):
        validate_release_list({"date": "x"}, Path("calendar.json"))


def test_upsert_updates_existing_entry_and_is_idempotent():
    rows = [{"date": "2026-09-14", "title": "Bilingual Yok 4", "status": "planned"}]
    assert upsert_release(rows, RELEASE) is True
    assert rows[0]["status"] == "published"
    assert upsert_release(rows, RELEASE) is False


def test_event_class_luma_and_yok_via_html_append():
    base = '<article class="release-month"><h2>September 2026</h2><div class="release-events"></div></article>'
    luma = patch_calendar_text(Path("calendar/index.html"), {"date": "2026-09-16", "title": "Luma 4"}, base)
    yok = patch_calendar_text(Path("calendar/index.html"), {"date": "2026-09-17", "title": "Yok 11"}, base)
    assert "release-event luma" in luma
    assert "release-event yok" in yok


def test_html_invalid_date_is_clear():
    with pytest.raises(WebsiteError, match="Invalid release date"):
        patch_calendar_text(Path("calendar/index.html"), {"date": "2026-99-14", "title": "X"}, "<html></html>")


def test_yaml_malformed_and_scalar_and_list_shapes():
    path = Path("releases.yaml")
    with pytest.raises(WebsiteError, match="Malformed YAML"):
        patch_calendar_text(path, RELEASE, "releases: [")
    with pytest.raises(WebsiteError, match="expected a list or object"):
        patch_calendar_text(path, RELEASE, "hello")
    patched = patch_calendar_text(path, RELEASE, "[]\n")
    assert "Bilingual Yok 4" in patched
    assert patch_calendar_text(path, RELEASE, patched) == patched


def test_json_list_shape_and_scalar_error():
    path = Path("releases.json")
    patched = patch_calendar_text(path, RELEASE, "[]")
    assert json.loads(patched)[0]["title"] == "Bilingual Yok 4"
    with pytest.raises(WebsiteError, match="expected a list or object"):
        patch_calendar_text(path, RELEASE, '"hello"')


def test_js_malformed_json_and_idempotent():
    path = Path("calendar/data.js")
    with pytest.raises(WebsiteError, match="Malformed JavaScript calendar array"):
        patch_calendar_text(path, RELEASE, "const releases = [{bad}];")
    original = 'const releases = [{"date":"2026-09-14","title":"Bilingual Yok 4","status":"published"}];'
    assert patch_calendar_text(path, RELEASE, original) == original


def test_unsupported_suffix_and_patch_write(tmp_path):
    bad = Path("calendar.txt")
    with pytest.raises(WebsiteError, match="Unsupported calendar file format"):
        patch_calendar_text(bad, RELEASE, "")

    path = tmp_path / "releases.json"
    path.write_text("[]", encoding="utf-8")
    patched = patch_calendar(path, RELEASE, write=True)
    assert path.read_text(encoding="utf-8") == patched


def test_calendar_format_unknown():
    assert calendar_format(Path("calendar.csv")) == "CSV"
    assert calendar_format(Path("calendar")) == "UNKNOWN"
