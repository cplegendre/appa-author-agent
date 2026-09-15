from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from author_agent.analytics import AnalyticsService
from author_agent.campaigns import CampaignPlanner
from author_agent.persistence import AutomationStore
from author_agent.publishing import InvalidMediaPublishingError, MetaConfig, MetaPublisher


def test_schema_v27_and_campaign_plan_persists(tmp_path: Path) -> None:
    store = AutomationStore(tmp_path / "automation.sqlite3")
    assert store.schema_version() == 27
    planner = CampaignPlanner(store, minimum_samples=2)
    plan = planner.create_plan(book="Yok and the Rain.pdf", release_date="2026-09-15")
    assert len(plan["slots"]) == 10
    assert {slot["platform"] for slot in plan["slots"]} == {"facebook", "instagram"}
    assert plan["slots"][0]["kind"] == "launch"
    restored = planner.get_plan(plan["campaign_id"])
    assert len(restored["slots"]) == 10


def test_campaign_materializes_workflows_and_experiment_features(tmp_path: Path) -> None:
    store = AutomationStore(tmp_path / "automation.sqlite3")
    planner = CampaignPlanner(store, minimum_samples=2)
    plan = planner.create_plan(book="book.pdf", release_date="2026-09-15", platforms=("instagram",))
    ids = planner.materialize_workflows(plan["campaign_id"])
    assert len(ids) == 5
    restored = planner.get_plan(plan["campaign_id"])
    assert all(slot["workflow_id"] for slot in restored["slots"])
    with store.connect() as con:
        count = con.execute("SELECT COUNT(*) AS n FROM post_features").fetchone()["n"]
    assert count == 5


def test_experiment_selector_explores_then_exploits(tmp_path: Path) -> None:
    store = AutomationStore(tmp_path / "automation.sqlite3")
    analytics = AnalyticsService(store, minimum_samples=2)
    # question has enough samples and performs well, statement is still under-sampled -> explore statement
    for idx, shares in enumerate((4, 8)):
        wid = f"q{idx}"
        analytics.store_features(wid, {"hook_style": "question"})
        analytics.store_snapshot(wid, {"shares": shares})
    rec = analytics.recommend_variant("hook_style", ["question", "statement"])
    assert rec["mode"] == "explore"
    assert rec["value"] == "statement"
    for idx in range(2):
        wid = f"s{idx}"
        analytics.store_features(wid, {"hook_style": "statement"})
        analytics.store_snapshot(wid, {"likes": 1})
    rec = analytics.recommend_variant("hook_style", ["question", "statement"])
    assert rec["mode"] == "exploit"
    assert rec["value"] == "question"


def test_meta_metric_normalization_matches_analytics_vocabulary() -> None:
    normalized = MetaPublisher.normalize_metrics(
        {"saved": 4, "post_impressions_unique": 100, "post_impressions": 150, "comments": 2}
    )
    assert normalized == {"saves": 4.0, "reach": 100.0, "impressions": 150.0, "comments": 2.0}


def test_meta_preflight_checks_target_and_instagram_media() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "HEAD":
            return httpx.Response(200, headers={"content-type": "image/jpeg"})
        if request.url.path.endswith("/me"):
            return httpx.Response(200, json={"id": "me"})
        if request.url.path.endswith("/ig-1"):
            return httpx.Response(200, json={"id": "ig-1", "username": "author"})
        return httpx.Response(404)

    publisher = MetaPublisher(
        MetaConfig(access_token="secret", instagram_account_id="ig-1", dry_run=False),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    result = publisher.preflight("instagram", "https://cdn.example/cover.jpg")
    assert result["ok"] is True
    assert result["target"]["username"] == "author"
    assert result["media"]["content_type"] == "image/jpeg"


def test_instagram_preflight_rejects_missing_media() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/me"):
            return httpx.Response(200, json={"id": "me"})
        if request.url.path.endswith("/ig-1"):
            return httpx.Response(200, json={"id": "ig-1", "username": "author"})
        return httpx.Response(404)

    publisher = MetaPublisher(
        MetaConfig(access_token="secret", instagram_account_id="ig-1", dry_run=False),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(InvalidMediaPublishingError, match="requires"):
        publisher.preflight("instagram")


def test_campaign_guards_invalid_platform_and_missing_campaign(tmp_path: Path) -> None:
    store = AutomationStore(tmp_path / "automation.sqlite3")
    planner = CampaignPlanner(store)
    with pytest.raises(ValueError, match="Unsupported campaign"):
        planner.create_plan(book="book.pdf", release_date="2026-09-15", platforms=("tiktok",))
    with pytest.raises(KeyError):
        planner.get_plan("missing")


def test_campaign_enforces_minimum_gap_and_materialization_is_idempotent(tmp_path: Path) -> None:
    store = AutomationStore(tmp_path / "automation.sqlite3")
    planner = CampaignPlanner(store, minimum_gap_hours=18)
    sequence = (
        {"day": 0, "kind": "launch", "goal": "announce", "cta": "buy"},
        {"day": 0, "kind": "followup", "goal": "curiosity", "cta": "comment"},
    )
    plan = planner.create_plan(book="book.pdf", release_date="2026-09-15", platforms=("facebook",), sequence=sequence)
    first = planner.materialize_workflows(plan["campaign_id"])
    second = planner.materialize_workflows(plan["campaign_id"])
    assert second == first
    restored = planner.get_plan(plan["campaign_id"])
    assert restored["slots"][1]["scheduled_at"] > restored["slots"][0]["scheduled_at"]


def test_experiment_selector_requires_candidates(tmp_path: Path) -> None:
    analytics = AnalyticsService(AutomationStore(tmp_path / "automation.sqlite3"))
    with pytest.raises(ValueError, match="candidate"):
        analytics.recommend_variant("hook_style", [])


def test_meta_get_requests_use_query_parameters() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"data": []})

    publisher = MetaPublisher(
        MetaConfig(access_token="secret", facebook_page_id="page", dry_run=False),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    publisher.fetch_metrics("post-1", "facebook")
    assert seen[0].url.params["access_token"] == "secret"
    assert "metric" in seen[0].url.params
    assert seen[0].content == b""
