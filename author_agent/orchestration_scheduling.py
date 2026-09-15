from __future__ import annotations

from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import yaml

from .errors import ConfigError, ValidationError
from .io_utils import load_json, save_json, validate_date


def load_releases(root: Path) -> list[dict]:
    path = root / "config/releases.yaml"
    if not path.exists():
        raise ValidationError(
            "Missing config/releases.yaml. Copy config/releases.example.yaml to "
            "config/releases.yaml and add your releases."
        )
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ValidationError(f"Malformed config/releases.yaml: {exc}") from exc
    releases = data if isinstance(data, list) else data.get("releases", [])
    if not isinstance(releases, list):
        raise ValidationError("config/releases.yaml must contain a `releases` list.")
    return releases


def release_candidates(today: date, releases: list[dict], window: int) -> list[tuple[int, dict]]:
    if window < 0:
        raise ValidationError("--window must be zero or greater.")
    parsed: list[tuple[int, dict]] = []
    for index, item in enumerate(releases):
        if not isinstance(item, dict):
            raise ValidationError(f"Release entry #{index + 1} in config/releases.yaml must be an object.")
        raw_date = str(item.get("date", ""))
        if not raw_date:
            raise ValidationError(f"Release entry #{index + 1} is missing `date`.")
        try:
            release_day = date.fromisoformat(raw_date)
        except ValueError as exc:
            raise ValidationError(
                f"Invalid release date `{raw_date}` in config/releases.yaml; expected YYYY-MM-DD."
            ) from exc
        delta = (release_day - today).days
        if 0 <= delta <= window:
            parsed.append((delta, item))
    return sorted(parsed, key=lambda pair: pair[0])


def today_cmd(args: Any, deps: Any) -> dict:
    """Select today's release/teaser/evergreen work and persist its manifest.

    Kept separate from generation/validation logic so scheduling can evolve
    operationally without making the editorial orchestration module larger.
    """
    today = date.fromisoformat(validate_date(args.date or date.today().isoformat(), "today date"))
    dry_run = bool(getattr(args, "dry_run", False))
    base_output = deps.root / "output" / "dry-run" if dry_run else deps.root / "output"
    manifest = base_output / f"today-{today.isoformat()}.json"
    if manifest.exists() and not args.force:
        data = load_json(manifest, {})
        deps.user_output(
            f"Already generated for today: {data.get('output', manifest)} "
            "(use --force to regenerate)."
        )
        return data
    parsed = release_candidates(today, load_releases(deps.root), args.window)
    if parsed:
        delta, item = parsed[0]
        if not item.get("book"):
            raise ValidationError(f"Release {item.get('date')} is missing `book` in config/releases.yaml.")
        ns = SimpleNamespace(
            book=item["book"],
            image=item.get("image", ""),
            date=str(item["date"]),
            url=item.get("url", ""),
            published=(delta == 0),
            dry_run=dry_run,
            website_dry_run=bool(getattr(args, "website_dry_run", False)),
        )
        if deps.release_cmd is None:
            raise ConfigError("Release command dependency is not configured.")
        _result, out = deps.release_cmd(ns, emit=False, run_date=today.isoformat())
        mode = "release" if delta == 0 else "teaser"
    else:
        ns = SimpleNamespace(date=today.isoformat(), image="", dry_run=dry_run)
        if deps.evergreen_cmd is None:
            raise ConfigError("Evergreen command dependency is not configured.")
        _result, out = deps.evergreen_cmd(ns, emit=False, run_date=today.isoformat())
        mode = "evergreen"
    manifest_data = {
        "date": today.isoformat(),
        "mode": mode,
        "output": str(out),
        "approved": False,
        "dry_run": dry_run,
    }
    save_json(manifest, manifest_data)
    prefix = "today dry-run" if dry_run else "today"
    deps.user_output(f"{prefix} → {mode}\nOutput: {out}\nManifest: {manifest}\nManual approval required.")
    return manifest_data
