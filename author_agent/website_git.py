from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Callable

from .errors import WebsiteError

Runner = Callable[..., subprocess.CompletedProcess]


def git(repo: Path, *args: str, runner: Runner = subprocess.run) -> subprocess.CompletedProcess:
    try:
        proc = runner(["git", *args], cwd=repo, capture_output=True, text=True, check=False)
    except FileNotFoundError as exc:
        raise WebsiteError("Git is not installed or is not available on PATH.") from exc
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "unknown git error").strip()
        raise WebsiteError(f"Git command failed: git {' '.join(args)}. {detail}")
    return proc


def ensure_git_available(which: Callable[[str], str | None] = shutil.which) -> None:
    if which("git") is None:
        raise WebsiteError("Git is not installed or is not available on PATH.")


def resolve_repo_path(configured: str) -> Path | None:
    raw = os.getenv("AUTHOR_AGENT_WEBSITE_REPO", "").strip() or configured.strip()
    return Path(raw).expanduser().resolve() if raw else None


def github_compare_url(repo: Path, branch: str, runner: Runner = subprocess.run) -> str:
    try:
        remote = git(repo, "remote", "get-url", "origin", runner=runner).stdout.strip()
    except WebsiteError:
        return ""
    match = re.search(r"github\.com[:/]([^/]+)/([^/]+?)(?:\.git)?$", remote)
    return f"https://github.com/{match.group(1)}/{match.group(2)}/compare/{branch}" if match else ""


def validate_repo(
    repo: Path,
    *,
    runner: Runner = subprocess.run,
    which: Callable[[str], str | None] = shutil.which,
) -> str:
    if not repo.is_dir() or not (repo / ".git").exists():
        raise WebsiteError(f"Website path is not a Git repository: {repo}")
    ensure_git_available(which)
    current = git(repo, "branch", "--show-current", runner=runner).stdout.strip()
    if not current:
        raise WebsiteError("The website repository is in detached HEAD state. Check out a branch before continuing.")
    dirty = git(repo, "status", "--porcelain", runner=runner).stdout.strip()
    if dirty:
        raise WebsiteError("The website repository has uncommitted changes. Commit, stash, or discard them first.")
    return current


def push_branch(
    repo_path: str,
    branch: str,
    *,
    runner: Runner = subprocess.run,
    which: Callable[[str], str | None] = shutil.which,
) -> dict:
    repo = resolve_repo_path(repo_path)
    if repo is None:
        raise WebsiteError("Website repository is not configured. Set AUTHOR_AGENT_WEBSITE_REPO.")
    current = validate_repo(repo, runner=runner, which=which)
    if current != branch:
        raise WebsiteError(f"Prepared branch mismatch: expected `{branch}`, but current branch is `{current}`.")
    exists = git(repo, "branch", "--list", branch, runner=runner).stdout.strip()
    if not exists:
        raise WebsiteError(f"Prepared branch does not exist locally: {branch}")
    proc = git(repo, "push", "-u", "origin", branch, runner=runner)
    return {
        "status": "pushed",
        "branch": branch,
        "push_performed": True,
        "stdout": (proc.stdout or "").strip(),
        "stderr": (proc.stderr or "").strip(),
    }
