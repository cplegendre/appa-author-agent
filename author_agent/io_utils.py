from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from pypdf import PdfReader

from .errors import ValidationError

SUPPORTED_BOOK_SUFFIXES = {".pdf", ".txt", ".md"}
SUPPORTED_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp"}


def validate_date(value: str, field: str = "date") -> str:
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise ValidationError(f"Invalid {field} `{value}`. Expected YYYY-MM-DD.") from exc


def require_file(path_value: str | Path, *, label: str, suffixes: set[str] | None = None) -> Path:
    path = Path(path_value).expanduser().resolve()
    if not path.is_file():
        raise ValidationError(f"{label} not found: {path}")
    if suffixes and path.suffix.lower() not in suffixes:
        allowed = ", ".join(sorted(suffixes))
        raise ValidationError(f"Unsupported format for {label}: {path.suffix}. Expected one of: {allowed}")
    return path


def validate_book(path_value: str | Path) -> Path:
    return require_file(path_value, label="Book file", suffixes=SUPPORTED_BOOK_SUFFIXES)


def validate_optional_image(path_value: str | Path | None) -> Path | None:
    if not path_value:
        return None
    return require_file(path_value, label="Promotional image", suffixes=SUPPORTED_IMAGE_SUFFIXES)


def read_text_file(path: Path) -> str:
    if not path.is_file():
        raise ValidationError(f"File not found: {path}")
    if path.suffix.lower() == ".pdf":
        reader = PdfReader(str(path))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    return path.read_text(encoding="utf-8")


def load_json(path: Path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
