from __future__ import annotations

import difflib
import logging
import re
import shutil
import subprocess
from typing import Callable

from .errors import WebsiteError
from .logging_utils import log_event
from .website_calendar import (
    calendar_format,
    detect_calendar_file,
    patch_calendar,
    patch_calendar_text,
    upsert_release,
    validate_release_list,
)
from .website_git import (
    ensure_git_available,
    git,
    github_compare_url,
    push_branch,
    resolve_repo_path,
)

# Compatibility aliases retained for existing callers/tests.
_git = git
_ensure_git_available = ensure_git_available
_detect_calendar_file = detect_calendar_file
_validate_release_list = validate_release_list
_upsert_release = upsert_release
_patch_structured_text = patch_calendar_text
_patch_structured = patch_calendar
_github_compare_url = github_compare_url
LOG = logging.getLogger(__name__)


def _slug(text: str) -> str:
    return re.sub(r"-+", "-", "".join(char.lower() if char.isalnum() else "-" for char in text)).strip("-")


def _readable_virtual_diff(before: str, after: str, rel: str) -> str:
    if before == after:
        return ""
    if "\n" in before.strip("\n") or "\n" in after.strip("\n"):
        return "".join(
            difflib.unified_diff(
                before.splitlines(keepends=True),
                after.splitlines(keepends=True),
                fromfile=f"a/{rel}",
                tofile=f"b/{rel}",
            )
        )
    prefix = 0
    max_prefix = min(len(before), len(after))
    while prefix < max_prefix and before[prefix] == after[prefix]:
        prefix += 1
    suffix = 0
    while (
        suffix < len(before) - prefix
        and suffix < len(after) - prefix
        and before[len(before) - 1 - suffix] == after[len(after) - 1 - suffix]
    ):
        suffix += 1
    start = max(0, prefix - 120)
    before_end = min(len(before), len(before) - suffix + 120)
    after_end = min(len(after), len(after) - suffix + 120)
    return (
        f"--- a/{rel}\n+++ b/{rel}\n@@ compact character diff @@\n"
        f"- {before[start:before_end]}\n+ {after[start:after_end]}\n"
    )


def push_website_branch(
    repo_path: str,
    branch: str,
    *,
    runner: Callable = subprocess.run,
    which: Callable = shutil.which,
) -> dict:
    """Push an already-prepared branch after explicit human approval."""
    return push_branch(repo_path, branch, runner=runner, which=which)


def prepare_website_update(
    repo_path: str,
    title: str,
    release_date: str,
    book_url: str | None,
    *,
    calendar_data_file: str = "",
    branch_prefix: str = "author-agent",
    commit: bool = True,
    dry_run: bool = False,
    runner: Callable = subprocess.run,
    which: Callable = shutil.which,
) -> dict:
    repo = resolve_repo_path(repo_path)
    log_event(LOG, logging.INFO, "website_prepare_started", date=release_date, title=title, dry_run=dry_run)
    if repo is None:
        return {
            "status": "skipped",
            "reason": "Website repository is not configured. Set AUTHOR_AGENT_WEBSITE_REPO.",
            "dry_run": dry_run,
        }
    if not repo.is_dir() or not (repo / ".git").exists():
        raise WebsiteError(f"Website path is not a Git repository: {repo}")
    ensure_git_available(which)

    target = detect_calendar_file(repo, calendar_data_file)
    if target is None:
        raise WebsiteError(
            "No calendar file could be detected. Set website.calendar_data_file or "
            "AUTHOR_AGENT_WEBSITE_REPO to a repository containing a supported calendar file."
        )
    current = git(repo, "branch", "--show-current", runner=runner).stdout.strip()
    if not current:
        raise WebsiteError("The website repository is in detached HEAD state. Check out a branch before patching.")
    if git(repo, "status", "--porcelain", runner=runner).stdout.strip():
        raise WebsiteError(
            "The website repository has uncommitted changes. Commit, stash, or discard them before running the patch."
        )

    branch = f"{branch_prefix}/{release_date}-{_slug(title)[:40]}"
    release = {"date": release_date, "title": title, "status": "published", "url": book_url or ""}
    rel = str(target.relative_to(repo))
    before = target.read_text(encoding="utf-8")
    after = patch_calendar_text(target, release, before)
    virtual_diff = _readable_virtual_diff(before, after, rel)
    compare_url = github_compare_url(repo, branch, runner=runner)

    if dry_run:
        log_event(LOG, logging.INFO, "website_prepare_dry_run", file=rel, branch=branch, changed=bool(virtual_diff))
        return {
            "status": "dry-run" if virtual_diff else "unchanged",
            "branch": branch,
            "file": rel,
            "format": calendar_format(target),
            "diff": virtual_diff,
            "compare_url": compare_url,
            "previous_branch": current,
            "push_performed": False,
            "dry_run": True,
            "manual_next_step": "No repository changes were made in dry-run mode.",
        }

    branches = git(repo, "branch", "--list", branch, runner=runner).stdout.strip()
    if current != branch:
        if branches:
            git(repo, "switch", branch, runner=runner)
        else:
            git(repo, "switch", "-c", branch, runner=runner)

    before = target.read_text(encoding="utf-8")
    after = patch_calendar_text(target, release, before)
    if after == before:
        return {
            "status": "unchanged",
            "branch": branch,
            "file": rel,
            "format": calendar_format(target),
            "diff": "",
            "compare_url": compare_url,
            "previous_branch": current,
            "push_performed": False,
            "dry_run": False,
            "manual_next_step": "The calendar already contains this published release; no new commit was created.",
        }

    target.write_text(after, encoding="utf-8")
    diff = git(repo, "diff", "--word-diff=plain", "--unified=0", "--", rel, runner=runner).stdout
    if commit:
        git(repo, "add", "--", rel, runner=runner)
        git(repo, "commit", "-m", f"chore(calendar): update {title} for {release_date}", runner=runner)
        diff = git(
            repo,
            "show",
            "--word-diff=plain",
            "--unified=0",
            "--format=medium",
            "HEAD",
            runner=runner,
        ).stdout
    log_event(LOG, logging.INFO, "website_prepare_complete", file=rel, branch=branch, committed=commit)
    return {
        "status": "prepared",
        "branch": branch,
        "file": rel,
        "format": calendar_format(target),
        "diff": diff,
        "compare_url": compare_url,
        "previous_branch": current,
        "push_performed": False,
        "dry_run": False,
        "manual_next_step": (
            f"Review the diff, then manually run `git push -u origin {branch}` if approved. "
            "Push/merge is never performed automatically."
        ),
    }
