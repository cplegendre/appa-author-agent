from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class PublishRequest:
    platform: str
    text: str
    media_url: str | None = None
    scheduled_at: datetime | None = None
    idempotency_key: str = ""


@dataclass(frozen=True)
class PublishResult:
    external_id: str
    status: str
    url: str | None = None
    raw: dict | None = None


class SocialPublisher(Protocol):
    def validate_credentials(self) -> bool: ...
    def publish_post(self, request: PublishRequest) -> PublishResult: ...
    def schedule_post(self, request: PublishRequest) -> PublishResult: ...
    def get_post_status(self, external_id: str, platform: str) -> str: ...
    def fetch_metrics(self, external_id: str, platform: str) -> dict[str, float]: ...
