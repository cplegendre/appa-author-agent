from __future__ import annotations

import logging
import re
import subprocess
import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

from .errors import ConfigError
from .io_utils import load_json
from .logging_utils import log_event
from .main import ROOT, SETTINGS, configure_logging, today_cmd
from .notifications import send_desktop_notification
from .alerting import slack_webhook_alerter
from .persistence import AutomationStore
from .workflow import WorkflowService

LOG = logging.getLogger(__name__)
_TIME_RE = re.compile(r"^(?:[01]\d|2[0-3]):[0-5]\d$")


def validate_daily_run_time(value: str) -> str:
    value = str(value or "").strip()
    if not _TIME_RE.fullmatch(value):
        raise ConfigError("orchestrator.daily_run_time must use 24-hour HH:MM format, e.g. `09:00`.")
    return value


def _daemon_log_handler() -> logging.Handler:
    path = ROOT / "output" / "daemon.log"
    path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    return handler


def configure_daemon_logging() -> None:
    configure_logging()
    root_logger = logging.getLogger()
    daemon_path = str((ROOT / "output" / "daemon.log").resolve())
    for handler in root_logger.handlers:
        if isinstance(handler, logging.FileHandler) and getattr(handler, "baseFilename", "") == daemon_path:
            return
    root_logger.addHandler(_daemon_log_handler())


def _notification_message(manifest: dict) -> tuple[str, str]:
    mode = str(manifest.get("mode", "draft"))
    output_path = Path(str(manifest.get("output", "")))
    data = load_json(output_path, {}) if output_path.is_file() else {}
    title = "Author Agent: draft ready"
    if mode in {"release", "teaser"}:
        book_title = str((data.get("profile") or {}).get("title") or output_path.stem)
        label = "New release draft ready" if mode == "release" else "New teaser draft ready"
        message = f"{label}: {book_title}"
    else:
        message = "New evergreen draft ready"
    web_url = SETTINGS.get("web", {}).get("url") or "http://127.0.0.1:8765"
    return title, f"{message} — review at {web_url}"



def alert_stale_reviews() -> list[dict]:
    """Alert through the existing failure-alert channel for reviews older than the configured threshold."""
    cfg = SETTINGS.get("notifications", {})
    threshold = int(cfg.get("stale_review_days", 3))
    store = AutomationStore(ROOT / SETTINGS["automation"].get("db_path", "data/automation.sqlite3"))
    service = WorkflowService(store)
    stale = service.stale_reviews(threshold)
    if not stale:
        return []
    notify = slack_webhook_alerter(
        env_name=cfg.get("alert_webhook_env", "AUTHOR_AGENT_ALERT_WEBHOOK"),
        timeout_seconds=int(cfg.get("alert_timeout_seconds", 10)),
    )
    for item in stale:
        notify({
            "event_type": "stale_review",
            "workflow_id": item["id"],
            "platform": item["platform"],
            "reason": f"review pending for {item['age_days']} days (threshold {threshold})",
        })
        log_event(
            LOG, logging.WARNING, "stale_review_alert", workflow_id=item["id"],
            platform=item["platform"], age_days=item["age_days"], threshold_days=threshold,
        )
    return stale

def run_daily_once(*, run_date: str | None = None) -> dict:
    """Run existing today_cmd once. Idempotency is owned by today_cmd's manifest check."""
    configure_daemon_logging()
    chosen = run_date or date.today().isoformat()
    manifest_path = ROOT / "output" / f"today-{chosen}.json"
    existed_before = manifest_path.exists()
    log_event(LOG, logging.INFO, "daemon_run_started", date=chosen)
    try:
        alert_stale_reviews()
    except Exception:
        # Review reminders are operational observability; they must never stop draft generation.
        LOG.exception("stale_review_check_failed date=%s", chosen)
    args = SimpleNamespace(
        date=chosen,
        window=int(SETTINGS.get("orchestrator", {}).get("window_days", 1)),
        force=False,
        dry_run=False,
        # Background generation must never mutate Git. Review/Prepare remains explicit in the UI/CLI.
        website_dry_run=True,
    )
    try:
        manifest = today_cmd(args)
    except Exception:
        LOG.exception("daemon_run_failed date=%s", chosen)
        raise
    generated = not existed_before and manifest_path.exists()
    if generated:
        log_event(
            LOG,
            logging.INFO,
            "daemon_output_generated",
            date=chosen,
            mode=manifest.get("mode"),
            output=manifest.get("output"),
        )
        if SETTINGS.get("notifications", {}).get("desktop", True):
            title, message = _notification_message(manifest)
            delivered = send_desktop_notification(title, message)
            log_event(LOG, logging.INFO, "desktop_notification", delivered=delivered, date=chosen)
    else:
        log_event(LOG, logging.INFO, "daemon_noop_existing_manifest", date=chosen)
    return {**manifest, "generated": generated}


def systemd_service_text(project_dir: Path | None = None, python_executable: str | None = None) -> str:
    project = (project_dir or ROOT).resolve()
    python_bin = python_executable or sys.executable
    lines = [
        "[Unit]",
        "Description=Author Agent daily content check",
        "After=default.target",
        "",
        "[Service]",
        "Type=oneshot",
        f"WorkingDirectory={project}",
        f'ExecStart="{python_bin}" "{project / "run_daemon.py"}" --run-once',
        "Environment=PYTHONUNBUFFERED=1",
        f"EnvironmentFile=-{project / '.env'}",
        "StandardOutput=journal",
        "StandardError=journal",
        "",
    ]
    return "\n".join(lines)


def systemd_timer_text(run_time: str) -> str:
    validated = validate_daily_run_time(run_time)
    lines = [
        "[Unit]",
        f"Description=Run Author Agent daily at {validated}",
        "",
        "[Timer]",
        f"OnCalendar=*-*-* {validated}:00",
        "Persistent=true",
        "Unit=author-agent.service",
        "",
        "[Install]",
        "WantedBy=timers.target",
        "",
    ]
    return "\n".join(lines)


def install_systemd_user_units(*, home: Path | None = None, reload_systemd: bool = True) -> tuple[Path, Path]:
    cfg = SETTINGS.get("orchestrator", {})
    run_time = validate_daily_run_time(cfg.get("daily_run_time", "09:00"))
    base = (home or Path.home()) / ".config" / "systemd" / "user"
    base.mkdir(parents=True, exist_ok=True)
    service = base / "author-agent.service"
    timer = base / "author-agent.timer"
    service.write_text(systemd_service_text(), encoding="utf-8")
    timer.write_text(systemd_timer_text(run_time), encoding="utf-8")
    if reload_systemd:
        try:
            subprocess.run(["systemctl", "--user", "daemon-reload"], check=True, capture_output=True, text=True)
        except FileNotFoundError as exc:
            raise ConfigError("`systemctl` was not found. systemd user timers are required for installation.") from exc
        except subprocess.CalledProcessError as exc:
            detail = (exc.stderr or exc.stdout or str(exc)).strip()
            raise ConfigError(f"Could not reload systemd user units: {detail}") from exc
    return service, timer
