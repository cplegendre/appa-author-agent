from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

from author_agent.persistence import AutomationStore
from author_agent.publishing import MetaConfig, MetaPublisher, PublishRequest, PublishingError, PublishingService
from author_agent.workflow import WorkflowService, WorkflowState


class FakePublisher:
    def __init__(self): self.calls = 0
    def validate_credentials(self): return True
    def publish_post(self, request):
        self.calls += 1
        from author_agent.publishing import PublishResult
        return PublishResult("post-1", "published", "https://example/post-1")
    def schedule_post(self, request):
        self.calls += 1
        from author_agent.publishing import PublishResult
        return PublishResult("sched-1", "scheduled")
    def get_post_status(self, external_id, platform): return "published"
    def fetch_metrics(self, external_id, platform): return {"reach": 1.0}


def approved(tmp_path: Path):
    store = AutomationStore(tmp_path / "a.sqlite3")
    wf = WorkflowService(store)
    wid = wf.create(state=WorkflowState.REVIEW_REQUIRED)
    wf.approve(wid, "hello")
    return store, wf, wid


def test_meta_dry_run_needs_no_credentials_and_never_networks():
    pub = MetaPublisher(MetaConfig(dry_run=True))
    assert pub.validate_credentials()
    result = pub.publish_post(PublishRequest(platform="facebook", text="hi", idempotency_key="x"))
    assert result.external_id == "dry-run:x"


def test_meta_payload_and_success():
    def handler(req: httpx.Request):
        body = req.read().decode()
        assert "message=hello" in body
        assert "access_token=secret" in body
        return httpx.Response(200, json={"id": "abc"})
    client = httpx.Client(transport=httpx.MockTransport(handler))
    pub = MetaPublisher(MetaConfig(access_token="secret", facebook_page_id="page", dry_run=False), client=client)
    assert pub.publish_post(PublishRequest(platform="facebook", text="hello")).external_id == "abc"


def test_meta_retries_rate_limit_then_succeeds():
    calls = 0
    def handler(req):
        nonlocal calls
        calls += 1
        return httpx.Response(
            429 if calls == 1 else 200,
            json={"error": {"message": "rate"}} if calls == 1 else {"id": "ok"},
        )
    pub = MetaPublisher(
        MetaConfig(access_token="x", facebook_page_id="p", dry_run=False),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
        sleep=lambda _: None,
    )
    assert pub.publish_post(PublishRequest(platform="facebook", text="x")).external_id == "ok"
    assert calls == 2


def test_meta_permanent_error_normalized():
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda req: httpx.Response(400, json={"error": {"message": "bad token details"}})
        )
    )
    pub = MetaPublisher(MetaConfig(access_token="secret", facebook_page_id="p", dry_run=False), client=client)
    with pytest.raises(PublishingError, match="bad token details"):
        pub.publish_post(PublishRequest(platform="facebook", text="x"))


def test_publish_service_duplicate_protection(tmp_path):
    store, wf, wid = approved(tmp_path)
    fake = FakePublisher()
    service = PublishingService(store, wf, fake)
    one = service.publish(wid, platform="facebook", text="hello")
    two = service.publish(wid, platform="facebook", text="hello")
    assert one.external_id == two.external_id == "post-1"
    assert fake.calls == 1


def test_publish_service_reapproval_if_content_changed(tmp_path):
    store, wf, wid = approved(tmp_path)
    service = PublishingService(store, wf, FakePublisher())
    with pytest.raises(ValueError, match="reapproval"):
        service.publish(wid, platform="facebook", text="changed")
    assert wf.get(wid)["state"] == "REVIEW_REQUIRED"


def test_scheduled_publish(tmp_path):
    store, wf, wid = approved(tmp_path)
    fake = FakePublisher()
    result = PublishingService(store, wf, fake).publish(
        wid,
        platform="facebook",
        text="hello",
        scheduled_at=datetime(2030, 1, 1, tzinfo=timezone.utc),
    )
    assert result.status == "scheduled"
    assert wf.get(wid)["state"] == "SCHEDULED"

def test_run_due_survives_restart(tmp_path):
    store, wf, wid = approved(tmp_path)
    fake = FakePublisher()
    first = PublishingService(store, wf, fake)
    first.publish(wid, platform="instagram", text="hello", scheduled_at=datetime(2020,1,1,tzinfo=timezone.utc))
    # New service instance simulates process restart and reads durable queued payload.
    restarted = PublishingService(AutomationStore(store.path), WorkflowService(AutomationStore(store.path)), fake)
    results = restarted.run_due(now=datetime(2020,1,2,tzinfo=timezone.utc))
    assert results[0].external_id == "post-1"
    assert restarted.workflow.get(wid)["state"] == "PUBLISHED"
