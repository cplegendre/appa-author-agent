from __future__ import annotations

import subprocess
from types import SimpleNamespace

import author_agent.notifications as notifications


def _clear_desktop_env(monkeypatch):
    for name in ("DISPLAY", "WAYLAND_DISPLAY", "DBUS_SESSION_BUS_ADDRESS"):
        monkeypatch.delenv(name, raising=False)


def test_notification_skips_without_any_desktop_session(monkeypatch, caplog):
    _clear_desktop_env(monkeypatch)
    assert notifications.send_desktop_notification("Title", "Message") is False
    assert "no desktop session" in caplog.text.lower()


def test_notification_uses_wayland_without_display(monkeypatch):
    _clear_desktop_env(monkeypatch)
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-0")
    monkeypatch.setattr(notifications.shutil, "which", lambda _: "/usr/bin/notify-send")
    monkeypatch.setattr(
        notifications.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )
    assert notifications.send_desktop_notification("Title", "Message") is True


def test_notification_uses_dbus_without_display_or_wayland(monkeypatch):
    _clear_desktop_env(monkeypatch)
    monkeypatch.setenv("DBUS_SESSION_BUS_ADDRESS", "unix:path=/run/user/1000/bus")
    monkeypatch.setattr(notifications.shutil, "which", lambda _: "/usr/bin/notify-send")
    monkeypatch.setattr(
        notifications.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout="", stderr=""),
    )
    assert notifications.send_desktop_notification("Title", "Message") is True


def test_notification_skips_when_notify_send_missing(monkeypatch, caplog):
    _clear_desktop_env(monkeypatch)
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setattr(notifications.shutil, "which", lambda _: None)
    assert notifications.send_desktop_notification("Title", "Message") is False
    assert "not installed" in caplog.text.lower()


def test_notification_nonzero_exit_logs_detail(monkeypatch, caplog):
    _clear_desktop_env(monkeypatch)
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setattr(notifications.shutil, "which", lambda _: "/usr/bin/notify-send")
    monkeypatch.setattr(
        notifications.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout="", stderr="dbus unavailable\n"),
    )
    assert notifications.send_desktop_notification("Title", "Message") is False
    assert "dbus unavailable" in caplog.text.lower()


def test_notification_nonzero_exit_uses_stdout_fallback(monkeypatch, caplog):
    _clear_desktop_env(monkeypatch)
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setattr(notifications.shutil, "which", lambda _: "/usr/bin/notify-send")
    monkeypatch.setattr(
        notifications.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=2, stdout="fallback detail\n", stderr=""),
    )
    assert notifications.send_desktop_notification("Title", "Message") is False
    assert "fallback detail" in caplog.text.lower()


def test_notification_timeout_is_best_effort(monkeypatch, caplog):
    _clear_desktop_env(monkeypatch)
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setattr(notifications.shutil, "which", lambda _: "/usr/bin/notify-send")

    def raise_timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="notify-send", timeout=10)

    monkeypatch.setattr(notifications.subprocess, "run", raise_timeout)
    assert notifications.send_desktop_notification("Title", "Message") is False
    assert "failed" in caplog.text.lower()


def test_notification_oserror_is_best_effort(monkeypatch, caplog):
    _clear_desktop_env(monkeypatch)
    monkeypatch.setenv("DISPLAY", ":0")
    monkeypatch.setattr(notifications.shutil, "which", lambda _: "/usr/bin/notify-send")

    def raise_oserror(*args, **kwargs):
        raise OSError("cannot execute")

    monkeypatch.setattr(notifications.subprocess, "run", raise_oserror)
    assert notifications.send_desktop_notification("Title", "Message") is False
    assert "cannot execute" in caplog.text.lower()
