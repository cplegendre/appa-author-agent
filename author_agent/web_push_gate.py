from __future__ import annotations

import json
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path

_STATE_FILE = ".prepared-pushes.json"


def _state_path(output_dir: Path) -> Path:
    return output_dir / _STATE_FILE


def _load_state(output_dir: Path) -> dict[str, dict]:
    path = _state_path(output_dir)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_state(output_dir: Path, state: dict[str, dict]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = _state_path(output_dir)
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")
    temp.replace(path)


def issue_token(
    output_dir: Path,
    cache: dict[str, dict],
    name: str,
    branch: str,
    *,
    ttl_seconds: int = 3600,
) -> str:
    token = secrets.token_urlsafe(24)
    expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
    entry = {"token": token, "branch": branch, "expires_at": expires_at.isoformat()}
    cache[name] = entry
    state = _load_state(output_dir)
    state[name] = entry
    _save_state(output_dir, state)
    return token


def get_prepared(output_dir: Path, cache: dict[str, dict], name: str) -> dict | None:
    entry = cache.get(name) or _load_state(output_dir).get(name)
    if not entry:
        return None
    raw_expiry = entry.get("expires_at")
    if raw_expiry:
        try:
            expiry = datetime.fromisoformat(str(raw_expiry))
        except ValueError:
            expiry = datetime.now(timezone.utc) - timedelta(seconds=1)
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        if expiry <= datetime.now(timezone.utc):
            consume(output_dir, cache, name)
            return None
    cache[name] = entry
    return entry


def consume(output_dir: Path, cache: dict[str, dict], name: str) -> None:
    cache.pop(name, None)
    state = _load_state(output_dir)
    if name in state:
        state.pop(name, None)
        _save_state(output_dir, state)
