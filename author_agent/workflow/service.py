from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from enum import StrEnum

from author_agent.persistence import AutomationStore


class WorkflowState(StrEnum):
    INGESTED = "INGESTED"
    ANALYZED = "ANALYZED"
    DRAFTED = "DRAFTED"
    VALIDATED = "VALIDATED"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"  # persisted legacy spelling
    IN_REVIEW = "IN_REVIEW"  # accepted review-state spelling
    APPROVED = "APPROVED"
    SCHEDULED = "SCHEDULED"
    PUBLISHING = "PUBLISHING"
    PUBLISHED = "PUBLISHED"
    MEASURED = "MEASURED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


_REVIEW_STATES = {WorkflowState.REVIEW_REQUIRED, WorkflowState.IN_REVIEW}
_PREPUBLICATION_REJECTABLE = {
    WorkflowState.INGESTED,
    WorkflowState.ANALYZED,
    WorkflowState.DRAFTED,
    WorkflowState.VALIDATED,
    WorkflowState.REVIEW_REQUIRED,
    WorkflowState.IN_REVIEW,
    WorkflowState.APPROVED,
    WorkflowState.SCHEDULED,
}

ALLOWED = {
    WorkflowState.INGESTED: {
        WorkflowState.ANALYZED,
        WorkflowState.FAILED,
        WorkflowState.CANCELLED,
        WorkflowState.REJECTED,
    },
    WorkflowState.ANALYZED: {
        WorkflowState.DRAFTED,
        WorkflowState.FAILED,
        WorkflowState.CANCELLED,
        WorkflowState.REJECTED,
    },
    WorkflowState.DRAFTED: {
        WorkflowState.VALIDATED,
        WorkflowState.FAILED,
        WorkflowState.CANCELLED,
        WorkflowState.REJECTED,
    },
    WorkflowState.VALIDATED: {
        WorkflowState.REVIEW_REQUIRED,
        WorkflowState.IN_REVIEW,
        WorkflowState.APPROVED,
        WorkflowState.FAILED,
        WorkflowState.REJECTED,
    },
    WorkflowState.REVIEW_REQUIRED: {
        WorkflowState.APPROVED,
        WorkflowState.DRAFTED,
        WorkflowState.CANCELLED,
        WorkflowState.REJECTED,
    },
    WorkflowState.IN_REVIEW: {
        WorkflowState.APPROVED,
        WorkflowState.DRAFTED,
        WorkflowState.CANCELLED,
        WorkflowState.REJECTED,
    },
    WorkflowState.APPROVED: {
        WorkflowState.SCHEDULED,
        WorkflowState.PUBLISHING,
        WorkflowState.DRAFTED,
        WorkflowState.CANCELLED,
        WorkflowState.REJECTED,
    },
    WorkflowState.SCHEDULED: {
        WorkflowState.PUBLISHING,
        WorkflowState.CANCELLED,
        WorkflowState.FAILED,
        WorkflowState.REJECTED,
    },
    WorkflowState.PUBLISHING: {WorkflowState.PUBLISHED, WorkflowState.FAILED},
    WorkflowState.PUBLISHED: {WorkflowState.MEASURED, WorkflowState.FAILED},
    WorkflowState.MEASURED: {WorkflowState.MEASURED},
    WorkflowState.FAILED: {
        WorkflowState.ANALYZED,
        WorkflowState.DRAFTED,
        WorkflowState.PUBLISHING,
        WorkflowState.CANCELLED,
    },
    WorkflowState.CANCELLED: set(),
    WorkflowState.REJECTED: set(),
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _metadata(row: dict) -> dict:
    try:
        value = json.loads(row.get("metadata_json") or "{}")
    except (TypeError, json.JSONDecodeError):
        value = {}
    return value if isinstance(value, dict) else {}


def _role_from_metadata(metadata: dict) -> str:
    role = str(metadata.get("post_role") or "").strip()
    if role:
        return role
    kind = str(metadata.get("kind") or "").strip()
    if kind == "launch":
        return "launch"
    if kind == "evergreen_reminder":
        return "evergreen"
    if kind:
        return "reminder"
    return ""


class WorkflowService:
    def __init__(self, store: AutomationStore):
        self.store = store

    def create(
        self,
        *,
        book: str = "",
        campaign: str = "",
        platform: str = "",
        state: WorkflowState = WorkflowState.INGESTED,
        text: str = "",
        metadata: dict | None = None,
    ) -> str:
        workflow_id = str(uuid.uuid4())
        now = utc_now()
        meta = dict(metadata or {})
        if text:
            meta.setdefault("drafts", {})["text"] = text
        with self.store.connect() as con:
            con.execute(
                "INSERT INTO workflows("
                "id,book,campaign,platform,state,created_at,updated_at,"
                "content_hash,metadata_json"
                ") VALUES(?,?,?,?,?,?,?,?,?)",
                (
                    workflow_id,
                    book,
                    campaign,
                    platform,
                    state.value,
                    now,
                    now,
                    content_hash(text) if text else "",
                    self.store.dumps(meta),
                ),
            )
            con.execute(
                "INSERT INTO workflow_transitions(workflow_id,from_state,to_state,at,reason) VALUES(?,?,?,?,?)",
                (workflow_id, None, state.value, now, "created"),
            )
        return workflow_id

    def get(self, workflow_id: str) -> dict:
        with self.store.connect() as con:
            row = con.execute("SELECT * FROM workflows WHERE id=?", (workflow_id,)).fetchone()
        if row is None:
            raise KeyError(workflow_id)
        return dict(row)

    def transition(
        self, workflow_id: str, to_state: WorkflowState, *, reason: str = "", error: str | None = None
    ) -> dict:
        row = self.get(workflow_id)
        current = WorkflowState(row["state"])
        if to_state == WorkflowState.REJECTED and not str(reason).strip():
            raise ValueError("Rejecting a workflow requires a non-empty reason")
        if to_state not in ALLOWED[current]:
            raise ValueError(f"Invalid workflow transition: {current.value} -> {to_state.value}")
        now = utc_now()
        retry_count = int(row["retry_count"]) + (1 if to_state == WorkflowState.FAILED else 0)
        with self.store.connect() as con:
            con.execute(
                "UPDATE workflows SET state=?,updated_at=?,last_error=?,retry_count=? WHERE id=?",
                (to_state.value, now, error, retry_count, workflow_id),
            )
            con.execute(
                "INSERT INTO workflow_transitions(workflow_id,from_state,to_state,at,reason) VALUES(?,?,?,?,?)",
                (workflow_id, current.value, to_state.value, now, reason),
            )
        return self.get(workflow_id)

    def reject(self, workflow_id: str, reason: str) -> dict:
        row = self.get(workflow_id)
        state = WorkflowState(row["state"])
        if state not in _PREPUBLICATION_REJECTABLE:
            raise ValueError(f"Workflow {workflow_id} cannot be rejected from {state.value}")
        return self.transition(workflow_id, WorkflowState.REJECTED, reason=reason)

    def approve(self, workflow_id: str, text: str) -> dict:
        row = self.get(workflow_id)
        if WorkflowState(row["state"]) not in _REVIEW_STATES:
            raise ValueError("Workflow must be in review before approval")
        digest = content_hash(text)
        now = utc_now()
        with self.store.connect() as con:
            con.execute(
                "UPDATE workflows SET state=?,approved_hash=?,content_hash=?,updated_at=? WHERE id=?",
                (WorkflowState.APPROVED.value, digest, digest, now, workflow_id),
            )
            con.execute(
                "INSERT INTO workflow_transitions(workflow_id,from_state,to_state,at,reason) VALUES(?,?,?,?,?)",
                (workflow_id, row["state"], WorkflowState.APPROVED.value, now, "explicit approval"),
            )
        return self.get(workflow_id)

    def update_content(self, workflow_id: str, text: str) -> dict:
        row = self.get(workflow_id)
        digest = content_hash(text)
        state = WorkflowState(row["state"])
        target = state
        approved_hash = row["approved_hash"]
        if approved_hash and digest != approved_hash:
            target = WorkflowState.REVIEW_REQUIRED
            approved_hash = None
        now = utc_now()
        with self.store.connect() as con:
            con.execute(
                "UPDATE workflows SET content_hash=?,approved_hash=?,state=?,updated_at=? WHERE id=?",
                (digest, approved_hash, target.value, now, workflow_id),
            )
            if target != state:
                con.execute(
                    "INSERT INTO workflow_transitions(workflow_id,from_state,to_state,at,reason) VALUES(?,?,?,?,?)",
                    (workflow_id, state.value, target.value, now, "content changed after approval"),
                )
        return self.get(workflow_id)

    def edit_draft(self, workflow_id: str, *, field: str, value: str, edited_by: str) -> dict:
        row = self.get(workflow_id)
        state = WorkflowState(row["state"])
        if state not in _REVIEW_STATES:
            raise ValueError("Drafts may only be edited while the workflow is in review")
        field = field.strip()
        if not field:
            raise ValueError("Draft field is required")
        metadata = _metadata(row)
        drafts = metadata.setdefault("drafts", {})
        if not isinstance(drafts, dict):
            drafts = {}
            metadata["drafts"] = drafts
        old_text = str(drafts.get(field, ""))
        drafts[field] = value
        metadata["factual_recheck_required"] = True
        metadata["last_edited_field"] = field
        now = utc_now()
        # Any human edit can change a factual claim. Move back to DRAFTED so the
        # existing factual validation path must run again before human approval.
        with self.store.connect() as con:
            con.execute(
                "UPDATE workflows "
                "SET state=?,approved_hash=NULL,content_hash=?,metadata_json=?,updated_at=? "
                "WHERE id=?",
                (WorkflowState.DRAFTED.value, content_hash(value), self.store.dumps(metadata), now, workflow_id),
            )
            con.execute(
                "INSERT INTO workflow_edits("
                "workflow_id,field,old_text,new_text,edited_by,at,factual_recheck_required"
                ") VALUES(?,?,?,?,?,?,1)",
                (workflow_id, field, old_text, value, edited_by, now),
            )
            con.execute(
                "INSERT INTO workflow_transitions(workflow_id,from_state,to_state,at,reason) VALUES(?,?,?,?,?)",
                (
                    workflow_id,
                    state.value,
                    WorkflowState.DRAFTED.value,
                    now,
                    f"draft field edited: {field}; factual recheck required",
                ),
            )
        return self.get(workflow_id)

    def edits(self, workflow_id: str) -> list[dict]:
        with self.store.connect() as con:
            rows = con.execute(
                "SELECT * FROM workflow_edits WHERE workflow_id=? ORDER BY id", (workflow_id,)
            ).fetchall()
        return [dict(row) for row in rows]

    def review_queue(
        self,
        *,
        book: str = "",
        platform: str = "",
        min_age_days: int | None = None,
        max_age_days: int | None = None,
        sort_by: str = "age",
    ) -> list[dict]:
        now = datetime.now(timezone.utc)
        with self.store.connect() as con:
            rows = con.execute(
                "SELECT w.*, "
                "(SELECT MAX(t.at) FROM workflow_transitions t "
                "WHERE t.workflow_id=w.id "
                "AND t.to_state IN ('REVIEW_REQUIRED','IN_REVIEW')) AS review_started_at "
                "FROM workflows w "
                "WHERE w.state IN ('REVIEW_REQUIRED','IN_REVIEW')"
            ).fetchall()
        items: list[dict] = []
        for raw in rows:
            row = dict(raw)
            if book and book.lower() not in row["book"].lower():
                continue
            if platform and row["platform"] != platform:
                continue
            started_raw = row.get("review_started_at") or row["updated_at"] or row["created_at"]
            started = datetime.fromisoformat(started_raw)
            if started.tzinfo is None:
                started = started.replace(tzinfo=timezone.utc)
            age_days = max(0, (now - started.astimezone(timezone.utc)).days)
            if min_age_days is not None and age_days < min_age_days:
                continue
            if max_age_days is not None and age_days > max_age_days:
                continue
            metadata = _metadata(row)
            items.append(
                {
                    "id": row["id"],
                    "book": row["book"],
                    "platform": row["platform"],
                    "post_role": _role_from_metadata(metadata),
                    "age_days": age_days,
                    "review_started_at": started_raw,
                }
            )
        keys = {
            "age": lambda item: (-item["age_days"], item["id"]),
            "book": lambda item: (item["book"].lower(), -item["age_days"]),
            "platform": lambda item: (item["platform"], -item["age_days"]),
        }
        if sort_by not in keys:
            raise ValueError("Queue sort must be age, book, or platform")
        return sorted(items, key=keys[sort_by])

    def stale_reviews(self, max_age_days: int) -> list[dict]:
        if max_age_days < 1:
            raise ValueError("stale review threshold must be at least 1 day")
        return self.review_queue(min_age_days=max_age_days, sort_by="age")

    def history(self, workflow_id: str) -> list[dict]:
        with self.store.connect() as con:
            rows = con.execute(
                "SELECT * FROM workflow_transitions WHERE workflow_id=? ORDER BY id", (workflow_id,)
            ).fetchall()
        return [dict(row) for row in rows]

    def register_publish_attempt(
        self, workflow_id: str, *, provider: str, platform: str, idempotency_key: str, payload: dict
    ) -> bool:
        payload_hash = hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
        now = utc_now()
        try:
            with self.store.connect() as con:
                con.execute(
                    "INSERT INTO publish_attempts("
                    "workflow_id,idempotency_key,provider,platform,status,"
                    "payload_hash,payload_json,attempted_at"
                    ") VALUES(?,?,?,?,?,?,?,?)",
                    (
                        workflow_id,
                        idempotency_key,
                        provider,
                        platform,
                        "started",
                        payload_hash,
                        self.store.dumps(payload),
                        now,
                    ),
                )
            return True
        except Exception as exc:
            if "UNIQUE constraint failed" in str(exc):
                return False
            raise
