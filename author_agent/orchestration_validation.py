from __future__ import annotations

import re
from typing import Any

from .errors import MarkdownFormattingError, ParagraphFormattingError, ValidationError

_SOCIAL_PARAGRAPH_WORD_THRESHOLD = 80
_MARKDOWN_HEADING_RE = re.compile(r"(?m)^\s{0,3}#{1,6}\s+")
_MARKDOWN_BULLET_RE = re.compile(r"(?m)^\s*[-*+]\s+")
_MARKDOWN_EMPHASIS_RE = re.compile(r"(?<!\w)(?:\*{1,3}[^*\n]+\*{1,3}|_{1,3}[^_\n]+_{1,3})(?!\w)")


def _strip_markdown_formatting(text: str) -> str:
    """Best-effort mechanical removal of Markdown emphasis/heading/bullet syntax.

    Only used as a last-resort fallback after corrective retries have already
    failed to stop the model from adding Markdown. Intentionally conservative:
    it strips the emphasis/heading/bullet *markers* only, never touches the
    words themselves, so `*Yok Helps a Friend*` becomes `Yok Helps a Friend`
    rather than being dropped or mangled.
    """

    def _strip_emphasis_match(match: re.Match[str]) -> str:
        return match.group(0).strip("*_")

    stripped = _MARKDOWN_EMPHASIS_RE.sub(_strip_emphasis_match, text)
    stripped = _MARKDOWN_HEADING_RE.sub("", stripped)
    stripped = _MARKDOWN_BULLET_RE.sub("", stripped)
    return stripped


_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'\u2018\u2019\u201c\u201d📚])")


def _insert_paragraph_breaks(text: str, *, sentences_per_paragraph: int = 3) -> str:
    """Conservative fallback: group sentences into paragraphs, never touching wording.

    Splits only at existing sentence-ending punctuation followed by whitespace and a
    capital letter/quote/emoji (never mid-sentence), then joins every N sentences with
    a blank line. If the text doesn't look like confidently splittable prose (e.g. no
    sentence boundaries found), it's returned unchanged rather than risking a bad break.
    """
    sentences = [s.strip() for s in _SENTENCE_SPLIT_RE.split(text.strip()) if s.strip()]
    if len(sentences) < 2:
        return text
    paragraphs = [
        " ".join(sentences[i : i + sentences_per_paragraph]) for i in range(0, len(sentences), sentences_per_paragraph)
    ]
    return "\n\n".join(paragraphs)


def _auto_fix_social_text(text: str) -> str:
    """Combined last-resort mechanical fix: strip Markdown, then ensure paragraph breaks.

    Order matters: stripping Markdown first means the paragraph splitter isn't thrown
    off by emphasis markers sitting at sentence boundaries.
    """
    fixed = _strip_markdown_formatting(text)
    words = re.findall(r"\b\w+[\u2019'-]?\w*\b", fixed, flags=re.UNICODE)
    if len(words) > _SOCIAL_PARAGRAPH_WORD_THRESHOLD and "\n\n" not in fixed:
        fixed = _insert_paragraph_breaks(fixed)
    return fixed


def _reject_social_formatting(
    field: str, text: str, *, paragraph_word_threshold: int = _SOCIAL_PARAGRAPH_WORD_THRESHOLD
) -> None:
    """Reject Markdown-ish social copy and long single-block prose.

    Facebook and Instagram render these drafts as plain text, so Markdown emphasis/headings
    leak literally. Instagram hashtags remain valid: only heading syntax such as ``# Title``
    is rejected. Short teaser copy may remain one paragraph; longer social copy must contain
    at least one blank-line paragraph separator.
    """
    markdown_match = (
        _MARKDOWN_EMPHASIS_RE.search(text) or _MARKDOWN_HEADING_RE.search(text) or _MARKDOWN_BULLET_RE.search(text)
    )
    if markdown_match:
        offending = markdown_match.group(0).strip()
        raise MarkdownFormattingError(
            f"{field.capitalize()} draft contains Markdown formatting. Social copy must be plain text: "
            "no emphasis markers, Markdown headings, or Markdown bullet lists. "
            f"Offending text: {offending!r}. Remove the Markdown markers and keep the words as-is. Retry generation."
        )
    words = re.findall(r"\b\w+[’'-]?\w*\b", text, flags=re.UNICODE)
    if len(words) > paragraph_word_threshold and "\n\n" not in text:
        raise ParagraphFormattingError(
            f"{field.capitalize()} draft is {len(words)} words but has no blank-line paragraph separator. "
            "Use multiple short paragraphs (2-3 sentences each) separated by a blank line (\\n\\n in the JSON "
            "string) and retry generation."
        )


