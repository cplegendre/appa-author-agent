from __future__ import annotations

import json
import os
from datetime import datetime
from typing import Any, Callable

from author_agent.alerting import slack_webhook_alerter
from author_agent.analytics import AnalyticsService
from author_agent.persistence import AutomationStore
from author_agent.publishing import MetaConfig, MetaPublisher, PublishingService
from author_agent.workflow import WorkflowService, WorkflowState


def meta_publisher(settings: dict[str, Any], ollama: dict[str, Any]) -> MetaPublisher:
    pcfg = settings["publishing"]
    if not pcfg.get("enabled", False):
        raise ValueError("Social publishing is disabled. Set publishing.enabled=true deliberately before publishing.")
    mcfg = settings["meta"]
    token = os.getenv(str(mcfg.get("access_token_env", "META_ACCESS_TOKEN")), "")
    return MetaPublisher(
        MetaConfig(
            access_token=token,
            facebook_page_id=mcfg.get("facebook_page_id", ""),
            instagram_account_id=mcfg.get("instagram_account_id", ""),
            graph_version=mcfg.get("graph_version", "v23.0"),
            timeout_seconds=int(ollama.get("timeout_seconds", 240)),
            dry_run=bool(pcfg.get("dry_run", True)),
            max_retries=int(pcfg.get("max_retries", 3)),
            kill_switch_env=str(pcfg.get("kill_switch_env", "PUBLISHING_KILL_SWITCH")),
        )
    )


def publishing_service(
    store: AutomationStore, settings: dict[str, Any], ollama: dict[str, Any]
) -> PublishingService:
    ncfg = settings.get("notifications", {})
    alerter = slack_webhook_alerter(
        env_name=str(ncfg.get("alert_webhook_env", "AUTHOR_AGENT_ALERT_WEBHOOK")),
        timeout_seconds=int(ncfg.get("alert_timeout_seconds", 10)),
    )
    return PublishingService(store, WorkflowService(store), meta_publisher(settings, ollama), alerter=alerter)


def publish_command(
    args: Any,
    *,
    store_factory: Callable[[], AutomationStore],
    settings: dict,
    ollama: dict,
    output: Callable[[Any], None],
) -> None:
    service = publishing_service(store_factory(), settings, ollama)
    scheduled = datetime.fromisoformat(args.schedule_at) if args.schedule_at else None
    result = service.publish(
        args.id,
        platform=args.platform,
        text=args.text,
        media_url=args.media_url or None,
        scheduled_at=scheduled,
    )
    output(json.dumps({"external_id": result.external_id, "status": result.status, "url": result.url}, indent=2))


def publish_due_command(
    args: Any,
    *,
    store_factory: Callable[[], AutomationStore],
    settings: dict,
    ollama: dict,
    output: Callable[[Any], None],
) -> None:
    results = publishing_service(store_factory(), settings, ollama).run_due()
    output(json.dumps({"published": len(results), "external_ids": [r.external_id for r in results]}, indent=2))


def preflight_command(
    args: Any, *, settings: dict, ollama: dict, output: Callable[[Any], None]
) -> None:
    result = meta_publisher(settings, ollama).preflight(args.platform, args.media_url or None)
    output(json.dumps(result, ensure_ascii=False, indent=2))


def metrics_command(
    args: Any,
    *,
    store_factory: Callable[[], AutomationStore],
    settings: dict,
    ollama: dict,
    output: Callable[[Any], None],
) -> None:
    store = store_factory()
    workflow = WorkflowService(store)
    row = workflow.get(args.id)
    if not row.get("external_id"):
        raise ValueError("Workflow has no published external ID")
    publisher = meta_publisher(settings, ollama)
    metrics = publisher.fetch_metrics(row["external_id"], row["platform"] or args.platform)
    acfg = settings["analytics"]
    analytics = AnalyticsService(
        store,
        weights=acfg.get("weights"),
        minimum_samples=int(acfg.get("minimum_samples", 10)),
    )
    score = analytics.store_snapshot(args.id, metrics)
    if WorkflowState(row["state"]) == WorkflowState.PUBLISHED:
        workflow.transition(args.id, WorkflowState.MEASURED, reason="metrics refreshed")
    output(json.dumps({"metrics": metrics, "score": score}, indent=2))
