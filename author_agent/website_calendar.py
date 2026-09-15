from __future__ import annotations

import html
import json
import re
from pathlib import Path

import yaml

from .errors import WebsiteError

SUPPORTED_SUFFIXES = {".json", ".yaml", ".yml", ".js", ".html", ".htm"}
CANDIDATES = (
    "data/releases.yaml",
    "data/releases.yml",
    "data/releases.json",
    "calendar/releases.yaml",
    "calendar/releases.yml",
    "calendar/releases.json",
    "assets/releases.json",
    "releases.yaml",
    "releases.yml",
    "releases.json",
    "calendar/data.js",
    "calendar/releases.js",
    "calendar/index.html",
)
MONTH_NAMES = (
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
)


def detect_calendar_file(repo: Path, configured: str = "") -> Path | None:
    if configured:
        target = repo / configured
        if not target.is_file():
            raise WebsiteError(f"Configured calendar file does not exist: {configured}")
        if target.suffix.lower() not in SUPPORTED_SUFFIXES:
            raise WebsiteError(
                f"Unsupported calendar file format: {target.suffix or '(none)'}. "
                "Supported formats: JSON, YAML, JS, HTML."
            )
        return target
    for candidate in CANDIDATES:
        path = repo / candidate
        if path.is_file():
            return path
    for path in [*repo.glob("calendar/*"), *repo.glob("data/*")]:
        if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES:
            return path
    return None


def validate_release_list(releases: object, path: Path) -> list[dict]:
    if not isinstance(releases, list):
        raise WebsiteError(f"Malformed calendar file {path}: 'releases' must be a list.")
    for index, entry in enumerate(releases):
        if not isinstance(entry, dict):
            raise WebsiteError(f"Malformed calendar file {path}: release entry #{index + 1} is not an object.")
    return releases


def upsert_release(releases: list[dict], release: dict) -> bool:
    validate_release_list(releases, Path("<calendar>"))
    for existing in releases:
        same_date = str(existing.get("date", "")) == release["date"]
        same_title = existing.get("title") == release["title"] or existing.get("book") == release["title"]
        if same_date and same_title:
            changed = any(existing.get(key) != value for key, value in release.items())
            if changed:
                existing.update(release)
            return changed
    releases.append(release)
    return True


def _event_class(title: str) -> str:
    lowered = title.lower()
    if "bilingual" in lowered:
        return "bilingual"
    if "luma" in lowered or "blue dreams" in lowered:
        return "luma"
    return "yok"


def _patch_html_calendar(path: Path, release: dict, original: str) -> str:
    try:
        year, month, day = [int(part) for part in release["date"].split("-")]
        month_label = f"{MONTH_NAMES[month - 1]} {year}"
    except (ValueError, IndexError) as exc:
        raise WebsiteError(f"Invalid release date for website patch: {release.get('date')!r}.") from exc

    month_pattern = re.compile(
        rf"(?P<open><article\b[^>]*class=[\"'][^\"']*\brelease-month\b[^\"']*[\"'][^>]*>\s*"
        rf"<h2>\s*{re.escape(month_label)}\s*</h2>\s*"
        rf"<div\b[^>]*class=[\"'][^\"']*\brelease-events\b[^\"']*[\"'][^>]*>)"
        rf"(?P<body>.*?)(?P<close></div>\s*</article>)",
        flags=re.IGNORECASE | re.DOTALL,
    )
    month_match = month_pattern.search(original)
    if not month_match:
        raise WebsiteError(f"Malformed or unsupported HTML calendar {path}: month block '{month_label}' was not found.")

    body = month_match.group("body")
    day_text = f"{day:02d}"
    event_pattern = re.compile(
        rf"<div(?P<attrs>[^>]*)>\s*<strong>\s*{re.escape(day_text)}\s*</strong>\s*"
        rf"<span>(?P<label>.*?)</span>\s*</div>",
        flags=re.IGNORECASE | re.DOTALL,
    )
    event_match = next(
        (
            candidate
            for candidate in event_pattern.finditer(body)
            if re.search(r"class=[\"'][^\"']*\brelease-event\b", candidate.group("attrs"), re.IGNORECASE)
        ),
        None,
    )

    safe_title = html.escape(str(release.get("title", "")), quote=True)
    title_value = f"{safe_title} — available now" if safe_title else "Available now"
    if event_match:
        attrs = event_match.group("attrs")
        if re.search(r"\btitle=[\"'].*?[\"']", attrs, flags=re.IGNORECASE | re.DOTALL):
            attrs = re.sub(
                r"\btitle=[\"'].*?[\"']",
                f'title="{title_value}"',
                attrs,
                count=1,
                flags=re.IGNORECASE | re.DOTALL,
            )
        else:
            attrs = attrs.rstrip() + f' title="{title_value}"'
        label = event_match.group("label")
        if "published" not in re.sub(r"<[^>]+>", "", label).lower():
            label = label.rstrip() + " · Published"
        replacement = f"<div{attrs}><strong>{day_text}</strong><span>{label}</span></div>"
        new_body = body[: event_match.start()] + replacement + body[event_match.end() :]
    else:
        css_class = _event_class(str(release.get("title", "")))
        label = html.escape(str(release.get("title", "Release"))) + " · Published"
        addition = (
            f'<div class="release-event {css_class}" title="{title_value}">'
            f"<strong>{day_text}</strong><span>{label}</span></div>"
        )
        new_body = body + addition
    return original[: month_match.start("body")] + new_body + original[month_match.end("body") :]