_URL_RE = re.compile(r"https?://[^\s)\]>]+")
_HASHTAG_RE = re.compile(r"(?<!\w)#[A-Za-z0-9_]+")
_PLACEHOLDER_LEAK_RE = re.compile(r"[\[{<]{1,2}\s*RELEASE_URL\s*[\]}>]{1,2}", re.IGNORECASE)


def _urls_in(text: str) -> set[str]:
    return {match.rstrip(".,;:!?") for match in _URL_RE.findall(text)}


def _reject_leaked_placeholder(field: str, text: str) -> None:
    if _PLACEHOLDER_LEAK_RE.search(text):
        raise ValidationError(
            f"{field.capitalize()} draft leaked the raw RELEASE_URL placeholder token "
            "instead of the real URL (or omitting it, if unpublished). This is a "
            "model output bug, not a template rendering bug — retry generation."
        )


def _current_release_facts(
    profile: dict[str, Any], *, status: str, release_date: str, release_url: str
) -> dict[str, str]:
    """Return the only release metadata social copy is allowed to treat as authoritative."""
    return {
        "title": str(profile.get("title", "") or "").strip(),
        "series": str(profile.get("series", "") or "").strip(),
        "book_number": str(profile.get("book_number", "") or "").strip(),
        "series_total": str(profile.get("series_total", "") or "").strip(),
        "status": status,
        "release_date": release_date,
        "release_url": release_url.strip(),
    }


def _metadata_search_text(text: str) -> str:
    cleaned = re.sub(r"[*_`#]", "", text)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.casefold().strip()


def _validate_current_release_metadata(field: str, text: str, facts: dict[str, str]) -> None:
    """Reject historical/example metadata leaking into a current release draft."""
    if field not in {"facebook", "instagram"}:
        return
    searchable = _metadata_search_text(text)
    title = facts.get("title", "").strip()
    series = facts.get("series", "").strip()
    number = facts.get("book_number", "").strip()
    total = facts.get("series_total", "").strip()

    if title and _metadata_search_text(title) not in searchable:
        raise ValidationError(
            f"{field.title()} draft omitted or altered the current book title. Use TITLE exactly as supplied: {title}"
        )
    if series and _metadata_search_text(series) not in searchable:
        raise ValidationError(
            f"{field.title()} draft omitted or altered the current series name. "
            f"Use SERIES exactly as supplied: {series}"
        )
    if field == "instagram" and "yokstories" in searchable and "yok" not in _metadata_search_text(series):
        # "#YokStories" is used as an illustrative example in the prompt's hashtag
        # instructions. Seen in real usage: it leaked verbatim into a post for an
        # unrelated series ("Luma's Blue Dreams Forest") instead of being replaced
        # with a tag derived from the actual series. Reject it outright whenever the
        # current release isn't actually a Yok book.
        raise ValidationError(
            "Instagram draft used the hashtag #YokStories, which is only an example "
            f"from these instructions, not this book's actual series ({series or 'unknown'}). "
            "Use a brand/series hashtag derived from the real series name instead."
        )

    mentioned_numbers = re.findall(r"\bBook\s+(\d+)\b", text, flags=re.I)
    if number and any(found != number for found in mentioned_numbers):
        raise ValidationError(
            f"{field.title()} draft used the wrong book number. Use BOOK_NUMBER exactly as supplied: {number}"
        )
    if number and total:
        positions = re.findall(r"\bBook\s+(\d+)\s+of\s+(\d+)\b", text, flags=re.I)
        if positions and any(found_num != number or found_total != total for found_num, found_total in positions):
            raise ValidationError(
                f"{field.title()} draft used the wrong series position. Use Book {number} of {total}."
            )


_FUTURE_ANNOUNCEMENT_RE = re.compile(
    r"\bcoming\s+(?:soon\b|(?:on\s+)?[A-Z][a-z]+\s+\d{1,2}(?:st|nd|rd|th)?(?:,\s*\d{4})?|\d{4}\b)",
    re.IGNORECASE,
)


def _reads_as_not_yet_available(text: str) -> bool:
    """Broader "this isn't out yet" detector for the teaser status check.

    The old check only caught the literal phrase "coming soon" — it missed the
    equally common "coming <Month Day, Year>" pattern (seen in real usage: a
    teaser said "coming September 13, 2026" for a book whose own Instagram draft
    in the same release said "now available", a direct status contradiction that
    should have been rejected).
    """
    return bool(_FUTURE_ANNOUNCEMENT_RE.search(text)) or "not yet available" in text.lower()


