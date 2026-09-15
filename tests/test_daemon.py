from __future__ import annotations


import pytest

import author_agent.daemon as daemon
import author_agent.notifications as notifications
from author_agent.io_utils import save_json


def test_validate_daily_run_time():
    assert daemon.validate_daily_run_time("09:00") == "09:00"
    assert daemon.validate_daily_run_time("23:59") == "23:59"
    for bad in ("9:00", "24:00", "12:60", "nope"):
        with pytest.raises(ValueError):
            daemon.validate_daily_run_time(bad)


def test_run_daily_once_generates_and_notifies(monkeypatch, tmp_path):
    monkeypatch.setattr(daemon, "ROOT", tmp_path)
    monkeypatch.setattr(
        daemon,
        "SETTINGS",
        {
            "orchestrator": {"window_days": 2},
            "notifications": {"desktop": True},
            "web": {"url": "http://127.0.0.1:8765"},
        },
    )
    seen = {}

    def fake_today(args):
        seen["args"] = args
        output = tmp_path / "output" / "release-2026-09-14.json"
        save_json(output, {"profile": {"title": "Bilingual Yok 4"}})
        manifest = tmp_path / "output" / "today-2026-09-14.json"
        data = {"date": "2026-09-14", "mode": "release", "output": str(output), "approved": False}
        save_json(manifest, data)
        return data

    monkeypatch.setattr(daemon, "today_cmd", fake_today)
    monkeypatch.setattr(daemon, "configure_daemon_logging", lambda: None)
    monkeypatch.setattr(
        daemon,
        "send_desktop_notification",
        lambda title, message: seen.update(title=title, message=message) or True,
    )
    result = daemon.run_daily_once(run_date="2026-09-14")
    assert result["generated"] is True
    assert "Bilingual Yok 4" in seen["message"]
    assert "127.0.0.1:8765" in seen["message"]
    assert seen["args"].window == 2
    assert seen["args"].force is False
    assert seen["args"].website_dry_run is True


def test_run_daily_once_existing_manifest_is_idempotent(monkeypatch, tmp_path):
    monkeypatch.setattr(daemon, "ROOT", tmp_path)
    monkeypatch.setattr(daemon, "SETTINGS", {"orchestrator": {"window_days": 1}, "notifications": {"desktop": True}})
    manifest = tmp_path / "output" / "today-2026-09-14.json"
    output = tmp_path / "output" / "evergreen-2026-09-14.json"
    save_json(output, {"facebook": "F", "instagram": "I"})
    data = {"date": "2026-09-14", "mode": "evergreen", "output": str(output)}
    save_json(manifest, data)
    monkeypatch.setattr(daemon, "today_cmd", lambda args: data)
    monkeypatch.setattr(daemon, "configure_daemon_logging", lambda: None)
    monkeypatch.setattr(daemon, "send_desktop_notification", lambda *a: pytest.fail("notification should not run"))
    result = daemon.run_daily_once(run_date="2026-09-14")
    assert result["generated"] is False


def test_systemd_text_and_install(monkeypatch, tmp_path):
    monkeypatch.setattr(daemon, "ROOT", tmp_path / "project")
    monkeypatch.setattr(daemon, "SETTINGS", {"orchestrator": {"daily_run_time": "08:35"}})
    calls = []
    monkeypatch.setattr(daemon.subprocess, "run", lambda cmd, **kwargs: calls.append(cmd))
    service, timer = daemon.install_systemd_user_units(home=tmp_path / "home")
    assert "run_daemon.py" in service.read_text()
    assert "OnCalendar=*-*-* 08:35:00" in timer.read_text()
    assert calls == [["systemctl", "--user", "daemon-reload"]]


def test_notify_send_success_and_no_session(monkeypatch):
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.delenv("DBUS_SESSION_BUS_ADDRESS", raising=False)
    assert notifications.send_desktop_notification("Title", "Message") is False

    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setattr(notifications.shutil, "which", lambda name: "/usr/bin/notify-send")
    seen = {}

    class Proc:
        returncode = 0
        stderr = ""
        stdout = ""

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        return Proc()

    monkeypatch.setattr(notifications.subprocess, "run", fake_run)
    assert notifications.send_desktop_notification("Draft ready", "Review at localhost") is True
    assert seen["cmd"][0] == "/usr/bin/notify-send"
    assert "Draft ready" in seen["cmd"]
