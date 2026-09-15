from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Callable


def make_rag_store(root: Path, rag_cfg: dict[str, Any], ollama: dict[str, Any], rag_store_cls: type) -> Any:
    return rag_store_cls(
        root / rag_cfg.get("db_path", "data/rag.sqlite3"),
        ollama["base_url"],
        ollama.get("embedding_model", "embeddinggemma:latest"),
        ollama.get("timeout_seconds", 240),
    )


def analyze_book_file(
    book_path: Path,
    *,
    read_text: Callable[[Path], str],
    generate: Callable[..., dict],
    render: Callable[..., str],
    ollama: dict[str, Any],
) -> dict:
    text = read_text(book_path)
    return generate(
        ollama["base_url"],
        ollama["marketing_model"],
        render("analyze_book.txt", BOOK_TEXT=text[:70000]),
        ollama.get("timeout_seconds", 240),
    )


def rag_context(
    store: Any, query: str, rag_cfg: dict[str, Any], hit_to_dict: Callable[[Any], dict], top_k: int | None = None
) -> list[dict]:
    limit = top_k or int(rag_cfg.get("top_k", 8))
    return [hit_to_dict(hit) for hit in store.search(query, top_k=limit)]


def sanitize_style_text(text: str) -> str:
    sanitized = re.sub("https?://\\S+", "[RELEASE_URL]", text)
    lines = sanitized.splitlines()
    historical_title = ""
    historical_series = ""
    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith("📚"):
            candidate = stripped[1:].strip().strip("*_ ")
            if candidate:
                historical_title = candidate
                lines[index] = "📚 [BOOK_TITLE]"
            if index + 1 < len(lines):
                following = lines[index + 1].strip().strip("*_ ")
                match = re.match("(.+?)\\s*[·•-]\\s*Book\\s+\\d+(?:\\s+of\\s+\\d+)?\\b", following, re.I)
                if match:
                    historical_series = match.group(1).strip()
    sanitized = "\n".join(lines)
    if historical_title:
        sanitized = sanitized.replace(historical_title, "[BOOK_TITLE]")
    if historical_series:
        sanitized = sanitized.replace(historical_series, "[SERIES_NAME]")
    sanitized = re.sub(
        "\\bBook\\s+\\d+\\s+of\\s+\\d+\\b", "Book [BOOK_NUMBER] of [SERIES_TOTAL]", sanitized, flags=re.I
    )
    return re.sub("\\bBook\\s+\\d+\\b", "Book [BOOK_NUMBER]", sanitized, flags=re.I)


def style_examples(
    store: Any, query: str, brand_voice: dict[str, Any], *, platforms: tuple[str, ...] = ("facebook", "instagram")
) -> dict[str, list[dict]]:
    limit = int(brand_voice.get("style_examples_per_platform", 3))
    if limit <= 0:
        return {platform: [] for platform in platforms}
    examples: dict[str, list[dict]] = {}
    for platform in platforms:
        hits = store.search(query, top_k=limit, kinds=["post"], platforms=[platform])
        examples[platform] = [
            {
                "platform": hit.platform,
                "date": hit.date,
                "text": sanitize_style_text(hit.text),
                "score": round(hit.score, 4),
            }
            for hit in hits
        ]
    return examples


def duplicate_report(
    store: Any,
    post_text: str,
    platform: str,
    *,
    rag_cfg: dict[str, Any],
    ollama: dict[str, Any],
    generate: Callable[..., dict],
    render: Callable[..., str],
    hit_to_dict: Callable[[Any], dict],
) -> dict:
    if not post_text.strip():
        return {"max_similarity": None, "warning": False, "hits": [], "llm_review": None}
    hits = store.search(post_text, top_k=5, kinds=["post"], platforms=[platform])
    if not hits:
        return {"max_similarity": None, "warning": False, "hits": [], "llm_review": None}
    threshold = float(rag_cfg.get("duplicate_threshold", 0.86))
    warning_threshold = float(rag_cfg.get("warning_threshold", 0.78))
    max_score = hits[0].score
    review = None
    if max_score >= warning_threshold:
        review = generate(
            ollama["base_url"],
            ollama.get("review_model", ollama["marketing_model"]),
            render(
                "review_similarity.txt", PROPOSED_POST=post_text, SIMILAR_HISTORY=[hit_to_dict(hit) for hit in hits]
            ),
            ollama.get("timeout_seconds", 240),
        )
    return {
        "max_similarity": round(max_score, 4),
        "warning": max_score >= threshold or bool(review and review.get("redundant")),
        "hits": [hit_to_dict(hit) for hit in hits],
        "llm_review": review,
    }
