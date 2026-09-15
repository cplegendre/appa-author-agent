from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

_REDACTED = "[REDACTED]"
_SENSITIVE_ENV_PREFIX = "AUTHOR_AGENT__META__"


def secret_values() -> set[str]:
    values: set[str] = set()
    for key, value in os.environ.items():
        upper = key.upper()
        if upper == "META_ACCESS_TOKEN" or upper.startswith(_SENSITIVE_ENV_PREFIX):
            if value:
                values.add(value)
    return values


def redact_text(value: object) -> str:
    text = str(value)
    for secret in sorted(secret_values(), key=len, reverse=True):
        text = text.replace(secret, _REDACTED)
    text = re.sub(
        r"(?i)(access[_-]?token|token)([=:]\s*)([^&\s,;]+)",
        lambda match: f"{match.group(1)}{match.group(2)}{_REDACTED}",
        text,
    )
    text = re.sub(
        r"(?i)(bearer\s+)([^&\s,;]+)",
        lambda match: f"{match.group(1)}{_REDACTED}",
        text,
    )
    return text


class SecretRedactionFilter(logging.Filter):
    """Redact configured Meta secrets from messages, arguments and exception text."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.msg = redact_text(record.getMessage())
        record.args = ()
        if record.exc_info and record.exc_info[1]:
            exc = record.exc_info[1]
            if exc.args:
                exc.args = tuple(redact_text(arg) for arg in exc.args)
        return True


def install_secret_redaction(logger: logging.Logger | None = None) -> SecretRedactionFilter:
    target = logger or logging.getLogger()
    redactor = SecretRedactionFilter()
    target.addFilter(redactor)
    for handler in target.handlers:
        handler.addFilter(redactor)
    return redactor


def log_event(logger: logging.Logger, level: int, event: str, **context: Any) -> None:
    details = " ".join(
        f"{redact_text(key)}={redact_text(value)}" for key, value in sorted(context.items()) if value not in (None, "")
    )
    message = f"{redact_text(event)} {details}".rstrip()
    logger.log(level, message)


def log_json_event(logger: logging.Logger, level: int, event: str, **context: Any) -> None:
    """Emit one redacted, machine-parseable JSON event as the log message."""
    payload: dict[str, Any] = {"event": redact_text(event)}
    for key, value in context.items():
        if value in (None, ""):
            continue
        safe_key = redact_text(key)
        if isinstance(value, (str, int, float, bool)):
            payload[safe_key] = redact_text(value) if isinstance(value, str) else value
        else:
            payload[safe_key] = redact_text(value)
    logger.log(level, json.dumps(payload, ensure_ascii=False, sort_keys=True))
