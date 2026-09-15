from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

SCHEMA_VERSION = 27


class AutomationStore:
    """Small durable SQLite store for workflow, publishing, vision, and analytics."""

    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.migrate()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        try:
            with con:
                yield con
        finally:
            con.close()

    def migrate(self) -> None:
        with self.connect() as con:
            con.execute("CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS workflows (
                    id TEXT PRIMARY KEY,
                    book TEXT NOT NULL DEFAULT '', campaign TEXT NOT NULL DEFAULT '', platform TEXT NOT NULL DEFAULT '',
                    state TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    scheduled_at TEXT, published_at TEXT, external_id TEXT, social_url TEXT,
                    content_hash TEXT NOT NULL DEFAULT '', approved_hash TEXT, retry_count INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT, metadata_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE TABLE IF NOT EXISTS workflow_transitions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, workflow_id TEXT NOT NULL, from_state TEXT,
                    to_state TEXT NOT NULL, at TEXT NOT NULL, reason TEXT NOT NULL DEFAULT '',
                    FOREIGN KEY(workflow_id) REFERENCES workflows(id)
                );
                CREATE TABLE IF NOT EXISTS workflow_edits (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, workflow_id TEXT NOT NULL, field TEXT NOT NULL,
                    old_text TEXT NOT NULL DEFAULT '', new_text TEXT NOT NULL, edited_by TEXT NOT NULL,
                    at TEXT NOT NULL, factual_recheck_required INTEGER NOT NULL DEFAULT 1,
                    FOREIGN KEY(workflow_id) REFERENCES workflows(id)
                );
                CREATE TABLE IF NOT EXISTS publish_attempts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    workflow_id TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL UNIQUE,
                    provider TEXT NOT NULL, platform TEXT NOT NULL, status TEXT NOT NULL, external_id TEXT,
                    payload_hash TEXT NOT NULL, payload_json TEXT NOT NULL DEFAULT '{}',
                    attempted_at TEXT NOT NULL, response_json TEXT NOT NULL DEFAULT '{}'
                );
                CREATE TABLE IF NOT EXISTS visual_evidence (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, book_hash TEXT NOT NULL, page INTEGER NOT NULL,
                    page_hash TEXT NOT NULL, text_evidence_json TEXT NOT NULL DEFAULT '[]',
                    visual_evidence_json TEXT NOT NULL DEFAULT '[]', analyzed_at TEXT NOT NULL,
                    UNIQUE(book_hash, page, page_hash)
                );
                CREATE TABLE IF NOT EXISTS metric_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, workflow_id TEXT NOT NULL, measured_at TEXT NOT NULL,
                    metrics_json TEXT NOT NULL, score REAL NOT NULL DEFAULT 0.0
                );
                CREATE TABLE IF NOT EXISTS post_features (
                    workflow_id TEXT PRIMARY KEY, features_json TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS campaigns (
                    id TEXT PRIMARY KEY, book TEXT NOT NULL, release_date TEXT NOT NULL,
                    timezone TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'PLANNED', created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS campaign_slots (
                    id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, platform TEXT NOT NULL, kind TEXT NOT NULL,
                    goal TEXT NOT NULL, cta TEXT NOT NULL, scheduled_at TEXT NOT NULL,
                    experiment_json TEXT NOT NULL DEFAULT '{}', status TEXT NOT NULL DEFAULT 'PLANNED',
                    workflow_id TEXT, FOREIGN KEY(campaign_id) REFERENCES campaigns(id)
                );
                """
            )
            con.execute(
                "INSERT INTO schema_meta(key,value) VALUES('schema_version',?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (str(SCHEMA_VERSION),),
            )

    def schema_version(self) -> int:
        with self.connect() as con:
            row = con.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()
        return int(row["value"]) if row else 0

    @staticmethod
    def dumps(value: object) -> str:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
