from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .errors import ValidationError
from .orchestration_types import OrchestrationDeps

LOG = logging.getLogger(__name__)


def _factual_rejections(review: dict[str, Any]) -> list[dict[str, str]]:
    rejected: list[dict[str, str]] = []
    claims = review.get("claims")
    if isinstance(claims, list):
        for item in claims:
            if not isinstance(item, dict):
                continue
            status = str(item.get("status", "")).strip().lower()
            if status not in {"unsupported", "contradicted"}:
                continue
            text = str(item.get("text", "")).strip()
            if not text:
                continue
            rejected.append(
                {
                    "text": text,
                    "status": status,
                    "evidence": str(item.get("evidence", "")).strip(),
                    "reason": str(item.get("reason", "")).strip(),
                }
            )
    if rejected:
        return rejected

    # Backward compatibility with older review-model responses.
    unsupported = review.get("unsupported_claims")
    if isinstance(unsupported, list):
        for item in unsupported:
            text = str(item).strip()
            if text:
                rejected.append({"text": text, "status": "unsupported", "evidence": "", "reason": ""})
    return rejected


class FactualGroundingError(ValidationError):
    def __init__(self, rejected: list[dict[str, str]], evidence: list[dict[str, Any]]):
        self.rejected = rejected
        self.evidence = evidence
        summary = []
        for item in rejected[:5]:
            label = item.get("status", "unsupported")
            reason = item.get("reason", "")
            text = item.get("text", "")
            summary.append(f"{label}: {text}" + (f" ({reason})" if reason else ""))
        super().__init__("Factual-grounding review found unsupported story detail(s): " + "; ".join(summary))

    def corrective_prompt(self) -> str:
        lines = [
            "FACTUAL CORRECTION REQUIRED.",
            "Rewrite only what is necessary to remove the rejected claims. Preserve supported claims and the",
            "overall platform structure. Do NOT replace a rejected detail with a different invented detail.",
            "A faithful paraphrase or clear entailment of verified evidence is allowed.",
            "",
            "REJECTED CLAIMS:",
        ]
        for index, item in enumerate(self.rejected, start=1):
            lines.append(f"{index}. [{item.get('status', 'unsupported')}] {item.get('text', '')}")
            if item.get("reason"):
                lines.append(f"   Reason: {item['reason']}")
            if item.get("evidence"):
                lines.append(f"   Evidence: {item['evidence']}")
        lines.extend(
            [
                "",
                "VERIFIED BOOK PASSAGES YOU MAY USE:",
            ]
        )
        for item in self.evidence[:12]:
            page = item.get("page")
            prefix = f"[page {page}]" if page else "[book passage]"
            lines.append(f"{prefix} {item.get('text', '')}")
        lines.extend(
            [
                "",
                "Do not add new actions, gestures, sensory descriptions, chronology, thoughts, emotions,",
                "motives, or setting details unless one of the verified passages explicitly supports them.",
            ]
        )
        return "\n".join(lines)


def _validate_factual_grounding(
    deps: OrchestrationDeps,
    ollama: dict[str, Any],
    profile: dict[str, Any],
    drafts: dict[str, Any],
    *,
    book_path: Path | None = None,
) -> None:
    if not bool(deps.brand_voice.get("factual_review_enabled", False)):
        return
    draft_subset = {key: drafts.get(key, "") for key in ("facebook", "instagram", "teaser") if key in drafts}
    evidence: list[dict[str, Any]] = []
    if book_path is not None and book_path.is_file():
        query = "\n\n".join(str(value) for value in draft_subset.values() if str(value).strip())
        try:
            store = deps.rag_store()
            evidence = deps.book_evidence(store, book_path, query, top_k=12)
        except Exception as exc:  # factual review can still fall back to the profile if retrieval fails
            LOG.warning("book_evidence_retrieval_failed", extra={"error": str(exc), "book": str(book_path)})

    review_fn = deps.factual_review_json or deps.generate_json
    review = review_fn(
        ollama["base_url"],
        ollama.get("review_model", ollama["marketing_model"]),
        deps.render(
            "factual_review.txt",
            BOOK_PROFILE=profile,
            BOOK_EVIDENCE=evidence,
            DRAFTS=draft_subset,
        ),
        ollama.get("timeout_seconds", 240),
    )
    if not isinstance(review, dict):
        LOG.warning("factual_review_unexpected_type", extra={"review_type": type(review).__name__})
        return
    rejected = _factual_rejections(review)
    if rejected:
        raise FactualGroundingError(rejected, evidence)
    if review.get("supported") is False:
        LOG.warning("factual_review_unstructured_rejection", extra={"review_keys": sorted(review)})


def _cross_draft_similarity(
    store: Any,
    drafts: dict[str, str],
    warning_threshold: float,
) -> dict[str, Any]:
    """Compare newly generated drafts with each other, independent of historical RAG."""
    embed = getattr(store, "embed", None)
    cosine = getattr(store, "_cosine", None)
    if not callable(embed) or not callable(cosine):
        return {"available": False, "warning": False, "pairs": []}
    vectors: dict[str, list[float]] = {}
    for field, text in drafts.items():
        if isinstance(text, str) and text.strip():
            vectors[field] = embed(text)
    pairs: list[dict[str, Any]] = []
    fields = list(vectors)
    for index, left in enumerate(fields):
        for right in fields[index + 1 :]:
            score = float(cosine(vectors[left], vectors[right]))
            pairs.append(
                {
                    "left": left,
                    "right": right,
                    "similarity": round(score, 4),
                    "warning": score >= warning_threshold,
                }
            )
    return {
        "available": True,
        "warning": any(pair["warning"] for pair in pairs),
        "threshold": warning_threshold,
        "pairs": pairs,
    }
