from pathlib import Path

import pytest

from author_agent.persistence import AutomationStore
from author_agent.workflow import WorkflowService, WorkflowState


def service(tmp_path: Path) -> WorkflowService:
    return WorkflowService(AutomationStore(tmp_path / "automation.sqlite3"))


def test_schema_migration_and_workflow_transitions(tmp_path):
    svc = service(tmp_path)
    assert svc.store.schema_version() == 27
    wid = svc.create(book="Book", campaign="launch", platform="instagram")
    for state in [
        WorkflowState.ANALYZED,
        WorkflowState.DRAFTED,
        WorkflowState.VALIDATED,
        WorkflowState.REVIEW_REQUIRED,
    ]:
        svc.transition(wid, state)
    row = svc.approve(wid, "approved copy")
    assert row["state"] == "APPROVED"
    assert len(svc.history(wid)) == 6


def test_invalid_transition_rejected(tmp_path):
    svc = service(tmp_path)
    wid = svc.create()
    with pytest.raises(ValueError, match="Invalid workflow transition"):
        svc.transition(wid, WorkflowState.PUBLISHED)


def test_approval_invalidated_after_edit(tmp_path):
    svc = service(tmp_path)
    wid = svc.create(state=WorkflowState.REVIEW_REQUIRED)
    svc.approve(wid, "approved")
    row = svc.update_content(wid, "edited")
    assert row["state"] == "REVIEW_REQUIRED"
    assert row["approved_hash"] is None


def test_failed_transition_increments_retry(tmp_path):
    svc = service(tmp_path)
    wid = svc.create()
    row = svc.transition(wid, WorkflowState.FAILED, error="boom")
    assert row["retry_count"] == 1
    assert row["last_error"] == "boom"


def test_publish_attempt_idempotency(tmp_path):
    svc = service(tmp_path)
    wid = svc.create()
    assert svc.register_publish_attempt(
        wid,
        provider="fake",
        platform="facebook",
        idempotency_key="one",
        payload={"x": 1},
    )
    assert not svc.register_publish_attempt(
        wid,
        provider="fake",
        platform="facebook",
        idempotency_key="one",
        payload={"x": 1},
    )
