from __future__ import annotations

import argparse

from .daemon import install_systemd_user_units, run_daily_once


def main() -> None:
    parser = argparse.ArgumentParser(description="Author Agent systemd-triggered daily runner.")
    parser.add_argument("--run-once", action="store_true", help="Run today's orchestrator once and exit (default).")
    parser.add_argument("--install-systemd", action="store_true", help="Install/update user service + timer units.")
    parser.add_argument("--date", default="", help="Optional YYYY-MM-DD override for testing/manual trigger.")
    args = parser.parse_args()
    if args.install_systemd:
        service, timer = install_systemd_user_units()
        print(
            f"Installed: {service}\nInstalled: {timer}\nEnable with: systemctl --user enable --now author-agent.timer"
        )
        return
    result = run_daily_once(run_date=args.date or None)
    print(
        "Author Agent daily check: "
        f"mode={result.get('mode')} generated={result.get('generated')} output={result.get('output')}"
    )
