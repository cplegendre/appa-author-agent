from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .errors import ValidationError
from .io_utils import load_json, read_text_file, require_file, save_json, validate_book, validate_date
from .rag import hit_to_dict, load_posts_file, normalize_post, parse_meta_facebook, parse_meta_instagram


@dataclass(frozen=True)
class RagCommandDeps:
    root: Path
    rag_store: Callable[[], Any]
    analyze_book: Callable[[Path], dict]
    duplicate_report: Callable[[Any, str, str], dict]
    user_output: Callable[[Any], None]


def ingest_rows(rows: list[dict], default_platform: str, source: str, deps: RagCommandDeps) -> dict:
    store = deps.rag_store()
    added = skipped = 0
    for index, raw in enumerate(rows):
        post = normalize_post(raw, default_platform=default_platform)
        if not post["text"].strip():
            skipped += 1
            continue
        store.upsert(
            kind="post",
            text=post["text"],
            source=post["source"] or source,
            external_id=post["external_id"] or f"{source}:{index}",
            date=post["date"],
            platform=post["platform"],
            topic=post["topic"],
            metadata=post["metadata"],
        )
        added += 1
    result = {"ingested": added, "skipped": skipped, "stats": store.stats()}
    deps.user_output(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def ingest_posts_cmd(args: Any, deps: RagCommandDeps) -> None:
    path = require_file(args.file, label="Posts file")
    ingest_rows(load_posts_file(path), args.platform or "", args.source or path.name, deps)


def import_meta_cmd(args: Any, deps: RagCommandDeps) -> None:
    path = require_file(args.file, label="Meta export")
    platform = args.platform
    if platform == "auto":
        name = path.name.lower()
        platform = "facebook" if "your_posts" in name else "instagram" if "posts_" in name else ""
        if not platform:
            raise ValidationError("Could not detect the Meta platform; add --platform facebook|instagram.")
    rows = parse_meta_facebook(path) if platform == "facebook" else parse_meta_instagram(path)
    ingest_rows(rows, platform, f"meta:{path.name}", deps)


def ingest_book_cmd(args: Any, deps: RagCommandDeps) -> None:
    path = validate_book(args.book)
    store = deps.rag_store()
    if args.date:
        validate_date(args.date)
    profile = deps.analyze_book(path) if not args.no_analyze else {}
    text = read_text_file(path)
    title = profile.get("title", path.stem)
    doc_id = store.upsert(
        kind="book",
        text=json.dumps(profile, ensure_ascii=False) + "\n" + text[:30000],
        source=args.source or path.name,
        external_id=args.id or path.stem,
        title=title,
        date=args.date or "",
        topic="; ".join(profile.get("themes", []) if isinstance(profile.get("themes"), list) else []),
        metadata={"path": str(path), "profile": profile},
    )
    deps.user_output(json.dumps({"id": doc_id, "title": title, "stats": store.stats()}, ensure_ascii=False, indent=2))


def search_cmd(args: Any, deps: RagCommandDeps) -> None:
    hits = deps.rag_store().search(
        args.query,
        top_k=args.top_k,
        kinds=args.kind or None,
        platforms=args.platform or None,
    )
    deps.user_output(json.dumps([hit_to_dict(hit) for hit in hits], ensure_ascii=False, indent=2))


def check_cmd(args: Any, deps: RagCommandDeps) -> None:
    result = deps.duplicate_report(deps.rag_store(), args.text, args.platform)
    deps.user_output(json.dumps(result, ensure_ascii=False, indent=2))


def stats_cmd(_args: Any, deps: RagCommandDeps) -> None:
    deps.user_output(json.dumps(deps.rag_store().stats(), ensure_ascii=False, indent=2))


def approve_file(path: Path, set_approved: bool, deps: RagCommandDeps) -> dict:
    data = load_json(path, None)
    if not isinstance(data, dict):
        raise ValidationError(f"Invalid output JSON: {path}")
    if data.get("dry_run"):
        raise ValidationError("Dry-run outputs cannot be approved. Regenerate without --dry-run first.")
    if set_approved:
        data["approved"] = True
        save_json(path, data)
    if not data.get("approved"):
        raise ValidationError("This output is not approved. Set `approved: true` or use `rag mark-approved`.")
    store = deps.rag_store()
    social = data.get("social", data)
    topic = social.get("primary_angle") or data.get("topic", "")
    added: list[str] = []
    for platform in ("facebook", "instagram"):
        text = social.get(platform, "")
        if text:
            store.upsert(
                kind="post",
                text=text,
                source="generated-approved",
                external_id=f"{path.stem}:{platform}",
                date=data.get("date", ""),
                platform=platform,
                topic=topic,
                metadata={"output_file": str(path), "approved": True, "published_assumed": True},
            )
            added.append(platform)
    data["rag_registered"] = True
    save_json(path, data)
    return {"file": str(path), "registered": added, "stats": store.stats()}


def mark_approved_cmd(args: Any, deps: RagCommandDeps) -> None:
    path = require_file(args.file, label="Output JSON", suffixes={".json"})
    deps.user_output(json.dumps(approve_file(path, True, deps), ensure_ascii=False, indent=2))


def sync_approved_cmd(_args: Any, deps: RagCommandDeps) -> None:
    results = []
    for path in sorted((deps.root / "output").glob("*.json")):
        data = load_json(path, {})
        if data.get("approved") and not data.get("rag_registered") and (data.get("social") or data.get("facebook")):
            results.append(approve_file(path, False, deps))
    deps.user_output(json.dumps({"synced": len(results), "files": results}, ensure_ascii=False, indent=2))
