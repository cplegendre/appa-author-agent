from __future__ import annotations

import json
import logging

import httpx
import pytest

from author_agent.logging_utils import log_json_event
from author_agent.persistence import AutomationStore
from author_agent.publishing import (
    ExpiredTokenPublishingError,
    MetaConfig,
    MetaPublisher,
    PublishRequest,
    PublishingKillSwitchError,
    PublishingService,
    RateLimitPublishingError,
    RetryablePublishingError,
)
from author_agent.workflow import WorkflowService, WorkflowState


def _approved(tmp_path):
    store = AutomationStore(tmp_path / "ops.sqlite3")
    workflow = WorkflowService(store)
    wid = workflow.create(state=WorkflowState.REVIEW_REQUIRED)
    workflow.approve(wid, "hello")
    return store, workflow, wid


def test_global_kill_switch_blocks_live_call_before_network(monkeypatch):
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(200, json={"id": "should-not-happen"})

    monkeypatch.setenv("PUBLISHING_KILL_SWITCH", "true")
    publisher = MetaPublisher(
        MetaConfig(access_token="secret", facebook_page_id="page", dry_run=False),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(PublishingKillSwitchError, match="kill-switch"):
        publisher.publish_post(PublishRequest(platform="facebook", text="hello"))
    assert calls == 0


def test_kill_switch_is_rechecked_between_instagram_api_calls(monkeypatch):
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        if calls == 1:
            monkeypatch.setenv("PUBLISHING_KILL_SWITCH", "true")
            return httpx.Response(200, json={"id": "container-1"})
        return httpx.Response(200, json={"id": "post-1"})

    monkeypatch.delenv("PUBLISHING_KILL_SWITCH", raising=False)
    publisher = MetaPublisher(
        MetaConfig(access_token="secret", instagram_account_id="ig", dry_run=False),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(PublishingKillSwitchError):
        publisher.publish_post(PublishRequest(platform="instagram", text="hello", media_url="https://e/x.jpg"))
    assert calls == 1


def test_network_timeout_retries_then_exhausts():
    calls = 0

    def handler(request):
        nonlocal calls
        calls += 1
        raise httpx.ReadTimeout("socket timed out", request=request)

    publisher = MetaPublisher(
        MetaConfig(access_token="secret", facebook_page_id="page", dry_run=False, max_retries=2),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda _: None,
    )
    with pytest.raises(RetryablePublishingError, match="timeout"):
        publisher.publish_post(PublishRequest(platform="facebook", text="hello"))
    assert calls == 3


def test_rate_limit_retries_then_exhausts():
    calls = 0

    def handler(_request):
        nonlocal calls
        calls += 1
        return httpx.Response(429, json={"error": {"message": "rate limited", "code": 4}})

    publisher = MetaPublisher(
        MetaConfig(access_token="secret", facebook_page_id="page", dry_run=False, max_retries=1),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda _: None,
    )
    with pytest.raises(RateLimitPublishingError):
        publisher.publish_post(PublishRequest(platform="facebook", text="hello"))
    assert calls == 2


def test_expired_token_is_not_retried():
    calls = 0

    def handler(_request):
        nonlocal calls
        calls += 1
        return httpx.Response(400, json={"error": {"message": "Token expired", "code": 190, "error_subcode": 463}})

    publisher = MetaPublisher(
        MetaConfig(access_token="secret", facebook_page_id="page", dry_run=False, max_retries=3),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda _: None,
    )
    with pytest.raises(ExpiredTokenPublishingError):
        publisher.publish_post(PublishRequest(platform="facebook", text="hello"))
    assert calls == 1


def test_dry_run_is_fail_closed_and_never_touches_network(monkeypatch):
    monkeypatch.setenv("PUBLISHING_KILL_SWITCH", "true")

    def handler(request):
        raise AssertionError(f"dry-run unexpectedly networked: {request.url}")

    publisher = MetaPublisher(
        MetaConfig(dry_run=True),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    result = publisher.publish_post(PublishRequest(platform="facebook", text="hello", idempotency_key="safe"))
    assert result.external_id == "dry-run:safe"
    assert result.raw == {"dry_run": True}


def test_publication_failure_is_persisted_and_alerted(tmp_path):
    class FailingPublisher:
        def publish_post(self, request):
            raise RetryablePublishingError("network down")

        def schedule_post(self, request):
            return self.publish_post(request)

    store, workflow, wid = _approved(tmp_path)
    alerts = []
    service = PublishingService(store, workflow, FailingPublisher(), alerter=lambda event: alerts.append(event) or True)
    with pytest.raises(RetryablePublishingError):
        service.publish(wid, platform="facebook", text="hello")
    assert workflow.get(wid)["state"] == "FAILED"
    with store.connect() as con:
        attempt = con.execute(
            "SELECT status,response_json FROM publish_attempts WHERE workflow_id=?", (wid,)
        ).fetchone()
    assert attempt["status"] == "failed"
    assert "network down" in attempt["response_json"]
    assert alerts and alerts[0]["platform"] == "facebook"


def test_structured_publication_log_is_valid_json(caplog):
    logger = logging.getLogger("author_agent.v28.json")
    with caplog.at_level(logging.INFO, logger=logger.name):
        log_json_event(logger, logging.INFO, "publication_attempt", outcome="success", platform="facebook")
    message = caplog.records[-1].getMessage()
    assert json.loads(message) == {"event": "publication_attempt", "outcome": "success", "platform": "facebook"}


def test_slack_alerter_posts_redacted_failure(monkeypatch):
    from author_agent.alerting import slack_webhook_alerter

    monkeypatch.setenv("AUTHOR_AGENT_ALERT_WEBHOOK", "https://hooks.example.test/abc")
    captured = {}

    class Response:
        def raise_for_status(self):
            return None

    def fake_post(url, *, json, timeout):
        captured.update(url=url, json=json, timeout=timeout)
        return Response()

    monkeypatch.setattr("author_agent.alerting.httpx.post", fake_post)
    notify = slack_webhook_alerter(timeout_seconds=7)
    assert notify({"workflow_id": "w1", "platform": "facebook", "reason": "boom"}) is True
    assert captured["url"].endswith("/abc")
    assert captured["timeout"] == 7
    assert "workflow=w1" in captured["json"]["text"]


def test_slack_alerter_without_webhook_is_best_effort(monkeypatch):
    from author_agent.alerting import slack_webhook_alerter

    monkeypatch.delenv("AUTHOR_AGENT_ALERT_WEBHOOK", raising=False)
    assert slack_webhook_alerter()({"workflow_id": "w1", "reason": "boom"}) is False
