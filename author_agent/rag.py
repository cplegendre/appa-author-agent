from __future__ import annotations

import csv
import json
import math
import sqlite3
import time
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from .errors import RagError, ValidationError
from .ollama_client import OllamaError, post_json


@dataclass
class RagHit:
    id: int
    kind: str
    source: str
    external_id: str
    title: str
    text: str
    date: str
    platform: str
    topic: str
    score: float
    metadata: dict


class RagStore:
    def __init__(self, db_path: Path, base_url: str, embedding_model: str, timeout: int = 240):
        self.db_path = db_path
        self.base_url = base_url.rstrip("/")
        self.embedding_model = embedding_model
        self.timeout = timeout
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self):
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        return con

    @contextmanager
    def _connection(self):
        """Transactional SQLite connection that is always closed."""
        con = self._connect()
        try:
            with con:
                yield con
        except sqlite3.Error as exc:
            raise RagError(f"SQLite RAG operation failed for {self.db_path}: {exc}") from exc
        finally:
            con.close()

    def _init_db(self):
        with self._connection() as con:
            con.execute("""
                CREATE TABLE IF NOT EXISTS documents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    kind TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT '',
                    external_id TEXT NOT NULL DEFAULT '',
                    title TEXT NOT NULL DEFAULT '',
                    text TEXT NOT NULL,
                    date TEXT NOT NULL DEFAULT '',
                    platform TEXT NOT NULL DEFAULT '',
                    topic TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    embedding_json TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                )
            """)
            con.execute("""
                CREATE UNIQUE INDEX IF NOT EXISTS idx_documents_unique
                ON documents(kind, source, external_id)
                WHERE external_id <> ''
            """)
            con.execute("CREATE INDEX IF NOT EXISTS idx_documents_kind ON documents(kind)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_documents_date ON documents(date)")
            con.execute("CREATE INDEX IF NOT EXISTS idx_documents_platform ON documents(platform)")

    def embed(self, text: str) -> list[float]:
        text = text.strip()
        if not text:
            raise ValidationError("Cannot embed empty text")
        response = post_json(
            self.base_url,
            "/api/embed",
            {"model": self.embedding_model, "input": text},
            timeout=self.timeout,
        )
        if response.status_code == 404:
            response = post_json(
                self.base_url,
                "/api/embeddings",
                {"model": self.embedding_model, "prompt": text},
                timeout=self.timeout,
            )
        if response.status_code == 404:
            raise OllamaError(
                f"Ollama embedding endpoint was not found at {self.base_url}. "
                "Update Ollama if needed, then run `ollama serve`."
            )
        payload = response.json()
        if payload.get("embeddings"):
            return payload["embeddings"][0]
        if payload.get("embedding"):
            return payload["embedding"]
        raise OllamaError(f"Unexpected Ollama embedding response: {sorted(payload.keys())}")

    def upsert(
        self,
        *,
        kind: str,
        text: str,
        source: str = "",
        external_id: str = "",
        title: str = "",
        date: str = "",
        platform: str = "",
        topic: str = "",
        metadata: dict | None = None,
    ) -> int:
        clean = " ".join(text.split())
        if not clean:
            raise ValidationError("Document text is empty")
        emb = self.embed(clean)
        metadata = metadata or {}
        now = int(time.time())
        with self._connection() as con:
            if external_id:
                row = con.execute(
                    "SELECT id FROM documents WHERE kind=? AND source=? AND external_id=?",
                    (kind, source, external_id),
                ).fetchone()
                if row:
                    con.execute(
                        """
                        UPDATE documents SET title=?, text=?, date=?, platform=?, topic=?,
                        metadata_json=?, embedding_json=?, created_at=? WHERE id=?
                    """,
                        (
                            title,
                            clean,
                            date,
                            platform,
                            topic,
                            json.dumps(metadata, ensure_ascii=False),
                            json.dumps(emb),
                            now,
                            row["id"],
                        ),
                    )
                    return int(row["id"])
            cur = con.execute(
                """
                INSERT INTO documents
                (kind, source, external_id, title, text, date, platform, topic,
                 metadata_json, embedding_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    kind,
                    source,
                    external_id,
                    title,
                    clean,
                    date,
                    platform,
                    topic,
                    json.dumps(metadata, ensure_ascii=False),
                    json.dumps(emb),
                    now,
                ),
            )
            if cur.lastrowid is None:
                raise RagError("SQLite did not return an id for the inserted RAG document.")
            return int(cur.lastrowid)

    @staticmethod
    def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
        if len(a) != len(b):
            return -1.0
        dot = sum(x * y for x, y in zip(a, b))
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(y * y for y in b))
        if not na or not nb:
            return -1.0
        return dot / (na * nb)

    def search(
        self, query: str, *, top_k: int = 8, kinds: Sequence[str] | None = None, platforms: Sequence[str] | None = None
    ) -> list[RagHit]:
        q = self.embed(query)
        sql = "SELECT * FROM documents WHERE 1=1"
        params: list[str] = []
        if kinds:
            sql += " AND kind IN (" + ",".join("?" for _ in kinds) + ")"
            params.extend(kinds)
        if platforms:
            sql += " AND platform IN (" + ",".join("?" for _ in platforms) + ")"
            params.extend(platforms)
        with self._connection() as con:
            rows = con.execute(sql, params).fetchall()
        hits = []
        for row in rows:
            score = self._cosine(q, json.loads(row["embedding_json"]))
            hits.append(
                RagHit(
                    id=row["id"],
                    kind=row["kind"],
                    source=row["source"],
                    external_id=row["external_id"],
                    title=row["title"],
                    text=row["text"],
                    date=row["date"],
                    platform=row["platform"],
                    topic=row["topic"],
                    score=score,
                    metadata=json.loads(row["metadata_json"] or "{}"),
                )
            )
        hits.sort(key=lambda h: h.score, reverse=True)
        return hits[:top_k]

    def stats(self) -> dict:
        with self._connection() as con:
            total_row = con.execute("SELECT COUNT(*) c FROM documents").fetchone()
            total = int(total_row["c"]) if total_row is not None else 0
            by_kind = {
                r["kind"]: r["c"]
                for r in con.execute("SELECT kind, COUNT(*) c FROM documents GROUP BY kind ORDER BY kind")
            }
            by_platform = {
                r["platform"] or "n/a": r["c"]
                for r in con.execute("SELECT platform, COUNT(*) c FROM documents GROUP BY platform ORDER BY platform")
            }
        return {"total": total, "by_kind": by_kind, "by_platform": by_platform}

    def recent_posts(self) -> list[dict]:
        with self._connection() as con:
            rows = con.execute(
                "SELECT date, platform, topic, source, text, metadata_json FROM documents "
                "WHERE kind='post' ORDER BY date DESC, id DESC"
            ).fetchall()
        return [dict(r) | {"metadata": json.loads(r["metadata_json"] or "{}")} for r in rows]


def hit_to_dict(hit: RagHit) -> dict:
    return {
        "id": hit.id,
        "kind": hit.kind,
        "source": hit.source,
        "external_id": hit.external_id,
        "title": hit.title,
        "text": hit.text,
        "date": hit.date,
        "platform": hit.platform,
        "topic": hit.topic,
        "score": round(hit.score, 4),
        "metadata": hit.metadata,
    }


def load_posts_file(path: Path) -> list[dict]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as f:
            return list(csv.DictReader(f))
    if suffix == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return data
        for key in ("posts", "data", "items"):
            if isinstance(data.get(key), list):
                return data[key]
        raise ValidationError("JSON must be a list or contain posts/data/items list")
    if suffix in {".txt", ".md"}:
        return [{"text": path.read_text(encoding="utf-8"), "source": path.name}]
    raise ValidationError(f"Unsupported posts file: {path.suffix}")


def _iso_from_timestamp(value) -> str:
    if value in (None, ""):
        return ""
    if isinstance(value, (int, float)) or (isinstance(value, str) and value.isdigit()):
        return datetime.fromtimestamp(int(value), tz=timezone.utc).date().isoformat()
    return str(value)


def _extract_meta_text(value) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts = [_extract_meta_text(v) for v in value]
        return "\n".join(p for p in parts if p)
    if isinstance(value, dict):
        for key in ("post", "text", "title", "description", "value"):
            if key in value:
                got = _extract_meta_text(value[key])
                if got:
                    return got
        if isinstance(value.get("data"), list):
            return _extract_meta_text(value["data"])
    return ""


def parse_meta_facebook(path: Path) -> list[dict]:
    """Parse Meta Facebook `your_posts_1.json`-style exports defensively."""
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    rows = (
        data
        if isinstance(data, list)
        else next((data[k] for k in ("posts_v2", "your_posts", "posts") if isinstance(data.get(k), list)), [])
    )
    result = []
    for idx, row in enumerate(rows):
        text = _extract_meta_text(row.get("data", row))
        if not text:
            text = _extract_meta_text(row.get("title", ""))
        result.append(
            {
                "text": text,
                "date": _iso_from_timestamp(row.get("timestamp", row.get("creation_timestamp", ""))),
                "platform": "facebook",
                "external_id": str(row.get("id", row.get("uri", idx))),
                "source": path.name,
                "metadata": row,
            }
        )
    return [r for r in result if r["text"].strip()]


def parse_meta_instagram(path: Path) -> list[dict]:
    """Parse Meta Instagram `posts_1.json` / media exports defensively."""
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    rows = (
        data
        if isinstance(data, list)
        else next((data[k] for k in ("ig_posts", "posts", "media") if isinstance(data.get(k), list)), [])
    )
    result = []
    for idx, row in enumerate(rows):
        media = row.get("media", [])
        captions = []
        timestamps = []
        if isinstance(media, list):
            for item in media:
                captions.append(_extract_meta_text(item.get("title", item.get("caption", ""))))
                if item.get("creation_timestamp"):
                    timestamps.append(item["creation_timestamp"])
        text = "\n".join(c for c in captions if c) or _extract_meta_text(row)
        ts = row.get("creation_timestamp") or row.get("timestamp") or (timestamps[0] if timestamps else "")
        result.append(
            {
                "text": text,
                "date": _iso_from_timestamp(ts),
                "platform": "instagram",
                "external_id": str(row.get("id", row.get("uri", idx))),
                "source": path.name,
                "metadata": row,
            }
        )
    return [r for r in result if r["text"].strip()]


def normalize_post(row: dict, default_platform: str = "") -> dict:
    def first(*keys):
        for key in keys:
            value = row.get(key)
            if value not in (None, ""):
                return str(value)
        return ""

    return {
        "text": first("text", "message", "caption", "content", "post_text", "description"),
        "date": first("date", "created_time", "timestamp", "published_at", "time"),
        "platform": first("platform") or default_platform,
        "external_id": first("id", "post_id", "external_id", "uri"),
        "topic": first("topic", "category"),
        "source": first("source"),
        "metadata": row.get("metadata", row),
    }
