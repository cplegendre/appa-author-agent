from __future__ import annotations

from types import SimpleNamespace

import pytest

from author_agent.errors import WebsiteError
from author_agent.website_git import git, github_compare_url, push_branch, validate_repo


def _proc(returncode=0, stdout="", stderr=""):
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


def _repo(tmp_path):
    repo = tmp_path / "site"
    repo.mkdir()
    (repo / ".git").mkdir()
    return repo


def test_git_wraps_missing_binary(tmp_path):
    repo = _repo(tmp_path)

    def runner(*args, **kwargs):
        raise FileNotFoundError("git")

    with pytest.raises(WebsiteError, match="not installed"):
        git(repo, "status", runner=runner)


def test_git_wraps_command_failure_with_stderr(tmp_path):
    repo = _repo(tmp_path)

    def runner(*args, **kwargs):
        return _proc(returncode=128, stderr="fatal: bad revision\n")

    with pytest.raises(WebsiteError, match=r"git status.*fatal: bad revision"):
        git(repo, "status", runner=runner)


def test_github_compare_url_returns_empty_when_origin_lookup_fails(tmp_path):
    repo = _repo(tmp_path)

    def runner(cmd, **kwargs):
        return _proc(returncode=2, stderr="No such remote 'origin'")

    assert github_compare_url(repo, "feature/test", runner=runner) == ""


def test_github_compare_url_returns_empty_for_non_github_remote(tmp_path):
    repo = _repo(tmp_path)

    def runner(cmd, **kwargs):
        return _proc(stdout="ssh://git@example.com/team/repo.git\n")

    assert github_compare_url(repo, "feature/test", runner=runner) == ""


def test_validate_repo_rejects_non_repo(tmp_path):
    path = tmp_path / "not-a-repo"
    path.mkdir()
    with pytest.raises(WebsiteError, match="not a Git repository"):
        validate_repo(path, which=lambda _: "/usr/bin/git")


def test_validate_repo_rejects_detached_head(tmp_path):
    repo = _repo(tmp_path)
    responses = iter([_proc(stdout=""), _proc(stdout="")])
    with pytest.raises(WebsiteError, match="detached HEAD"):
        validate_repo(repo, runner=lambda *args, **kwargs: next(responses), which=lambda _: "/usr/bin/git")


def test_validate_repo_rejects_dirty_tree(tmp_path):
    repo = _repo(tmp_path)
    responses = iter([_proc(stdout="main\n"), _proc(stdout=" M calendar/index.html\n")])
    with pytest.raises(WebsiteError, match="uncommitted changes"):
        validate_repo(repo, runner=lambda *args, **kwargs: next(responses), which=lambda _: "/usr/bin/git")


def test_push_rejects_missing_repo_configuration(monkeypatch):
    monkeypatch.delenv("AUTHOR_AGENT_WEBSITE_REPO", raising=False)
    with pytest.raises(WebsiteError, match="not configured"):
        push_branch("", "author-agent/test", which=lambda _: "/usr/bin/git")


def test_push_rejects_missing_local_prepared_branch(tmp_path):
    repo = _repo(tmp_path)
    branch = "author-agent/test"
    responses = {
        ("branch", "--show-current"): _proc(stdout=branch + "\n"),
        ("status", "--porcelain"): _proc(stdout=""),
        ("branch", "--list", branch): _proc(stdout=""),
    }

    def runner(cmd, **kwargs):
        return responses[tuple(cmd[1:])]

    with pytest.raises(WebsiteError, match="does not exist locally"):
        push_branch(str(repo), branch, runner=runner, which=lambda _: "/usr/bin/git")


def test_push_rejection_surfaces_remote_error(tmp_path):
    repo = _repo(tmp_path)
    branch = "author-agent/test"
    responses = {
        ("branch", "--show-current"): _proc(stdout=branch + "\n"),
        ("status", "--porcelain"): _proc(stdout=""),
        ("branch", "--list", branch): _proc(stdout=branch + "\n"),
        ("push", "-u", "origin", branch): _proc(returncode=1, stderr="remote rejected\n"),
    }

    def runner(cmd, **kwargs):
        return responses[tuple(cmd[1:])]

    with pytest.raises(WebsiteError, match="remote rejected"):
        push_branch(str(repo), branch, runner=runner, which=lambda _: "/usr/bin/git")
