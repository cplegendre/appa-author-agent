#!/usr/bin/env python3
"""Opt-in Meta publishing validation for a dedicated test Page/account.

Default execution is dry-run only. Live posting requires both --live and the
literal confirmation token LIVE_META_TEST.
"""

from __future__ import annotations

import argparse
import os
import tempfile
from pathlib import Path

from author_agent.config import load_settings
from author_agent.persistence import AutomationStore
from author_agent.publishing import MetaConfig, MetaPublisher, PublishingService
from author_agent.workflow import WorkflowService, WorkflowState

TEST_TEXT = "Author Agent v26 validation post — safe test content."


def _approved_workflow(store: AutomationStore, text: str) -> tuple[WorkflowService, str]:
    workflow = WorkflowService(store)
    workflow_id = workflow.create(
        book="validation",
        campaign="meta-live-validation",
        platform="facebook",
        state=WorkflowState.INGESTED,
        text=text,
    )
    for state in (
        WorkflowState.ANALYZED,
        WorkflowState.DRAFTED,
        WorkflowState.VALIDATED,
        WorkflowState.REVIEW_REQUIRED,
    ):
        workflow.transition(workflow_id, state, reason="validation script")
    workflow.approve(workflow_id, text)
    return workflow, workflow_id


def _publisher(*, dry_run: bool, token: str, page_id: str, settings) -> MetaPublisher:
    return MetaPublisher(
        MetaConfig(
            access_token=token,
            facebook_page_id=page_id,
            graph_version=settings.meta.graph_version,
            dry_run=dry_run,
            max_retries=settings.publishing.max_retries,
        )
    )


def run_cycle(*, live: bool, confirm: str) -> None:
    settings = load_settings()
    token = os.getenv(settings.meta.access_token_env, "").strip()
    page_id = settings.meta.facebook_page_id.strip()

    with tempfile.TemporaryDirectory(prefix="author-agent-meta-validation-") as tmp:
        dry_store = AutomationStore(Path(tmp) / "dry.sqlite3")
        dry_workflow, dry_id = _approved_workflow(dry_store, TEST_TEXT)
        dry_service = PublishingService(
            dry_store,
            dry_workflow,
            _publisher(dry_run=True, token="", page_id="", settings=settings),
        )
        first = dry_service.publish(dry_id, platform="facebook", text=TEST_TEXT)
        second = dry_service.publish(dry_id, platform="facebook", text=TEST_TEXT)
        assert first.external_id == second.external_id, "dry-run idempotency failed"
        print(f"DRY-RUN PASS: {first.external_id}; duplicate call returned same publication")

        if not live:
            print(
                "LIVE NOT RUN: re-run with --live --confirm LIVE_META_TEST "
                "after configuring a dedicated Meta test Page."
            )
            return
        if confirm != "LIVE_META_TEST":
            raise SystemExit("Live validation requires --confirm LIVE_META_TEST")
        if not token or not page_id:
            raise SystemExit(
                f"Live validation requires {settings.meta.access_token_env} and "
                "meta.facebook_page_id for a dedicated test Page."
            )

        live_store = AutomationStore(Path(tmp) / "live.sqlite3")
        live_workflow, live_id = _approved_workflow(live_store, TEST_TEXT)
        live_service = PublishingService(
            live_store,
            live_workflow,
            _publisher(dry_run=False, token=token, page_id=page_id, settings=settings),
        )
        one = live_service.publish(live_id, platform="facebook", text=TEST_TEXT)
        two = live_service.publish(live_id, platform="facebook", text=TEST_TEXT)
        assert one.external_id == two.external_id, "live idempotency failed; investigate immediately"
        print(f"LIVE PASS: Meta post id={one.external_id}; duplicate call did not create a second post")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--live",
        action="store_true",
        help="Actually publish one low-risk test post to the configured test Page",
    )
    parser.add_argument("--confirm", default="", help="Required literal LIVE_META_TEST for live mode")
    args = parser.parse_args()
    run_cycle(live=args.live, confirm=args.confirm)


if __name__ == "__main__":
    main()
