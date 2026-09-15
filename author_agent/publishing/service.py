from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone

from author_agent.logging_utils import log_json_event, redact_text
from author_agent.persistence import AutomationStore
from author_agent.workflow import WorkflowService, WorkflowState

from .base import PublishRequest, PublishResult, SocialPublisher

LOG = logging.getLogger(__name__)


class PublishingService:
    def __init__(
        self,
        store: AutomationStore,
        workflow: WorkflowService,
        publisher: SocialPublisher,
        alerter=None,
    ):
        self.store = store
        self.workflow = workflow
        self.publisher = publisher
        self.alerter = alerter

    def _record_failure(self, workflow_id: str, key: str, platform: str, exc: Exception) -> None:
        reason = redact_text(exc)
        now = datetime.now(timezone.utc).isoformat()
        with self.store.connect() as con:
            con.execute(
                "UPDATE publish_attempts SET status=?,response_json=? WHERE idempotency_key=?",
                ("failed", self.store.dumps({"error": reason, "type": type(exc).__name__}), key),
            )
        try:
            row = self.workflow.get(workflow_id)
            if WorkflowState(row["state"]) in {WorkflowState.PUBLISHING, WorkflowState.SCHEDULED}:
                self.workflow.transition(workflow_id, WorkflowState.FAILED, reason="publication failed", error=reason)
        except Exception:
            LOG.exception("Could not persist workflow failure state")
        log_json_event(
            LOG,
            logging.ERROR,
            "publication_attempt",
            workflow_id=workflow_id,
            platform=platform,
            outcome="failure",
            reason=reason,
            error_type=type(exc).__name__,
            at=now,
        )
        if self.alerter is not None:
            try:
                self.alerter(
                    {
                        "workflow_id": workflow_id,
                        "platform": platform,
                        "reason": reason,
                        "error_type": type(exc).__name__,
                    }
                )
            except Exception:
                LOG.exception("Publication failure alert callback crashed")

    def _log_success(self, workflow_id: str, platform: str, result: PublishResult) -> None:
        log_json_event(
            LOG,
            logging.INFO,
            "publication_attempt",
            workflow_id=workflow_id,
            platform=platform,
            outcome="success",
            status=result.status,
            external_id=result.external_id,
        )

    @staticmethod
    def idempotency_key(workflow_id: str, platform: str, text: str) -> str:
        digest = hashlib.sha256(f"{workflow_id}\n{platform}\n{text}".encode()).hexdigest()[:24]
        return f"author-agent:{digest}"

    def _existing_result(self, key: str) -> PublishResult | None:
        with self.store.connect() as con:
            existing = con.execute(
                "SELECT external_id,status,response_json FROM publish_attempts WHERE idempotency_key=?",
                (key,),
            ).fetchone()
        if existing and existing["external_id"]:
            return PublishResult(external_id=existing["external_id"], status=existing["status"])
        return None

    def publish(
        self,
        workflow_id: str,
        *,
        platform: str,
        text: str,
        media_url: str | None = None,
        scheduled_at: datetime | None = None,
    ) -> PublishResult:
        row = self.workflow.get(workflow_id)
        state = WorkflowState(row["state"])
        key = self.idempotency_key(workflow_id, platform, text)
        if state == WorkflowState.PUBLISHED:
            existing = self._existing_result(key)
            if existing is not None:
                return existing
        if state not in {WorkflowState.APPROVED, WorkflowState.SCHEDULED, WorkflowState.PUBLISHING}:
            raise ValueError(f"Workflow {workflow_id} is not approved/scheduled for publishing")
        if row["approved_hash"] and row["approved_hash"] != hashlib.sha256(text.encode()).hexdigest():
            self.workflow.update_content(workflow_id, text)
            raise ValueError("Post content changed after approval; reapproval is required")
        payload = {
            "platform": platform,
            "text": text,
            "media_url": media_url,
            "scheduled_at": scheduled_at.isoformat() if scheduled_at else None,
        }
        created = self.workflow.register_publish_attempt(
            workflow_id,
            provider=type(self.publisher).__name__,
            platform=platform,
            idempotency_key=key,
            payload=payload,
        )
        if not created:
            existing = self._existing_result(key)
            if existing is not None:
                return existing
            raise ValueError("Duplicate publish attempt is already in progress")
        if state != WorkflowState.PUBLISHING and scheduled_at is None:
            self.workflow.transition(workflow_id, WorkflowState.PUBLISHING, reason="publish started")
        request = PublishRequest(
            platform=platform,
            text=text,
            media_url=media_url,
            scheduled_at=scheduled_at,
            idempotency_key=key,
        )
        try:
            result = self.publisher.schedule_post(request) if scheduled_at else self.publisher.publish_post(request)
        except Exception as exc:
            self._record_failure(workflow_id, key, platform, exc)
            raise
        self._log_success(workflow_id, platform, result)
        now = datetime.now(timezone.utc).isoformat()
        with self.store.connect() as con:
            con.execute(
                "UPDATE publish_attempts SET status=?,external_id=?,response_json=? WHERE idempotency_key=?",
                (result.status, result.external_id, self.store.dumps(result.raw or {}), key),
            )
            if result.status == "scheduled":
                con.execute(
                    "UPDATE workflows SET state=?,scheduled_at=?,external_id=?,updated_at=? WHERE id=?",
                    (
                        WorkflowState.SCHEDULED.value,
                        scheduled_at.isoformat() if scheduled_at else now,
                        result.external_id,
                        now,
                        workflow_id,
                    ),
                )
            else:
                con.execute(
                    "UPDATE workflows SET state=?,published_at=?,external_id=?,social_url=?,updated_at=? WHERE id=?",
                    (
                        WorkflowState.PUBLISHED.value,
                        now,
                        result.external_id,
                        result.url,
                        now,
                        workflow_id,
                    ),
                )
        return result

    def run_due(self, *, now: datetime | None = None) -> list[PublishResult]:
        now = now or datetime.now(timezone.utc)
        with self.store.connect() as con:
            rows = con.execute(
                "SELECT a.idempotency_key,a.payload_json,a.workflow_id FROM publish_attempts a "
                "JOIN workflows w ON w.id=a.workflow_id WHERE a.status='scheduled' "
                "AND w.state='SCHEDULED' AND w.scheduled_at IS NOT NULL AND w.scheduled_at<=? "
                "ORDER BY w.scheduled_at",
                (now.isoformat(),),
            ).fetchall()
        results: list[PublishResult] = []
        for row in rows:
            payload = json.loads(row["payload_json"] or "{}")
            request = PublishRequest(
                platform=payload["platform"],
                text=payload["text"],
                media_url=payload.get("media_url"),
                idempotency_key=row["idempotency_key"],
            )
            self.workflow.transition(
                row["workflow_id"],
                WorkflowState.PUBLISHING,
                reason="scheduled publication due",
            )
            try:
                result = self.publisher.publish_post(request)
            except Exception as exc:
                self._record_failure(row["workflow_id"], row["idempotency_key"], payload["platform"], exc)
                continue
            self._log_success(row["workflow_id"], payload["platform"], result)
            published_at = datetime.now(timezone.utc).isoformat()
            with self.store.connect() as con:
                con.execute(
                    "UPDATE publish_attempts SET status=?,external_id=?,response_json=? WHERE idempotency_key=?",
                    (
                        result.status,
                        result.external_id,
                        self.store.dumps(result.raw or {}),
                        row["idempotency_key"],
                    ),
                )
                con.execute(
                    "UPDATE workflows SET state=?,published_at=?,external_id=?,social_url=?,updated_at=? WHERE id=?",
                    (
                        WorkflowState.PUBLISHED.value,
                        published_at,
                        result.external_id,
                        result.url,
                        published_at,
                        row["workflow_id"],
                    ),
                )
            results.append(result)
        return results
