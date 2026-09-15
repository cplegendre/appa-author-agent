from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from .errors import ValidationError


@dataclass(frozen=True)
class BookPassage:
    index: int
    text: str
    page: int | None = None


_EMBED_CACHE: dict[tuple[str, int, int, str, int], list[float]] = {}


def _split_text(text: str, *, max_chars: int = 1800) -> list[str]:
    paragraphs = [part.strip() for part in text.replace("\r\n", "\n").split("\n\n") if part.strip()]
    if not paragraphs:
        paragraphs = [line.strip() for line in text.splitlines() if line.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if current and len(current) + len(paragraph) + 2 > max_chars:
            chunks.append(current)
            current = ""
        if len(paragraph) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            for start in range(0, len(paragraph), max_chars):
                piece = paragraph[start : start + max_chars].strip()
                if piece:
                    chunks.append(piece)
            continue
        current = f"{current}\n\n{paragraph}".strip() if current else paragraph
    if current:
        chunks.append(current)
    return chunks


def extract_book_passages(path: Path) -> list[BookPassage]:
    if not path.is_file():
        raise ValidationError(f"Book file not found: {path}")
    passages: list[BookPassage] = []
    if path.suffix.lower() == ".pdf":
        reader = PdfReader(str(path))
        index = 0
        for page_number, page in enumerate(reader.pages, start=1):
            text = (page.extract_text() or "").strip()
            for chunk in _split_text(text):
                passages.append(BookPassage(index=index, page=page_number, text=chunk))
                index += 1
        return passages

    text = path.read_text(encoding="utf-8")
    for index, chunk in enumerate(_split_text(text)):
        passages.append(BookPassage(index=index, page=None, text=chunk))
    return passages


def retrieve_book_evidence(store: Any, path: Path, query: str, *, top_k: int = 10) -> list[dict[str, Any]]:
    """Retrieve semantically relevant passages from the *current book* without persisting them.

    Historical social RAG remains separate. Passage embeddings are cached in-process so the first
    review pays the embedding cost, while subsequent retries/regenerations reuse the vectors.
    """
    query = query.strip()
    if not query:
        return []
    embed = getattr(store, "embed", None)
    cosine = getattr(store, "_cosine", None)
    if not callable(embed) or not callable(cosine):
        return []

    passages = extract_book_passages(path)
    if not passages:
        return []
    stat = path.stat()
    model = str(getattr(store, "embedding_model", ""))
    resolved = str(path.resolve())
    query_vector = embed(query)
    ranked: list[tuple[float, BookPassage]] = []
    for passage in passages:
        cache_key = (resolved, stat.st_mtime_ns, stat.st_size, model, passage.index)
        vector = _EMBED_CACHE.get(cache_key)
        if vector is None:
            vector = embed(passage.text)
            _EMBED_CACHE[cache_key] = vector
        score = float(cosine(query_vector, vector))
        ranked.append((score, passage))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [
        {
            "page": passage.page,
            "passage_index": passage.index,
            "score": round(score, 4),
            "text": passage.text,
        }
        for score, passage in ranked[: max(1, top_k)]
    ]
