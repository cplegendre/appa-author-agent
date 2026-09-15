import json
import subprocess
from pathlib import Path

import pytest

from author_agent.website import (
    WebsiteError,
    _detect_calendar_file,
    _patch_structured,
    _patch_structured_text,
    prepare_website_update,
)

RELEASE = {"date": "2026-09-14", "title": "Bilingual Yok 4", "status": "published", "url": "https://example"}


def _repo(tmp_path: Path, calendar_rel: str = "data/releases.json", content: str = '{"releases": []}') -> Path:
    repo = tmp_path / "site"
    (repo / ".git").mkdir(parents=True)
    target = repo / calendar_rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return repo


def _runner(*, current="main", dirty="", branches="", diff="DIFF\n", remote="git@github.com:user/site.git\n"):
    calls = []

    def run(cmd, cwd, capture_output, text, check):
        calls.append(cmd[1:])
        args = cmd[1:]
        out = ""
        if args[:2] == ["branch", "--show-current"]:
            out = current + ("\n" if current else "")
        elif args[:2] == ["status", "--porcelain"]:
            out = dirty
        elif args[:2] == ["branch", "--list"]:
            out = branches
        elif args and args[0] == "diff":
            out = diff
        elif args and args[0] == "show":
            out = "COMMITTED PATCH\n"
        elif args[:3] == ["remote", "get-url", "origin"]:
            out = remote
        return subprocess.CompletedProcess(cmd, 0, out, "")

    return run, calls


def test_detect_real_calendar_html_candidate(tmp_path):
    repo = _repo(tmp_path, "calendar/index.html", "<html></html>")
    assert _detect_calendar_file(repo).relative_to(repo).as_posix() == "calendar/index.html"


def test_patch_json_calendar_is_idempotent(tmp_path):
    p = tmp_path / "releases.json"
    p.write_text('{"releases": []}')
    _patch_structured(p, RELEASE)
    _patch_structured(p, RELEASE)
    data = json.loads(p.read_text())
    assert len(data["releases"]) == 1
    assert data["releases"][0]["status"] == "published"


def test_patch_html_calendar_matches_real_repo_shape(tmp_path):
    p = tmp_path / "index.html"
    p.write_text(
        '<article class="release-month"><h2>September 2026</h2><div class="release-events">'
        '<div class="release-event bilingual"><strong>14</strong><span>Bilingual 4</span></div>'
        "</div></article>"
    )
    _patch_structured(p, RELEASE)
    text = p.read_text()
    assert "Bilingual 4 · Published" in text
    assert 'title="Bilingual Yok 4 — available now"' in text
    again = _patch_structured_text(p, RELEASE, text)
    assert again == text


def test_patch_html_adds_missing_day_inside_existing_month(tmp_path):
    p = tmp_path / "index.html"
    original = (
        '<article class="release-month"><h2>September 2026</h2><div class="release-events">'
        '<div class="release-event bilingual"><strong>07</strong><span>Bilingual 3</span></div>'
        "</div></article>"
    )
    patched = _patch_structured_text(p, RELEASE, original)
    assert "<strong>14</strong>" in patched
    assert "Bilingual Yok 4 · Published" in patched


def test_malformed_structured_entries_raise_clear_error(tmp_path):
    p = tmp_path / "releases.json"
    p.write_text('{"releases": ["bad"]}')
    with pytest.raises(WebsiteError, match="release entry #1"):
        _patch_structured(p, RELEASE)


def test_unsupported_configured_calendar_format(tmp_path):
    repo = _repo(tmp_path, "calendar/releases.toml", "x")
    with pytest.raises(WebsiteError, match="Unsupported calendar file format"):
        _detect_calendar_file(repo, "calendar/releases.toml")


def test_malformed_html_month_raise_clear_error(tmp_path):
    p = tmp_path / "index.html"
    p.write_text("<html>no release-month</html>")
    with pytest.raises(WebsiteError, match="September 2026"):
        _patch_structured(p, RELEASE)


def test_prepare_website_update_dry_run_never_switches_or_writes(tmp_path):
    repo = _repo(tmp_path)
    target = repo / "data/releases.json"
    before = target.read_text()
    runner, calls = _runner()
    got = prepare_website_update(
        str(repo),
        "Book",
        "2026-09-14",
        "x",
        calendar_data_file="data/releases.json",
        dry_run=True,
        runner=runner,
        which=lambda _: "/usr/bin/git",
    )
    assert got["status"] == "dry-run"
    assert target.read_text() == before
    assert not any(call and call[0] == "switch" for call in calls)
    assert not any(call and call[0] == "commit" for call in calls)
    assert "+" in got["diff"]


