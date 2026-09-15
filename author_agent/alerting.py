from __future__ import annotations

import logging
import os
from typing import Any, Callable

import httpx

from .logging_utils import log_json_event, redact_text

LOG = logging.getLogger(__name__)

FailureAlerter = Callable[[dict[str, Any]], bool]


def slack_webhook_alerter(*, env_name: str = "AUTHOR_AGENT_ALERT_WEBHOOK", timeout_seconds: int = 10) -> FailureAlerter:
    """Return a best-effort Slack-compatible webhook notifier.

    If the configured environment variable is empty, alerts are logged and treated
    as not delivered. Alert delivery failures never mask the publishing failure.
    """

    def notify(event: dict[str, Any]) -> bool:
        webhook = os.getenv(env_name, "").strip()
        if not webhook:
            log_json_event(LOG, logging.WARNING, "publication_alert_skipped", reason="webhook_not_configured")
            return False
        event_type = str(event.get("event_type") or "publication_failure")
        heading = "Author Agent stale review" if event_type == "stale_review" else "Author Agent publication failure"
        text = (
            f"{heading}\n"
            f"workflow={event.get('workflow_id', '')} platform={event.get('platform', '')} "
            f"reason={redact_text(event.get('reason', 'unknown'))}"
        )
        try:
            response = httpx.post(webhook, json={"text": text}, timeout=timeout_seconds)
            response.raise_for_status()
            log_json_event(LOG, logging.INFO, "publication_alert_sent", channel="slack_webhook")
            return True
        except httpx.HTTPError as exc:
            log_json_event(
                LOG,
                logging.ERROR,
                "publication_alert_failed",
                channel="slack_webhook",
                reason=type(exc).__name__,
            )
            return False

    return notify
