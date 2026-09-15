from __future__ import annotations

import sys

import author_agent.daemon_runner as daemon_runner
import author_agent.web_runner as web_runner


def test_web_runner_parses_port_and_binds_localhost(monkeypatch):
    seen = {}
    monkeypatch.setattr(sys, "argv", ["author-agent-web", "--port", "9001"])
    monkeypatch.setattr(web_runner.uvicorn, "run", lambda app, **kwargs: seen.update(app=app, **kwargs))
    web_runner.main()
    assert seen == {
        "app": "author_agent.web:app",
        "host": "127.0.0.1",
        "port": 9001,
        "reload": False,
    }


def test_daemon_runner_install_path(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["author-agent-daemon", "--install-systemd"])
    monkeypatch.setattr(
        daemon_runner,
        "install_systemd_user_units",
        lambda: ("/tmp/author-agent.service", "/tmp/author-agent.timer"),
    )
    daemon_runner.main()
    out = capsys.readouterr().out
    assert "author-agent.service" in out
    assert "enable --now author-agent.timer" in out


def test_daemon_runner_executes_one_shot_with_date(monkeypatch, capsys):
    seen = {}
    monkeypatch.setattr(sys, "argv", ["author-agent-daemon", "--run-once", "--date", "2026-09-14"])
    monkeypatch.setattr(
        daemon_runner,
        "run_daily_once",
        lambda **kwargs: seen.update(kwargs) or {"mode": "release", "generated": True, "output": "x.json"},
    )
    daemon_runner.main()
    assert seen == {"run_date": "2026-09-14"}
    assert "generated=True" in capsys.readouterr().out
