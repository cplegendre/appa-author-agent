from __future__ import annotations

import json
import logging
import time
from typing import Any

import requests

from .errors import OllamaError

LOG = logging.getLogger(__name__)


FACTUAL_REVIEW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "supported": {"type": "boolean"},
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "status": {"type": "string", "enum": ["unsupported", "contradicted"]},
                    "reason": {"type": "string"},
                },
                "required": ["text", "status", "reason"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["supported", "claims"],
    "additionalProperties": False,
}


def _actionable(base_url: str, detail: str) -> OllamaError:
    return OllamaError(
        f"Ollama is not reachable at {base_url.rstrip('/')}. "
        f"Run `ollama serve` and verify that the requested model is installed. Detail: {detail}"
    )


def post_json(
    base_url: str,
    endpoint: str,
    payload: dict[str, Any],
    *,
    timeout: int = 240,
    retries: int = 3,
    backoff_seconds: float = 1.0,
) -> requests.Response:
    """POST to Ollama with bounded exponential backoff and actionable errors."""
    url = f"{base_url.rstrip('/')}/{endpoint.lstrip('/')}"
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            LOG.debug("ollama_request", extra={"url": url, "attempt": attempt})
            response = requests.post(url, json=payload, timeout=timeout)
            # Retry transient server/rate-limit failures, but return 404 to callers that
            # intentionally probe old/new endpoints.
            if response.status_code == 404:
                return response
            if response.status_code == 429 or response.status_code >= 500:
                raise requests.HTTPError(f"HTTP {response.status_code}: {response.text[:300]}", response=response)
            response.raise_for_status()
            return response
        except (requests.Timeout, requests.ConnectionError, requests.HTTPError) as exc:
            last_error = exc
            LOG.warning(
                "ollama_request_failed",
                extra={"url": url, "attempt": attempt, "retries": retries, "error": str(exc)},
            )
            if attempt < retries:
                time.sleep(backoff_seconds * (2 ** (attempt - 1)))

    raise _actionable(base_url, str(last_error or "unknown error"))


def _response_text(response: requests.Response, model: str) -> tuple[str, dict[str, Any]]:
    try:
        payload = response.json()
        text = str(payload.get("response", "")).strip()
    except (ValueError, TypeError) as exc:
        raise OllamaError(f"Invalid response body from Ollama model `{model}`. Detail: {exc}") from exc
    return text, payload if isinstance(payload, dict) else {}


def _decode_json_object(text: str) -> dict | None:
    try:
        decoded = json.loads(text)
    except json.JSONDecodeError:
        decoded = None
    if isinstance(decoded, dict):
        return decoded

    extracted = _extract_json_object(text)
    if extracted is not None:
        return extracted
    return None


def generate_json(base_url: str, model: str, prompt: str, timeout: int = 240) -> dict:
    response = post_json(
        base_url,
        "/api/generate",
        {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            # Reasoning models (qwen3, deepseek-r1, ...) think in free text before
            # answering. Ollama's `format: "json"` grammar-constrains every token
            # from the start, which leaves no room for that reasoning pass and
            # commonly makes these models degenerate to an empty `{}` instead of
            # real content. `think: False` turns that off when supported.
            "think": False,
        },
        timeout=timeout,
    )
    if response.status_code == 404:
        raise _actionable(base_url, "endpoint /api/generate was not found")
    text, _payload = _response_text(response, model)
    decoded = _decode_json_object(text)
    if decoded is not None:
        if text.strip() != json.dumps(decoded, ensure_ascii=False, separators=(",", ":")):
            # This condition is intentionally approximate; the warning is useful when
            # commentary leaked around otherwise recoverable JSON.
            try:
                json.loads(text)
            except json.JSONDecodeError:
                LOG.warning(
                    "ollama_json_extracted_from_wrapped_response",
                    extra={"model": model, "raw_length": len(text)},
                )
        return decoded
    raise OllamaError(
        f"Invalid JSON response from Ollama model `{model}`. "
        f"Retry or verify the model. Raw response: {text[:300] or '<empty>'}"
    )


def generate_factual_review_json(base_url: str, model: str, prompt: str, timeout: int = 240) -> dict:
    """Generate compact factual-review JSON with one retry for malformed/truncated output.

    The factual reviewer is intentionally separate from generic JSON generation: claim-level
    reviews can be verbose, and local models occasionally hit an output limit mid-object. A
    strict compact schema, larger token budget, and one parser-level retry make this stage
    robust without changing generation behavior elsewhere.
    """
    retry_suffix = (
        "\n\nIMPORTANT RETRY INSTRUCTION:\n"
        "Your previous response was incomplete or invalid JSON. Return ONLY the compact JSON object "
        "required by the schema. List ONLY unsupported or contradicted claims. Do not include supported "
        "claims, evidence excerpts, notes, markdown, "
        "or commentary. Keep each reason to one short sentence."
    )
    last_text = ""
    last_done_reason = ""
    for attempt in range(2):
        request_prompt = prompt if attempt == 0 else prompt + retry_suffix
        response = post_json(
            base_url,
            "/api/generate",
            {
                "model": model,
                "prompt": request_prompt,
                "stream": False,
                "format": FACTUAL_REVIEW_SCHEMA,
                "think": False,
                "options": {
                    "temperature": 0,
                    "num_predict": 4096,
                },
            },
            timeout=timeout,
        )
        if response.status_code == 404:
            raise _actionable(base_url, "endpoint /api/generate was not found")
        text, payload = _response_text(response, model)
        last_text = text
        last_done_reason = str(payload.get("done_reason", "") or "")
        decoded = _decode_json_object(text)
        if decoded is not None:
            claims = decoded.get("claims")
            if isinstance(claims, list):
                # Defensive compaction if a model/older Ollama ignored the schema and
                # still returned supported claims or verbose legacy fields.
                blocking: list[dict[str, str]] = []
                for item in claims:
                    if not isinstance(item, dict):
                        continue
                    status = str(item.get("status", "")).strip().lower()
                    if status not in {"unsupported", "contradicted"}:
                        continue
                    text_value = str(item.get("text", "")).strip()
                    if not text_value:
                        continue
                    blocking.append(
                        {
                            "text": text_value,
                            "status": status,
                            "reason": str(item.get("reason", "")).strip(),
                        }
                    )
                return {"supported": not blocking, "claims": blocking}
            return decoded
        LOG.warning(
            "factual_review_invalid_json_retry",
            extra={
                "model": model,
                "attempt": attempt + 1,
                "raw_length": len(text),
                "done_reason": last_done_reason,
            },
        )

    detail = f" done_reason={last_done_reason!r}." if last_done_reason else ""
    raise OllamaError(
        f"Invalid JSON response from Ollama factual-review model `{model}` after one retry.{detail} "
        f"Raw response: {last_text[:300] or '<empty>'}"
    )


def _extract_json_object(text: str) -> dict | None:
    """Best-effort extraction of a JSON object embedded in extra text."""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        candidate = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return candidate if isinstance(candidate, dict) else None
