from __future__ import annotations

from pathlib import Path
from typing import Any

from .errors import ValidationError
from .io_utils import load_json


def safe_output(output_dir: Path, name: str) -> Path:
    if Path(name).name != name or not name.endswith(".json"):
        raise ValidationError("Invalid output file name.")
    path = (output_dir / name).resolve()
    root = output_dir.resolve()
    if root not in path.parents:
        raise ValidationError("Output file is outside the allowed output directory.")
    if not path.is_file():
        raise ValidationError(f"Output file not found: {name}")
    return path


def serialize_output(path: Path) -> dict:
    return {"output_file": path.name, "data": load_json(path, {})}


def history_mode(data: dict) -> str:
    if isinstance(data.get("profile"), dict):
        return "release" if data.get("published") else "teaser"
    return "evergreen"


def website_push_status(data: dict) -> str:
    raw_website = data.get("website")
    website: dict[str, Any] = raw_website if isinstance(raw_website, dict) else {}
    if website.get("push_performed") or website.get("status") == "pushed":
        return "pushed"
    if website.get("status") in {"prepared", "unchanged"}:
        return "prepared"
    if isinstance(data.get("profile"), dict) and data.get("published"):
        return "not-pushed"
    return "not-applicable"


def history_items(output_dir: Path, filter_name: str = "all") -> list[dict]:
    if filter_name not in {"all", "needs_review", "approved"}:
        raise ValidationError("History filter must be all, needs_review, or approved.")
    if not output_dir.exists():
        return []
    items: list[dict] = []
    for path in output_dir.glob("*.json"):
        if path.name.startswith("today-"):
            continue
        data = load_json(path, None)
        if not isinstance(data, dict):
            continue
        if not (isinstance(data.get("profile"), dict) or data.get("facebook") or data.get("instagram")):
            continue
        approved = bool(data.get("approved"))
        if filter_name == "needs_review" and approved:
            continue
        if filter_name == "approved" and not approved:
            continue
        raw_profile = data.get("profile")
        profile: dict[str, Any] = raw_profile if isinstance(raw_profile, dict) else {}
        items.append(
            {
                "output_file": path.name,
                "date": str(data.get("date") or data.get("release_date") or ""),
                "mode": history_mode(data),
                "title": str(profile.get("title") or data.get("topic") or data.get("primary_angle") or path.stem),
                "approved": approved,
                "website_push_status": website_push_status(data),
                "modified_at": path.stat().st_mtime,
            }
        )
    items.sort(key=lambda row: (row.get("date", ""), row.get("modified_at", 0)), reverse=True)
    return items
