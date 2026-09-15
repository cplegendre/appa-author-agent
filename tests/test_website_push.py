from types import SimpleNamespace

import pytest

from author_agent.website import WebsiteError, push_website_branch


def _runner_factory(outputs):
    calls = []

    def runner(cmd, **kwargs):
        calls.append(cmd)
        key = tuple(cmd[1:])
        rc, out, err = outputs.get(key, (0, "", ""))
        return SimpleNamespace(returncode=rc, stdout=out, stderr=err)

    return runner, calls


def test_push_branch_is_explicit_and_targets_origin(tmp_path):
    repo = tmp_path / "site"
    repo.mkdir()
    (repo / ".git").mkdir()
    branch = "author-agent/2026-09-14-book"
    outputs = {
        ("branch", "--show-current"): (0, branch + "\n", ""),
        ("status", "--porcelain"): (0, "", ""),
        ("branch", "--list", branch): (0, branch + "\n", ""),
        ("push", "-u", "origin", branch): (0, "ok\n", ""),
    }
    runner, calls = _runner_factory(outputs)
    result = push_website_branch(str(repo), branch, runner=runner, which=lambda _: "/usr/bin/git")
    assert result["status"] == "pushed"
    assert ["git", "push", "-u", "origin", branch] in calls


def test_push_rejects_wrong_current_branch(tmp_path):
    repo = tmp_path / "site"
    repo.mkdir()
    (repo / ".git").mkdir()
    runner, _ = _runner_factory({("branch", "--show-current"): (0, "main\n", "")})
    with pytest.raises(WebsiteError, match="branch mismatch"):
        push_website_branch(str(repo), "author-agent/x", runner=runner, which=lambda _: "/usr/bin/git")