def test_prepare_website_update_git_branch_commit_flow(tmp_path):
    repo = _repo(tmp_path)
    runner, calls = _runner()
    got = prepare_website_update(
        str(repo),
        "Book",
        "2026-09-14",
        "x",
        calendar_data_file="data/releases.json",
        runner=runner,
        which=lambda _: "/usr/bin/git",
    )
    assert got["status"] == "prepared"
    assert got["push_performed"] is False
    assert "github.com/user/site/compare/" in got["compare_url"]
    assert ["switch", "-c", "author-agent/2026-09-14-book"] in calls
    assert any(call and call[0] == "commit" for call in calls)
    assert not any(call and call[0] == "push" for call in calls)


def test_existing_branch_is_reused(tmp_path):
    repo = _repo(tmp_path)
    runner, calls = _runner(branches="  author-agent/2026-09-14-book\n")
    prepare_website_update(
        str(repo),
        "Book",
        "2026-09-14",
        "x",
        calendar_data_file="data/releases.json",
        runner=runner,
        which=lambda _: "/usr/bin/git",
    )
    assert ["switch", "author-agent/2026-09-14-book"] in calls
    assert ["switch", "-c", "author-agent/2026-09-14-book"] not in calls


def test_already_patched_release_returns_unchanged_without_commit(tmp_path):
    repo = _repo(tmp_path, content=json.dumps({"releases": [RELEASE]}))
    runner, calls = _runner(current="author-agent/2026-09-14-bilingual-yok-4", branches="*")
    got = prepare_website_update(
        str(repo),
        "Bilingual Yok 4",
        "2026-09-14",
        "https://example",
        calendar_data_file="data/releases.json",
        runner=runner,
        which=lambda _: "/usr/bin/git",
    )
    assert got["status"] == "unchanged"
    assert not any(call and call[0] == "commit" for call in calls)


def test_dirty_repo_is_blocked(tmp_path):
    repo = _repo(tmp_path)
    runner, _ = _runner(dirty=" M index.html\n")
    with pytest.raises(WebsiteError, match="uncommitted changes"):
        prepare_website_update(str(repo), "Book", "2026-09-14", "", runner=runner, which=lambda _: "/usr/bin/git")


def test_detached_head_is_blocked(tmp_path):
    repo = _repo(tmp_path)
    runner, _ = _runner(current="")
    with pytest.raises(WebsiteError, match="detached HEAD"):
        prepare_website_update(str(repo), "Book", "2026-09-14", "", runner=runner, which=lambda _: "/usr/bin/git")


def test_missing_git_binary_is_clear(tmp_path):
    repo = _repo(tmp_path)
    with pytest.raises(WebsiteError, match="not installed"):
        prepare_website_update(str(repo), "Book", "2026-09-14", "", which=lambda _: None)


def test_non_repo_is_clear(tmp_path):
    with pytest.raises(WebsiteError, match="not a Git repository"):
        prepare_website_update(str(tmp_path), "Book", "2026-09-14", "")


def test_patch_yaml_and_js(tmp_path):
    y = tmp_path / "releases.yaml"
    y.write_text("releases: []\n")
    _patch_structured(y, RELEASE)
    assert "Bilingual Yok 4" in y.read_text()
    j = tmp_path / "releases.js"
    j.write_text("const releases = [];\n")
    _patch_structured(j, RELEASE)
    assert "Bilingual Yok 4" in j.read_text()


def test_malformed_json_and_js_raise(tmp_path):
    j = tmp_path / "bad.json"
    j.write_text("{")
    with pytest.raises(WebsiteError, match="Malformed JSON"):
        _patch_structured(j, RELEASE)
    js = tmp_path / "bad.js"
    js.write_text("export default []")
    with pytest.raises(WebsiteError, match="Unsupported JavaScript"):
        _patch_structured(js, RELEASE)


def test_unconfigured_repo_skips(tmp_path):
    got = prepare_website_update("", "Book", "2026-09-14", "", which=lambda _: "/usr/bin/git")
    assert got["status"] == "skipped"


def test_configured_missing_calendar_is_clear(tmp_path):
    repo = tmp_path / "site"
    (repo / ".git").mkdir(parents=True)
    with pytest.raises(WebsiteError, match="does not exist"):
        _detect_calendar_file(repo, "calendar/nope.json")
