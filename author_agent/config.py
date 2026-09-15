from __future__ import annotations

import copy
import os
import re
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic import ValidationError as PydanticValidationError

from .errors import ConfigError

ROOT = Path(os.getenv("AUTHOR_AGENT_ROOT", Path(__file__).resolve().parents[1])).expanduser().resolve()
_TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


class SectionModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)

    def __getitem__(self, key: str) -> Any:
        return getattr(self, key)


class OllamaSettings(SectionModel):
    base_url: str = "http://localhost:11434"
    marketing_model: str = "qwen3:14b"
    coding_model: str = "devstral-small-2:latest"
    review_model: str = "gemma4:12b"
    embedding_model: str = "embeddinggemma:latest"
    timeout_seconds: int = Field(default=240, ge=1, le=3600)

    @field_validator("base_url", "marketing_model", "coding_model", "review_model", "embedding_model")
    @classmethod
    def non_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value


class RagSettings(SectionModel):
    db_path: str = "data/rag.sqlite3"
    top_k: int = Field(default=8, ge=1, le=100)
    warning_threshold: float = Field(default=0.78, ge=0.0, le=1.0)
    duplicate_threshold: float = Field(default=0.86, ge=0.0, le=1.0)

    @field_validator("db_path")
    @classmethod
    def non_empty_db_path(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value

    @field_validator("duplicate_threshold")
    @classmethod
    def duplicate_not_too_low(cls, value: float, info: Any) -> float:
        warning = info.data.get("warning_threshold")
        if warning is not None and value < warning:
            raise ValueError("must be greater than or equal to rag.warning_threshold")
        return value


class SocialSettings(SectionModel):
    hashtags: dict[str, list[str]] = Field(
        default_factory=lambda: {
            "instagram": ["ChildrensBooks", "PictureBooks", "ReadAloud", "IndieAuthor"],
            "facebook": [],
        }
    )
    recent_post_limit: int = Field(default=30, ge=0, le=1000)


class OrchestratorSettings(SectionModel):
    window_days: int = Field(default=1, ge=0, le=365)
    daily_run_time: str = "09:00"

    @field_validator("daily_run_time")
    @classmethod
    def valid_time(cls, value: str) -> str:
        value = value.strip()
        if not _TIME_RE.fullmatch(value):
            raise ValueError("must use 24-hour HH:MM format, e.g. 09:00")
        return value


class NotificationSettings(SectionModel):
    desktop: bool = True
    alert_webhook_env: str = "AUTHOR_AGENT_ALERT_WEBHOOK"
    alert_timeout_seconds: int = Field(default=10, ge=1, le=120)
    stale_review_days: int = Field(default=3, ge=1, le=365)


class WebSettings(SectionModel):
    url: str = "http://127.0.0.1:8765"
    push_token_ttl_seconds: int = Field(default=3600, ge=60, le=86400)


class WebsiteSettings(SectionModel):
    repo_path: str = ""
    calendar_data_file: str = ""
    branch_prefix: str = "author-agent"
    allow_commit: bool = True
    allow_push: bool = False

    @field_validator("branch_prefix")
    @classmethod
    def non_empty_branch_prefix(cls, value: str) -> str:
        value = value.strip().strip("/")
        if not value:
            raise ValueError("must not be empty")
        return value


class AutomationSettings(SectionModel):
    mode: str = "manual"
    db_path: str = "data/automation.sqlite3"

    @field_validator("mode")
    @classmethod
    def valid_mode(cls, value: str) -> str:
        if value not in {"manual", "approve_and_schedule", "automatic"}:
            raise ValueError("must be manual, approve_and_schedule, or automatic")
        return value


class PublishingSettings(SectionModel):
    enabled: bool = False
    provider: str = "meta"
    dry_run: bool = True
    max_retries: int = Field(default=3, ge=0, le=10)
    kill_switch_env: str = "PUBLISHING_KILL_SWITCH"


class MetaSettings(SectionModel):
    access_token_env: str = "META_ACCESS_TOKEN"
    facebook_page_id: str = ""
    instagram_account_id: str = ""
    graph_version: str = "v23.0"


class BookAnalysisSettings(SectionModel):
    multimodal_enabled: bool = False
    vision_provider: str = ""
    vision_model: str = ""
    max_pages: int = Field(default=0, ge=0, le=10000)


class AnalyticsSettings(SectionModel):
    enabled: bool = True
    minimum_samples: int = Field(default=10, ge=1, le=10000)
    refresh_hours: int = Field(default=24, ge=1, le=720)
    weights: dict[str, float] = Field(
        default_factory=lambda: {
            "shares": 3.0,
            "comments": 2.0,
            "saves": 2.5,
            "clicks": 3.0,
            "reach": 1.0,
            "likes": 0.5,
        }
    )


class CampaignSettings(SectionModel):
    timezone: str = "Europe/Prague"
    facebook_time: str = "19:00"
    instagram_time: str = "18:30"
    minimum_gap_hours: int = Field(default=18, ge=1, le=168)

    @field_validator("facebook_time", "instagram_time")
    @classmethod
    def valid_campaign_time(cls, value: str) -> str:
        value = value.strip()
        if not _TIME_RE.fullmatch(value):
            raise ValueError("must use 24-hour HH:MM format")
        return value


class EvaluationSettings(SectionModel):
    real_model_enabled: bool = False


class LoggingSettings(SectionModel):
    level: str = "INFO"

    @field_validator("level")
    @classmethod
    def valid_level(cls, value: str) -> str:
        value = value.upper().strip()
        if value not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError("must be DEBUG, INFO, WARNING, ERROR, or CRITICAL")
        return value


class Settings(SectionModel):
    ollama: OllamaSettings = Field(default_factory=OllamaSettings)
    rag: RagSettings = Field(default_factory=RagSettings)
    social: SocialSettings = Field(default_factory=SocialSettings)
    orchestrator: OrchestratorSettings = Field(default_factory=OrchestratorSettings)
    notifications: NotificationSettings = Field(default_factory=NotificationSettings)
    web: WebSettings = Field(default_factory=WebSettings)
    website: WebsiteSettings = Field(default_factory=WebsiteSettings)
    automation: AutomationSettings = Field(default_factory=AutomationSettings)
    publishing: PublishingSettings = Field(default_factory=PublishingSettings)
    meta: MetaSettings = Field(default_factory=MetaSettings)
    book_analysis: BookAnalysisSettings = Field(default_factory=BookAnalysisSettings)
    analytics: AnalyticsSettings = Field(default_factory=AnalyticsSettings)
    campaign: CampaignSettings = Field(default_factory=CampaignSettings)
    evaluation: EvaluationSettings = Field(default_factory=EvaluationSettings)
    logging: LoggingSettings = Field(default_factory=LoggingSettings)

    def legacy_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="python")


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise ConfigError(f"Could not load configuration `{path}`: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"Configuration `{path}` must contain a YAML object at the top level.")
    return data


def _parse_env_value(raw: str) -> Any:
    try:
        return yaml.safe_load(raw)
    except yaml.YAMLError:
        return raw


def _environment_overrides() -> dict[str, Any]:
    overrides: dict[str, Any] = {}
    prefix = "AUTHOR_AGENT__"
    for key, raw in os.environ.items():
        if not key.startswith(prefix):
            continue
        path = [part.lower() for part in key[len(prefix) :].split("__") if part]
        if not path:
            continue
        cursor = overrides
        for part in path[:-1]:
            cursor = cursor.setdefault(part, {})
        cursor[path[-1]] = _parse_env_value(raw)
    repo = os.getenv("AUTHOR_AGENT_WEBSITE_REPO")
    if repo:
        overrides.setdefault("website", {})["repo_path"] = repo
    log_level = os.getenv("AUTHOR_AGENT_LOG_LEVEL")
    if log_level:
        overrides.setdefault("logging", {})["level"] = log_level
    return overrides


def load_settings(root: Path = ROOT) -> Settings:
    data = _read_yaml(root / "config/settings.yaml")
    data = _deep_merge(data, _read_yaml(root / "config/settings.local.yaml"))
    data = _deep_merge(data, _environment_overrides())
    try:
        settings = Settings.model_validate(data)
        if settings.publishing.enabled and not settings.publishing.dry_run:
            token = os.getenv(settings.meta.access_token_env, "").strip()
            if not token:
                raise ConfigError(
                    "Live Meta publishing is enabled but no access token is configured. "
                    f"Set {settings.meta.access_token_env} or restore publishing.dry_run=true."
                )
            if not (settings.meta.facebook_page_id.strip() or settings.meta.instagram_account_id.strip()):
                raise ConfigError(
                    "Live Meta publishing is enabled but no target account is configured. "
                    "Set meta.facebook_page_id or meta.instagram_account_id, or restore publishing.dry_run=true."
                )
        return settings
    except PydanticValidationError as exc:
        errors = "; ".join(f"{'.'.join(str(part) for part in item['loc'])}: {item['msg']}" for item in exc.errors())
        raise ConfigError(f"Invalid Author Agent configuration: {errors}") from exc


SETTINGS_MODEL = load_settings()
