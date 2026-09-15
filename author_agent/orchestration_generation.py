from __future__ import annotations

import json
import logging
from typing import Any, Callable

from .errors import MarkdownFormattingError, ParagraphFormattingError, SocialFormattingError, ValidationError
from .orchestration_factual import FactualGroundingError
from .orchestration_types import OrchestrationDeps
from .orchestration_validation import _auto_fix_social_text

LOG = logging.getLogger(__name__)

_DEFAULT_RETRY_BUDGET = 2
_FORMATTING_RETRY_BUDGET = 4


def _correction_block(last_error: ValidationError, last_sample: str, fields: tuple[str, ...]) -> str:
    """Build the corrective follow-up appended to a retry prompt.

    Formatting failures (Markdown or missing paragraph breaks) get a sharper,
    example-driven correction instead of the generic "your response was
    invalid" wording, since that generic wording was not enough on its own to
    stop the model from repeating the same mistake on the very next attempt.
    """
    if isinstance(last_error, MarkdownFormattingError):
        return (
            f"IMPORTANT: your previous response still used Markdown formatting. {last_error}\n"
            "Do not use *, **, _, __, #, or leading -/* list markers anywhere in the text — "
            "not even around the book title. Write the title as plain words, e.g. "
            "`Yok Helps a Friend`, never `*Yok Helps a Friend*`.\n\n"
            "Return ONLY a single flat JSON object with non-empty plain-text string values "
            f"for every one of these keys: {', '.join(fields)}. No nested objects, markdown, or commentary."
        )
    if isinstance(last_error, ParagraphFormattingError):
        return (
            f"IMPORTANT: your previous response was still one unbroken block of text. {last_error}\n"
            "Break the copy into 2-3 short paragraphs. Put a literal blank line "
            "(the two-character sequence \\n\\n) between paragraphs inside the JSON string, e.g. "
            '"First short paragraph here.\\n\\nSecond short paragraph here."\n\n'
            "Return ONLY a single flat JSON object with non-empty plain-text string values "
            f"for every one of these keys: {', '.join(fields)}. No nested objects, markdown, or commentary."
        )
    if isinstance(last_error, FactualGroundingError):
        return last_error.corrective_prompt()
    return (
        "IMPORTANT: your previous response was invalid or missing required "
        f"fields ({', '.join(fields)}). You returned: {last_sample}\n"
        f"Validation problem: {last_error}\n\n"
        "Return ONLY a single flat JSON object with non-empty string values "
        f"for every one of these keys: {', '.join(fields)}. No nested objects, markdown, or commentary."
    )


_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "facebook": ("facebook", "facebook_post", "fb", "fb_post"),
    "instagram": ("instagram", "instagram_post", "ig", "ig_post"),
    "teaser": ("teaser", "teaser_post", "preview", "coming_soon"),
}
_TEXT_KEYS = ("text", "caption", "content", "copy", "post", "body", "message")
_CONTAINER_KEYS = ("social", "drafts", "posts", "result", "output", "response", "data")


