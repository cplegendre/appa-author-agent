from __future__ import annotations

import json
from typing import Any, Callable

from author_agent.campaigns import CampaignPlanner
from author_agent.persistence import AutomationStore


def plan_command(
    args: Any,
    *,
    store_factory: Callable[[], AutomationStore],
    settings: dict,
    output: Callable[[Any], None],
) -> None:
    store = store_factory()
    cfg = settings["campaign"]
    analytics_cfg = settings["analytics"]
    planner = CampaignPlanner(
        store,
        timezone=cfg.get("timezone", "Europe/Prague"),
        facebook_time=cfg.get("facebook_time", "19:00"),
        instagram_time=cfg.get("instagram_time", "18:30"),
        minimum_gap_hours=int(cfg.get("minimum_gap_hours", 18)),
        minimum_samples=int(analytics_cfg.get("minimum_samples", 10)),
    )
    platforms = tuple(args.platform or ["facebook", "instagram"])
    result = planner.create_plan(
        book=args.book,
        release_date=args.release_date,
        platforms=platforms,
        persist=not args.no_persist,
    )
    if args.create_workflows and not args.no_persist:
        result["workflow_ids"] = planner.materialize_workflows(result["campaign_id"])
        result = planner.get_plan(result["campaign_id"]) | {"workflow_ids": result["workflow_ids"]}
    output(json.dumps(result, ensure_ascii=False, indent=2))


def status_command(
    args: Any,
    *,
    store_factory: Callable[[], AutomationStore],
    settings: dict,
    output: Callable[[Any], None],
) -> None:
    cfg = settings["campaign"]
    planner = CampaignPlanner(store_factory(), timezone=cfg.get("timezone", "Europe/Prague"))
    output(json.dumps(planner.get_plan(args.id), ensure_ascii=False, indent=2))