def patch_calendar_text(path: Path, release: dict, original: str) -> str:
    suffix = path.suffix.lower()
    if suffix in {".yaml", ".yml"}:
        try:
            data = yaml.safe_load(original) or {}
        except yaml.YAMLError as exc:
            raise WebsiteError(f"Malformed YAML calendar file {path}: {exc}") from exc
        if isinstance(data, list):
            releases = validate_release_list(data, path)
        elif isinstance(data, dict):
            data.setdefault("releases", [])
            releases = validate_release_list(data["releases"], path)
        else:
            raise WebsiteError(f"Malformed YAML calendar file {path}: expected a list or object.")
        if upsert_release(releases, release):
            return yaml.safe_dump(data, allow_unicode=True, sort_keys=False)
        return original

    if suffix == ".json":
        try:
            data = json.loads(original)
        except json.JSONDecodeError as exc:
            raise WebsiteError(f"Malformed JSON calendar file {path}: {exc.msg} at line {exc.lineno}.") from exc
        if isinstance(data, list):
            releases = validate_release_list(data, path)
        elif isinstance(data, dict):
            data.setdefault("releases", [])
            releases = validate_release_list(data["releases"], path)
        else:
            raise WebsiteError(f"Malformed JSON calendar file {path}: expected a list or object.")
        return json.dumps(data, ensure_ascii=False, indent=2) + "\n" if upsert_release(releases, release) else original

    if suffix == ".js":
        match = re.search(r"(?s)(?:const|let|var)\s+\w+\s*=\s*(\[.*\])\s*;?\s*$", original)
        if not match:
            raise WebsiteError(
                f"Unsupported JavaScript calendar structure in {path}. "
                "Expected `const/let/var name = [...]`; configure website.calendar_data_file if needed."
            )
        try:
            releases = validate_release_list(json.loads(match.group(1)), path)
        except json.JSONDecodeError as exc:
            raise WebsiteError(f"Malformed JavaScript calendar array in {path}: {exc.msg}.") from exc
        if not upsert_release(releases, release):
            return original
        replacement = json.dumps(releases, ensure_ascii=False, indent=2)
        return original[: match.start(1)] + replacement + original[match.end(1) :]

    if suffix in {".html", ".htm"}:
        return _patch_html_calendar(path, release, original)
    raise WebsiteError(
        f"Unsupported calendar file format: {path.suffix or '(none)'}. Supported formats: JSON, YAML, JS, HTML."
    )


def patch_calendar(path: Path, release: dict, *, write: bool = True) -> str:
    original = path.read_text(encoding="utf-8")
    patched = patch_calendar_text(path, release, original)
    if write and patched != original:
        path.write_text(patched, encoding="utf-8")
    return patched


def calendar_format(path: Path) -> str:
    names = {".json": "JSON", ".yaml": "YAML", ".yml": "YAML", ".js": "JS", ".html": "HTML", ".htm": "HTML"}
    suffix = path.suffix.lower()
    return names.get(suffix, suffix.lstrip(".").upper() or "UNKNOWN")