def _validate_release_field_contract(
    field: str,
    text: str,
    *,
    status: str,
    release_url: str,
    require_release_metadata: bool = False,
    release_facts: dict[str, str] | None = None,
    hashtag_min: int = 0,
    hashtag_max: int = 0,
) -> None:
    lowered = text.lower()
    urls = _urls_in(text)
    exact_url = release_url.strip()
    _reject_leaked_placeholder(field, text)
    _reject_social_formatting(field, text)
    if require_release_metadata and release_facts:
        _validate_current_release_metadata(field, text, release_facts)

    if field == "facebook":
        if exact_url:
            unexpected = {url for url in urls if url != exact_url}
            if unexpected:
                raise ValidationError(
                    "Facebook draft invented or altered a URL. Use RELEASE_URL exactly as supplied. "
                    f"Unexpected URL(s): {', '.join(sorted(unexpected))}"
                )
            if require_release_metadata and status == "published" and exact_url not in urls:
                raise ValidationError(
                    "Published Facebook draft omitted the supplied RELEASE_URL. "
                    "Include the exact URL after the Amazon availability line."
                )
        elif urls:
            raise ValidationError(
                "Facebook draft contains a URL even though RELEASE_URL is empty; URLs must never be guessed."
            )
    elif field == "instagram":
        if urls:
            raise ValidationError("Instagram draft must not print a raw URL; use `link in bio` for published books.")
        if require_release_metadata and status == "published" and "link in bio" not in lowered:
            raise ValidationError("Published Instagram draft must include `Now available on Amazon — link in bio`.")
        if hashtag_max > 0:
            count = len(_HASHTAG_RE.findall(text))
            if count < hashtag_min or count > hashtag_max:
                raise ValidationError(f"Instagram draft has {count} hashtags; expected {hashtag_min}-{hashtag_max}.")
    elif field == "teaser":
        if status == "scheduled" and "available now" in lowered:
            raise ValidationError("Scheduled teaser must not say `available now`.")
        if status == "published" and _reads_as_not_yet_available(text):
            raise ValidationError(
                "Published teaser reads as not-yet-available (e.g. a future "
                "'coming <date>' announcement), contradicting the published status."
            )


def _trim_excess_hashtags(text: str, max_count: int) -> str:
    """Deterministically drop hashtags beyond `max_count` instead of relying on the
    model to count precisely.

    LLMs are unreliable at hitting an exact count under a hard cap — seen in the
    wild: an Instagram draft with 17 hashtags against a 12-16 range, failing even
    after one corrective retry. Counting and trimming is something code does
    perfectly and a model doesn't need to; only *undershooting* the minimum still
    needs a model retry, since we can't safely invent good hashtags ourselves.
    """
    if max_count <= 0:
        return text
    matches = list(_HASHTAG_RE.finditer(text))
    if len(matches) <= max_count:
        return text
    result = text
    for match in reversed(matches[max_count:]):
        start, end = match.span()
        result = result[:start] + result[end:]
    result = re.sub(r"[ \t]{2,}", " ", result)
    result = re.sub(r"[ \t]+\n", "\n", result)
    result = re.sub(r"\n{3,}", "\n\n", result)
    return result.rstrip()


def _validate_release_social_contract(
    payload: dict[str, Any],
    *,
    status: str,
    release_url: str,
    brand_voice: dict[str, Any] | None = None,
    profile: dict[str, Any] | None = None,
) -> None:
    voice = brand_voice or {}
    instagram = voice.get("instagram", {}) if isinstance(voice.get("instagram"), dict) else {}
    enforce_metadata = bool(voice.get("enforce_release_metadata", False))
    release_facts = _current_release_facts(profile or {}, status=status, release_date="", release_url=release_url)
    hashtag_max = int(instagram.get("hashtag_max", 0) or 0) if enforce_metadata else 0
    if hashtag_max > 0 and "instagram" in payload:
        payload["instagram"] = _trim_excess_hashtags(str(payload["instagram"]), hashtag_max)
    for field in ("facebook", "instagram", "teaser"):
        _validate_release_field_contract(
            field,
            str(payload.get(field, "")),
            status=status,
            release_url=release_url,
            require_release_metadata=enforce_metadata,
            release_facts=release_facts,
            hashtag_min=(int(instagram.get("hashtag_min", 0) or 0) if field == "instagram" and enforce_metadata else 0),
            hashtag_max=(hashtag_max if field == "instagram" else 0),
        )
