from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from author_agent.persistence import AutomationStore


class VisionProvider(Protocol):
    def analyze(self, image_bytes: bytes, *, page: int, text: str) -> list[dict]: ...


@dataclass(frozen=True)
class PageEvidence:
    page: int
    text_evidence: list[str]
    visual_evidence: list[dict]
    provenance: str = "page"


class MultimodalBookAnalyzer:
    def __init__(self, store: AutomationStore, provider: VisionProvider | None = None):
        self.store = store
        self.provider = provider

    @staticmethod
    def _hash(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    def analyze_pdf(
        self,
        path: Path,
        *,
        enabled: bool = True,
        max_pages: int = 0,
    ) -> list[PageEvidence]:
        from pypdf import PdfReader

        raw = path.read_bytes()
        book_hash = self._hash(raw)
        reader = PdfReader(path)
        limit = len(reader.pages) if max_pages <= 0 else min(len(reader.pages), max_pages)
        results: list[PageEvidence] = []
        fitz_doc = None
        if enabled and self.provider is not None:
            try:
                import fitz

                fitz_doc = fitz.open(path)
            except ImportError:
                fitz_doc = None
        try:
            for idx in range(limit):
                text = reader.pages[idx].extract_text() or ""
                visual: list[dict] = []
                page_hash = self._hash(text.encode("utf-8"))
                image_bytes = b""
                if fitz_doc is not None:
                    pixmap = fitz_doc[idx].get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
                    image_bytes = pixmap.tobytes("png")
                    page_hash = self._hash(image_bytes + text.encode("utf-8"))
                with self.store.connect() as con:
                    cached = con.execute(
                        "SELECT * FROM visual_evidence WHERE book_hash=? AND page=? AND page_hash=?",
                        (book_hash, idx + 1, page_hash),
                    ).fetchone()
                if cached:
                    visual = json.loads(cached["visual_evidence_json"])
                elif enabled and self.provider is not None and image_bytes:
                    visual = self.provider.analyze(image_bytes, page=idx + 1, text=text)
                    with self.store.connect() as con:
                        con.execute(
                            "INSERT OR REPLACE INTO visual_evidence("
                            "book_hash,page,page_hash,text_evidence_json,visual_evidence_json,analyzed_at"
                            ") VALUES(?,?,?,?,?,?)",
                            (
                                book_hash,
                                idx + 1,
                                page_hash,
                                self.store.dumps([text] if text.strip() else []),
                                self.store.dumps(visual),
                                datetime.now(timezone.utc).isoformat(),
                            ),
                        )
                results.append(
                    PageEvidence(
                        page=idx + 1,
                        text_evidence=[text] if text.strip() else [],
                        visual_evidence=visual,
                    )
                )
        finally:
            if fitz_doc is not None:
                fitz_doc.close()
        return results

    @staticmethod
    def serializable(items: list[PageEvidence]) -> list[dict]:
        return [asdict(item) for item in items]


class OllamaVisionProvider:
    """Local vision adapter. Observations are evidence only, never generated marketing copy."""

    def __init__(self, base_url: str, model: str, timeout_seconds: int = 240):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout_seconds = timeout_seconds

    def analyze(self, image_bytes: bytes, *, page: int, text: str) -> list[dict]:
        import base64

        import requests

        prompt = (
            "Describe only directly visible, marketing-relevant facts on this illustrated book page. "
            "Do not infer plot events, emotions, names, colors, or relationships unless directly visible "
            "or present in page text. Return JSON only: "
            '{"observations":[{"claim":str,"confidence":0..1,"source":"vision"}]}. '
            f"Page number: {page}. Extracted page text: {text[:4000]}"
        )
        response = requests.post(
            f"{self.base_url}/api/generate",
            json={
                "model": self.model,
                "prompt": prompt,
                "images": [base64.b64encode(image_bytes).decode("ascii")],
                "stream": False,
                "format": "json",
            },
            timeout=self.timeout_seconds,
        )
        response.raise_for_status()
        raw = response.json().get("response", "{}")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            return []
        observations = data.get("observations", [])
        return [
            item | {"source": "vision"}
            for item in observations
            if isinstance(item, dict) and str(item.get("claim", "")).strip()
        ]