def _clean_string(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _text_from_value(value: Any, *, depth: int = 0) -> str | None:
    """Extract copy from a nested model value without accepting unrelated metadata."""
    text = _clean_string(value)
    if text is not None:
        return text
    if depth >= 4:
        return None
    if isinstance(value, dict):
        for key in _TEXT_KEYS:
            if key in value:
                found = _text_from_value(value[key], depth=depth + 1)
                if found is not None:
                    return found
        # Some models wrap the requested draft in one arbitrary object key.
        if len(value) == 1:
            return _text_from_value(next(iter(value.values())), depth=depth + 1)
    if isinstance(value, list) and len(value) == 1:
        return _text_from_value(value[0], depth=depth + 1)
    return None


def _find_field_value(payload: dict[str, Any], field: str, *, depth: int = 0) -> str | None:
    if depth >= 4:
        return None
    aliases = _FIELD_ALIASES.get(field, (field,))
    for key in aliases:
        if key in payload:
            found = _text_from_value(payload[key], depth=depth + 1)
            if found is not None:
                return found
    for container in _CONTAINER_KEYS:
        nested = payload.get(container)
        if isinstance(nested, dict):
            found = _find_field_value(nested, field, depth=depth + 1)
            if found is not None:
                return found
    return None


def _payload_shape(payload: Any) -> str:
    if isinstance(payload, dict):
        return "keys=" + ",".join(sorted(str(key) for key in payload.keys()))
    return f"type={type(payload).__name__}"


def _payload_sample(payload: Any, *, max_len: int = 400) -> str:
    """Short, log-safe preview of what the model actually returned.

    This is what was missing when this bug first surfaced: the error only said
    `keys=` (empty dict) with no way to tell whether Ollama returned truly empty
    JSON, a differently-shaped JSON, or something that barely parsed. Every
    validation failure below now logs and surfaces this sample so it's obvious
    from the log line (or the web UI error) what the model actually produced.
    """
    try:
        text = json.dumps(payload, ensure_ascii=False)
    except (TypeError, ValueError):
        text = str(payload)
    text = text.strip()
    if len(text) > max_len:
        text = text[:max_len] + "…(truncated)"
    return text or "<empty>"


def _generate_social_with_retry(
    deps: OrchestrationDeps,
    ollama: dict,
    template: str,
    fields: tuple[str, ...],
    render_kwargs: dict,
    *,
    label: str,
    post_validate: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Generate + validate a social payload, retrying on a bad/empty response.

    A model occasionally returns syntactically valid but empty/wrong-shaped JSON
    (e.g. `{}`) even in Ollama's `format: json` mode, especially with a tight
    timeout or an undertrained marketing model. Rather than failing the whole
    release on the first miss, retry with a corrective follow-up prompt that
    echoes back exactly what came back and exactly what's still missing.

    Markdown-formatting failures get extra attempts (`_FORMATTING_RETRY_BUDGET`
    instead of the normal `_DEFAULT_RETRY_BUDGET`): the fix is mechanical
    (remove a few stray characters), so it's cheap to keep asking, and if the
    model still won't stop after that many corrective nudges, `_FORMATTING_RETRY_BUDGET`
    of them the last response is sanitized in code instead of failing the whole run.
    """
    attempts_log: list[str] = []
    last_error: ValidationError | None = None
    last_normalized: dict[str, Any] | None = None
    max_attempts = _DEFAULT_RETRY_BUDGET
    attempt = 0
    while attempt < max_attempts:
        prompt = deps.render(template, **render_kwargs)
        if attempt >= 1 and last_error is not None:
            prompt = f"{prompt}\n\n{_correction_block(last_error, attempts_log[-1], fields)}"
        payload = deps.generate_json(
            ollama["base_url"],
            ollama["marketing_model"],
            prompt,
            ollama.get("timeout_seconds", 240),
        )
        sample = _payload_sample(payload)
        attempts_log.append(sample)
        try:
            normalized = _normalize_social_payload(payload, fields)
            last_normalized = normalized
            if post_validate is not None:
                post_validate(normalized)
            return normalized
        except ValidationError as exc:
            last_error = exc
            LOG.warning(
                "%s_generation_attempt_failed",
                label,
                extra={"attempt": attempt + 1, "payload_sample": sample},
            )
            if isinstance(exc, SocialFormattingError) and max_attempts == _DEFAULT_RETRY_BUDGET:
                # Give the model the full markdown-specific retry budget instead of
                # bailing after the generic first retry.
                max_attempts = _FORMATTING_RETRY_BUDGET
        attempt += 1

    if isinstance(last_error, SocialFormattingError) and last_normalized is not None:
        sanitized = dict(last_normalized)
        for field in fields:
            if field in sanitized and isinstance(sanitized[field], str):
                sanitized[field] = _auto_fix_social_text(sanitized[field])
        try:
            if post_validate is not None:
                post_validate(sanitized)
            LOG.warning(
                "%s_markdown_auto_stripped",
                label,
                extra={"fields": list(fields), "attempts": attempt},
            )
            return sanitized
        except ValidationError:
            pass  # Auto-strip didn't fully resolve it (e.g. tripped another check); fall through to raise.

    assert last_error is not None
    raise ValidationError(f"{last_error} Model response after retry: {attempts_log[-1]}")


def _normalize_social_payload(payload: dict[str, Any], fields: tuple[str, ...]) -> dict[str, Any]:
    """Normalize a multi-field social payload and reject empty required drafts."""
    normalized = dict(payload)
    missing: list[str] = []
    for field in fields:
        found = _find_field_value(payload, field)
        if found is None:
            missing.append(field)
        else:
            normalized[field] = found
    if missing:
        joined = ", ".join(missing)
        sample = _payload_sample(payload)
        LOG.warning(
            "social_payload_missing_fields",
            extra={"missing_fields": joined, "payload_shape": _payload_shape(payload), "payload_sample": sample},
        )
        raise ValidationError(
            f"The model response is missing usable social draft(s): {joined} "
            f"({_payload_shape(payload)}, sample={sample})."
        )
    return normalized


def _extract_generated_text(payload: dict[str, Any], field: str) -> str:
    """Return usable targeted copy while tolerating common nested model schemas."""
    found = _find_field_value(payload, field)
    if found is not None:
        return found

    # Targeted prompts ask for one field only, so generic text wrappers are safe here.
    for key in _TEXT_KEYS:
        if key in payload:
            found = _text_from_value(payload[key])
            if found is not None:
                return found
    for container in _CONTAINER_KEYS:
        nested = payload.get(container)
        if isinstance(nested, dict):
            for key in _TEXT_KEYS:
                if key in nested:
                    found = _text_from_value(nested[key])
                    if found is not None:
                        return found
    if len(payload) == 1:
        found = _text_from_value(next(iter(payload.values())))
        if found is not None:
            return found

    LOG.warning(
        "targeted_regeneration_payload_unsupported",
        extra={"field": field, "payload_shape": _payload_shape(payload)},
    )
    raise ValidationError(
        f"The model returned an empty draft or unsupported payload for `{field}` "
        f"({_payload_shape(payload)}). Expected the platform name or a text-like wrapper."
    )


def _generate_targeted_text_with_retry(
    deps: OrchestrationDeps,
    ollama: dict[str, Any],
    prompt: str,
    field: str,
    *,
    post_validate: Callable[[str], None] | None = None,
    label: str = "targeted_social",
) -> str:
    """Generate one social field and retry when its output contract fails.

    Same extended formatting-retry budget and auto-fix fallback as
    `_generate_social_with_retry` — see its docstring.
    """
    last_error: ValidationError | None = None
    last_sample = "<none>"
    last_text: str | None = None
    max_attempts = _DEFAULT_RETRY_BUDGET
    attempt = 0
    while attempt < max_attempts:
        effective_prompt = prompt
        if attempt >= 1 and last_error is not None:
            effective_prompt = f"{prompt}\n\n{_correction_block(last_error, last_sample, (field,))}"
        payload = deps.generate_json(
            ollama["base_url"],
            ollama["marketing_model"],
            effective_prompt,
            ollama.get("timeout_seconds", 240),
        )
        last_sample = _payload_sample(payload)
        try:
            text = _extract_generated_text(payload, field)
            last_text = text
            if post_validate is not None:
                post_validate(text)
            return text
        except ValidationError as exc:
            last_error = exc
            LOG.warning(
                "%s_generation_attempt_failed",
                label,
                extra={"attempt": attempt + 1, "field": field, "payload_sample": last_sample},
            )
            if isinstance(exc, SocialFormattingError) and max_attempts == _DEFAULT_RETRY_BUDGET:
                max_attempts = _FORMATTING_RETRY_BUDGET
        attempt += 1

    if isinstance(last_error, SocialFormattingError) and last_text is not None:
        sanitized = _auto_fix_social_text(last_text)
        try:
            if post_validate is not None:
                post_validate(sanitized)
            LOG.warning("%s_markdown_auto_stripped", label, extra={"field": field, "attempts": attempt})
            return sanitized
        except ValidationError:
            pass

    assert last_error is not None
    raise ValidationError(f"{last_error} Model response after retry: {last_sample}")
