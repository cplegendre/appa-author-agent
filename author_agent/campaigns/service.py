from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from author_agent.analytics import AnalyticsService
from author_agent.persistence import AutomationStore


DEFAULT_SEQUENCE = (
    {"day": 0, "kind": "launch", "goal": "announce", "cta": "buy_or_read"},
    {"day": 2, "kind": "inside_the_book", "goal": "curiosity", "cta": "discover"},
    {"day": 5, "kind": "character_or_theme", "goal": "connection", "cta": "comment"},
    {"day": 9, "kind": "read_aloud_hook", "goal": "reader_value", "cta": "save_or_share"},
    {"day": 16, "kind": "evergreen_reminder", "goal": "rediscovery", "cta": "buy_or_read"},
)


@dataclass(frozen=True)
class CampaignSlot:
    id: str
    campaign_id: str
    book: str
    platform: str
    kind: str
    goal: str
    cta: str
    scheduled_at: str
    experiment: dict[str, str]
    status: str = "PLANNED"


class CampaignPlanner:
    """Create a durable, platform-aware post-release campaign without generating copy.

    Copy still goes through the existing grounding/review/approval pipeline. The planner's
    responsibility is campaign sequencing, cadence and experiment assignment.
    """

    def __init__(
        self,
        store: AutomationStore,
        *,
        timezone: str = "Europe/Prague",
        facebook_time: str = "19:00",
        instagram_time: str = "18:30",
        minimum_gap_hours: int = 18,
        minimum_samples: int = 10,
    ):
        self.store = store
        self.timezone = timezone
        self.tz = ZoneInfo(timezone)
        self.platform_times = {
            "facebook": self._parse_time(facebook_time),
            "instagram": self._parse_time(instagram_time),
        }
        self.minimum_gap = timedelta(hours=minimum_gap_hours)
        self.analytics = AnalyticsService(store, minimum_samples=minimum_samples)

    @staticmethod
    def _parse_time(value: str) -> time:
        hour, minute = (int(part) for part in value.split(":", 1))
        return time(hour=hour, minute=minute)

    def _variant(self, feature: str, candidates: list[str]) -> str:
        recommendation = self.analytics.recommend_variant(feature, candidates)
        return recommendation["value"]

    def _experiments(self, kind: str, platform: str) -> dict[str, str]:
        # Experiments are deliberately bounded to editorial attributes, not factual content.
        hook = self._variant("hook_style", ["statement", "question", "micro_scene"])
        length_candidates = ["short", "medium"] if platform == "instagram" else ["medium", "long"]
        length = self._variant("copy_length", length_candidates)
        cta_style = self._variant("cta_style", ["direct", "soft"])
        return {"hook_style": hook, "copy_length": length, "cta_style": cta_style, "post_kind": kind}

    def _scheduled_datetime(self, release: date, day_offset: int, platform: str) -> datetime:
        post_date = release + timedelta(days=day_offset)
        return datetime.combine(post_date, self.platform_times[platform], tzinfo=self.tz)

    def create_plan(
        self,
        *,
        book: str,
        release_date: str,
        platforms: tuple[str, ...] = ("facebook", "instagram"),
        sequence: tuple[dict, ...] = DEFAULT_SEQUENCE,
        persist: bool = True,
    ) -> dict:
        release = date.fromisoformat(release_date)
        invalid = sorted(set(platforms) - set(self.platform_times))
        if invalid:
            raise ValueError(f"Unsupported campaign platform(s): {', '.join(invalid)}")
        campaign_id = str(uuid.uuid4())
        now = datetime.now(self.tz).isoformat()
        slots: list[CampaignSlot] = []
        # Stagger FB and IG by 30m (default config) rather than simultaneous blasting.
        last_by_platform: dict[str, datetime] = {}
        for item in sequence:
            for platform in platforms:
                scheduled = self._scheduled_datetime(release, int(item["day"]), platform)
                previous = last_by_platform.get(platform)
                if previous is not None and scheduled - previous < self.minimum_gap:
                    scheduled = previous + self.minimum_gap
                last_by_platform[platform] = scheduled
                slot = CampaignSlot(
                    id=str(uuid.uuid4()),
                    campaign_id=campaign_id,
                    book=book,
                    platform=platform,
                    kind=str(item["kind"]),
                    goal=str(item["goal"]),
                    cta=str(item["cta"]),
                    scheduled_at=scheduled.isoformat(),
                    experiment=self._experiments(str(item["kind"]), platform),
                )
                slots.append(slot)
        if persist:
            with self.store.connect() as con:
                con.execute(
                    "INSERT INTO campaigns(id,book,release_date,timezone,status,created_at) VALUES(?,?,?,?,?,?)",
                    (campaign_id, book, release_date, self.timezone, "PLANNED", now),
                )
                for slot in slots:
                    con.execute(
                        "INSERT INTO campaign_slots(id,campaign_id,platform,kind,goal,cta,scheduled_at,"
                        "experiment_json,status) VALUES(?,?,?,?,?,?,?,?,?)",
                        (
                            slot.id,
                            campaign_id,
                            slot.platform,
                            slot.kind,
                            slot.goal,
                            slot.cta,
                            slot.scheduled_at,
                            self.store.dumps(slot.experiment),
                            slot.status,
                        ),
                    )
        return {
            "campaign_id": campaign_id,
            "book": book,
            "release_date": release_date,
            "timezone": self.timezone,
            "slots": [asdict(slot) for slot in slots],
        }

    def materialize_workflows(self, campaign_id: str) -> list[str]:
        """Create one INGESTED workflow per planned slot and attach experiment features."""
        from author_agent.workflow import WorkflowService

        plan = self.get_plan(campaign_id)
        workflow = WorkflowService(self.store)
        created: list[str] = []
        for slot in plan["slots"]:
            if slot.get("workflow_id"):
                created.append(str(slot["workflow_id"]))
                continue
            kind = str(slot["kind"])
            post_role = "launch" if kind == "launch" else ("evergreen" if kind == "evergreen_reminder" else "reminder")
            metadata = {
                "campaign_slot_id": slot["id"],
                "scheduled_at": slot["scheduled_at"],
                "kind": kind,
                "post_role": post_role,
                "goal": slot["goal"],
                "cta": slot["cta"],
                "experiment": slot["experiment"],
            }
            workflow_id = workflow.create(
                book=plan["book"],
                campaign=campaign_id,
                platform=slot["platform"],
                metadata=metadata,
            )
            self.analytics.store_features(workflow_id, slot["experiment"])
            with self.store.connect() as con:
                con.execute(
                    "UPDATE campaign_slots SET workflow_id=?,status='INGESTED' WHERE id=?",
                    (workflow_id, slot["id"]),
                )
            created.append(workflow_id)
        return created

    def get_plan(self, campaign_id: str) -> dict:
        with self.store.connect() as con:
            campaign = con.execute("SELECT * FROM campaigns WHERE id=?", (campaign_id,)).fetchone()
            if campaign is None:
                raise KeyError(campaign_id)
            rows = con.execute(
                "SELECT * FROM campaign_slots WHERE campaign_id=? ORDER BY scheduled_at,platform", (campaign_id,)
            ).fetchall()
        result = dict(campaign)
        result["slots"] = []
        for row in rows:
            item = dict(row)
            import json

            item["experiment"] = json.loads(item.pop("experiment_json") or "{}")
            result["slots"].append(item)
        return result
