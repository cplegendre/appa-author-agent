from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

@dataclass(frozen=True)
class OrchestrationDeps:
    root: Path
    settings: dict[str, Any]
    rag_store: Callable[[], Any]
    analyze_book: Callable[[Path], dict]
    generate_json: Callable[..., dict]
    render: Callable[..., str]
    prepare_website_update: Callable[..., dict]
    duplicate_report: Callable[[Any, str, str], dict]
    rag_context: Callable[..., list[dict]]
    style_examples: Callable[..., dict[str, list[dict]]]
    brand_voice: dict[str, Any]
    user_output: Callable[[Any], None]
    book_evidence: Callable[..., list[dict[str, Any]]] = lambda *args, **kwargs: []
    factual_review_json: Callable[..., dict] | None = None
    release_cmd: Callable[..., tuple[dict, Path]] | None = None
    evergreen_cmd: Callable[..., tuple[dict, Path]] | None = None
