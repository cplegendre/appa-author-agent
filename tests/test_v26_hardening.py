from __future__ import annotations

import logging
from pathlib import Path

import httpx
import pytest

from author_agent.config import ConfigError, Settings, load_settings
from author_agent.demo import run_demo
from author_agent.logging_utils import install_secret_redaction, log_event
from author_agent.publishing import (
    ExpiredTokenPublishingError,
    InvalidMediaPublishingError,
    MetaConfig,
    MetaPublisher,
    PublishRequest,
    RateLimitPublishingError,
)


def test_live_config_fails_fast_without_token(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AUTHOR_AGENT__PUBLISHING__ENABLED", "true")
    monkeypatch.setenv("AUTHOR_AGENT__PUBLISHING__DRY_RUN", "false")
    monkeypatch.setenv("AUTHOR_AGENT__META__FACEBOOK_PAGE_ID", "test-page")
    monkeypatch.delenv("META_ACCESS_TOKEN", raising=False)
    with pytest.raises(ConfigError, match="no access token"):
        load_settings(tmp_path)


def test_live_config_fails_fast_without_target(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("AUTHOR_AGENT__PUBLISHING__ENABLED", "true")
    monkeypatch.setenv("AUTHOR_AGENT__PUBLISHING__DRY_RUN", "false")
    monkeypatch.setenv("META_ACCESS_TOKEN", "fake-live-token")
    monkeypatch.delenv("AUTHOR_AGENT__META__FACEBOOK_PAGE_ID", raising=False)
    monkeypatch.delenv("AUTHOR_AGENT__META__INSTAGRAM_ACCOUNT_ID", raising=False)
    with pytest.raises(ConfigError, match="no target account"):
        load_settings(tmp_path)


def _response(status: int, message: str, *, code: int, subcode: int | None = None) -> httpx.Response:
    error: dict[str, object] = {"message": message, "code": code}
    if subcode is not None:
        error["error_subcode"] = subcode
    return httpx.Response(status, json={"error": error})


def test_meta_rate_limit_payload_maps_to_domain_error() -> None:
    client = httpx.Client(transport=httpx.MockTransport(lambda _: _response(429, "Too many calls", code=4)))
    publisher = MetaPublisher(
        MetaConfig(access_token="secret", facebook_page_id="page", dry_run=False, max_retries=0),
        client=client,
    )
    with pytest.raises(RateLimitPublishingError, match="Too many calls"):
        publisher.publish_post(PublishRequest(platform="facebook", text="test"))


def test_meta_expired_token_payload_maps_to_domain_error() -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(lambda _: _response(400, "Session has expired", code=190, subcode=463))
    )
    publisher = MetaPublisher(
        MetaConfig(access_token="secret", facebook_page_id="page", dry_run=False),
        client=client,
    )
    with pytest.raises(ExpiredTokenPublishingError, match="expired"):
        publisher.publish_post(PublishRequest(platform="facebook", text="test"))


def test_meta_invalid_media_payload_maps_to_domain_error() -> None:
    client = httpx.Client(
        transport=httpx.MockTransport(lambda _: _response(400, "Invalid image URL", code=100))
    )
    publisher = MetaPublisher(
        MetaConfig(access_token="secret", facebook_page_id="page", dry_run=False),
        client=client,
    )
    with pytest.raises(InvalidMediaPublishingError, match="Invalid image URL"):
        publisher.publish_post(
            PublishRequest(platform="facebook", text="test", media_url="https://invalid.example/image.jpg")
        )


def test_secret_never_appears_in_captured_logs(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    token = "EAAB_FAKE_SUPER_SECRET_TOKEN_12345"
    monkeypatch.setenv("META_ACCESS_TOKEN", token)
    monkeypatch.setenv("AUTHOR_AGENT__META__SECONDARY_SECRET", "other-secret")
    logger = logging.getLogger("author_agent.secret_test")
    install_secret_redaction(logger)
    with caplog.at_level(logging.DEBUG, logger=logger.name):
        log_event(logger, logging.DEBUG, "debug_event", token=token, nested=f"Bearer {token}")
        try:
            raise RuntimeError(f"remote failure access_token={token}")
        except RuntimeError:
            logger.exception("provider failed token=%s", token)
    assert token not in caplog.text
    assert "other-secret" not in caplog.text
    assert "[REDACTED]" in caplog.text


def test_demo_pipeline_reaches_dry_run_publish(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("author_agent.demo._ollama_available", lambda settings: False)
    lines: list[str] = []
    result = run_demo(settings=Settings(), output=lines.append)
    assert result["state"] == "PUBLISHED"
    assert result["external_id"].startswith("dry-run:")
    assert "mocked deterministic generator" in result["generator_mode"]
    assert any("Grounding: PASS" in line for line in lines)
    assert any("External network posts created: 0" in line for line in lines)
