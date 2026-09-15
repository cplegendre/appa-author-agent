from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from typing import Callable

import httpx

from author_agent.logging_utils import log_json_event, redact_text

from .base import PublishRequest, PublishResult

LOG = logging.getLogger(__name__)


class PublishingError(RuntimeError):
    pass


class RetryablePublishingError(PublishingError):
    pass


class RateLimitPublishingError(RetryablePublishingError):
    pass


class ExpiredTokenPublishingError(PublishingError):
    pass


class InvalidMediaPublishingError(PublishingError):
    pass


class PublishingKillSwitchError(PublishingError):
    pass


@dataclass(frozen=True)
class MetaConfig:
    access_token: str = ""
    facebook_page_id: str = ""
    instagram_account_id: str = ""
    graph_version: str = "v23.0"
    timeout_seconds: int = 30
    dry_run: bool = True
    max_retries: int = 3
    kill_switch_env: str = "PUBLISHING_KILL_SWITCH"


class MetaPublisher:
    def __init__(
        self,
        config: MetaConfig,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.config = config
        self.client = client or httpx.Client(timeout=config.timeout_seconds)
        self.sleep = sleep

    @property
    def base_url(self) -> str:
        return f"https://graph.facebook.com/{self.config.graph_version}"

    def _token(self) -> str:
        if not self.config.access_token:
            raise PublishingError("Meta access token is not configured")
        return self.config.access_token

    def _kill_switch_active(self) -> bool:
        raw = os.getenv(self.config.kill_switch_env, "").strip().lower()
        return raw in {"1", "true", "yes", "on"}

    def _assert_publication_allowed(self) -> None:
        if not self.config.dry_run and self._kill_switch_active():
            raise PublishingKillSwitchError(
                f"Publishing blocked by global kill-switch {self.config.kill_switch_env}=true"
            )

    def validate_credentials(self) -> bool:
        if self.config.dry_run and not self.config.access_token:
            return True
        response = self.client.get(f"{self.base_url}/me", params={"access_token": self._token()})
        if response.status_code >= 400:
            self._raise_meta_error(response)
        return True

    @staticmethod
    def _error_details(response: httpx.Response) -> tuple[str, int | None, int | None]:
        message = "Meta API request failed"
        code = None
        subcode = None
        try:
            body = response.json()
            error = body.get("error", {}) if isinstance(body, dict) else {}
            if isinstance(error, dict):
                message = str(error.get("message") or message)[:300]
                raw_code = error.get("code")
                raw_subcode = error.get("error_subcode")
                code = int(raw_code) if isinstance(raw_code, int | str) and str(raw_code).isdigit() else None
                subcode = (
                    int(raw_subcode)
                    if isinstance(raw_subcode, int | str) and str(raw_subcode).isdigit()
                    else None
                )
        except (ValueError, TypeError):
            pass
        return redact_text(message), code, subcode

    def _raise_meta_error(self, response: httpx.Response) -> None:
        message, code, subcode = self._error_details(response)
        lower = message.lower()
        suffix = f" (HTTP {response.status_code})"
        if response.status_code == 429 or code in {4, 17, 32, 613}:
            raise RateLimitPublishingError(f"{message}{suffix}")
        if code == 190 or subcode in {458, 459, 460, 463, 464, 467} or "expired" in lower and "token" in lower:
            raise ExpiredTokenPublishingError(f"{message}{suffix}")
        if code == 100 and any(term in lower for term in ("image", "media", "url")):
            raise InvalidMediaPublishingError(f"{message}{suffix}")
        if any(term in lower for term in ("invalid media", "invalid image", "image url", "media url")):
            raise InvalidMediaPublishingError(f"{message}{suffix}")
        if response.status_code >= 500:
            raise RetryablePublishingError(f"{message}{suffix}")
        raise PublishingError(f"{message}{suffix}")

    def _request(self, method: str, url: str, *, data: dict, publication: bool = False) -> dict:
        safe_data = dict(data)
        token = self._token()
        total_attempts = self.config.max_retries + 1
        for attempt in range(total_attempts):
            if publication:
                # Read dynamically for every outbound publication call/retry so operators
                # can stop a running process without restarting it.
                self._assert_publication_allowed()
            request_data = safe_data | {"access_token": token}
            attempt_no = attempt + 1
            try:
                if method.upper() == "GET":
                    response = self.client.request(method, url, params=request_data)
                else:
                    response = self.client.request(method, url, data=request_data)
            except httpx.RequestError as exc:
                exhausted = attempt >= self.config.max_retries
                reason = "timeout" if isinstance(exc, httpx.TimeoutException) else "network_error"
                log_json_event(
                    LOG, logging.ERROR if exhausted else logging.WARNING, "meta_api_attempt",
                    outcome="failure", reason=reason, attempt=attempt_no, attempts=total_attempts,
                    retry_exhausted=exhausted, publication=publication,
                )
                if not exhausted:
                    self.sleep(min(2**attempt, 8))
                    continue
                raise RetryablePublishingError(
                    f"Meta API {reason} after {total_attempts} attempt(s): {redact_text(exc)}"
                ) from exc

            if response.status_code < 400:
                log_json_event(
                    LOG, logging.INFO, "meta_api_attempt", outcome="success", attempt=attempt_no,
                    attempts=total_attempts, http_status=response.status_code, publication=publication,
                )
                return response.json()

            retryable = response.status_code == 429 or response.status_code >= 500
            _, code, _ = self._error_details(response)
            retryable = retryable or code in {4, 17, 32, 613}
            exhausted = retryable and attempt >= self.config.max_retries
            log_json_event(
                LOG, logging.ERROR if exhausted or not retryable else logging.WARNING, "meta_api_attempt",
                outcome="failure",
                reason=(
                    "rate_limit"
                    if response.status_code == 429 or code in {4, 17, 32, 613}
                    else "http_error"
                ),
                attempt=attempt_no, attempts=total_attempts, http_status=response.status_code,
                retry_exhausted=exhausted, publication=publication,
            )
            if retryable and not exhausted:
                self.sleep(min(2**attempt, 8))
                continue
            self._raise_meta_error(response)
        raise RetryablePublishingError("Meta API retry budget exhausted")

    def publish_post(self, request: PublishRequest) -> PublishResult:
        if self.config.dry_run:
            return PublishResult(
                external_id=f"dry-run:{request.idempotency_key or 'post'}",
                status="published",
                raw={"dry_run": True},
            )
        if request.platform == "facebook":
            if not self.config.facebook_page_id:
                raise PublishingError("Facebook Page ID is not configured")
            payload = {"message": request.text}
            if request.media_url:
                payload["url"] = request.media_url
                path = "photos"
            else:
                path = "feed"
            body = self._request(
                "POST",
                f"{self.base_url}/{self.config.facebook_page_id}/{path}",
                data=payload,
                publication=True,
            )
            return PublishResult(external_id=str(body["id"]), status="published", raw=body)
        if request.platform == "instagram":
            if not self.config.instagram_account_id:
                raise PublishingError("Instagram account ID is not configured")
            if not request.media_url:
                raise PublishingError("Instagram publishing requires a publicly reachable media URL")
            container = self._request(
                "POST",
                f"{self.base_url}/{self.config.instagram_account_id}/media",
                data={"caption": request.text, "image_url": request.media_url},
                publication=True,
            )
            body = self._request(
                "POST",
                f"{self.base_url}/{self.config.instagram_account_id}/media_publish",
                data={"creation_id": container["id"]},
                publication=True,
            )
            return PublishResult(external_id=str(body["id"]), status="published", raw=body)
        raise PublishingError(f"Unsupported Meta platform: {request.platform}")

    def schedule_post(self, request: PublishRequest) -> PublishResult:
        if request.scheduled_at is None:
            return self.publish_post(request)
        if request.platform == "facebook" and not self.config.dry_run:
            if not self.config.facebook_page_id:
                raise PublishingError("Facebook Page ID is not configured")
            body = self._request(
                "POST",
                f"{self.base_url}/{self.config.facebook_page_id}/feed",
                data={
                    "message": request.text,
                    "published": "false",
                    "scheduled_publish_time": int(request.scheduled_at.timestamp()),
                },
                publication=True,
            )
            return PublishResult(external_id=str(body["id"]), status="scheduled", raw=body)
        if self.config.dry_run:
            return PublishResult(
                external_id=f"dry-run:{request.idempotency_key or 'scheduled'}",
                status="scheduled",
                raw={"dry_run": True},
            )
        return PublishResult(
            external_id=request.idempotency_key,
            status="scheduled",
            raw={"deferred_by_author_agent": True},
        )

    def get_post_status(self, external_id: str, platform: str) -> str:
        if self.config.dry_run:
            return "published"
        body = self._request("GET", f"{self.base_url}/{external_id}", data={})
        return str(body.get("status_type") or body.get("media_type") or "published")

    @staticmethod
    def normalize_metrics(metrics: dict[str, float]) -> dict[str, float]:
        """Map provider-specific metric names onto the analytics vocabulary."""
        aliases = {
            "saved": "saves",
            "post_impressions_unique": "reach",
            "post_impressions": "impressions",
            "impressions": "impressions",
        }
        normalized: dict[str, float] = {}
        for key, value in metrics.items():
            target = aliases.get(key, key)
            normalized[target] = normalized.get(target, 0.0) + float(value)
        return normalized

    def preflight(self, platform: str, media_url: str | None = None) -> dict:
        """Validate credentials, target account and remote media before a live campaign."""
        if platform not in {"facebook", "instagram"}:
            raise PublishingError(f"Unsupported Meta platform: {platform}")
        if self.config.dry_run:
            return {
                "ok": True,
                "dry_run": True,
                "platform": platform,
                "target": "configured" if (
                    self.config.facebook_page_id if platform == "facebook" else self.config.instagram_account_id
                ) else "missing",
                "media_checked": False,
            }
        self.validate_credentials()
        target_id = self.config.facebook_page_id if platform == "facebook" else self.config.instagram_account_id
        if not target_id:
            raise PublishingError(f"{platform.title()} target account is not configured")
        fields = "id,name" if platform == "facebook" else "id,username"
        target = self._request("GET", f"{self.base_url}/{target_id}", data={"fields": fields})
        media = {"checked": False}
        if media_url:
            try:
                response = self.client.head(media_url, follow_redirects=True)
                if response.status_code >= 400:
                    raise InvalidMediaPublishingError(f"Media URL returned HTTP {response.status_code}")
                content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                if platform == "instagram" and content_type and not content_type.startswith("image/"):
                    raise InvalidMediaPublishingError(
                        f"Instagram image URL returned unsupported content type: {content_type}"
                    )
                media = {"checked": True, "status_code": response.status_code, "content_type": content_type}
            except httpx.HTTPError as exc:
                raise InvalidMediaPublishingError(f"Media URL is not reachable: {exc}") from exc
        elif platform == "instagram":
            raise InvalidMediaPublishingError("Instagram preflight requires a publicly reachable media URL")
        return {
            "ok": True,
            "dry_run": False,
            "platform": platform,
            "target": {key: target.get(key) for key in ("id", "name", "username") if target.get(key)},
            "media": media,
        }

    def fetch_metrics(self, external_id: str, platform: str) -> dict[str, float]:
        if self.config.dry_run:
            return {}
        names = (
            "impressions,reach,likes,comments,shares,saved"
            if platform == "instagram"
            else "post_impressions,post_impressions_unique"
        )
        body = self._request("GET", f"{self.base_url}/{external_id}/insights", data={"metric": names})
        metrics: dict[str, float] = {}
        for item in body.get("data", []):
            values = item.get("values") or []
            if values:
                value = values[-1].get("value", 0)
                if isinstance(value, (int, float)):
                    metrics[str(item.get("name"))] = float(value)
        return self.normalize_metrics(metrics)
