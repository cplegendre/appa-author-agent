from __future__ import annotations

from pathlib import Path


def _status(check: dict | None) -> str:
    if not check or check.get("max_similarity") is None:
        return "✅ no comparable history"
    score = float(check["max_similarity"])
    if check.get("warning"):
        icon = "❌" if score >= 0.86 else "⚠️"
    else:
        icon = "✅"
    return f"{icon} max similarity {score:.3f}"


def _draft_similarity_summary(report: dict | None) -> str:
    if not report or not report.get("available"):
        return "not available"
    pairs = report.get("pairs", [])
    if not pairs:
        return "no comparable draft pairs"
    flagged = [pair for pair in pairs if pair.get("warning")]
    max_pair = max(pairs, key=lambda pair: float(pair.get("similarity", -1.0)))
    icon = "⚠️" if flagged else "✅"
    return (
        f"{icon} max cross-draft similarity "
        f"{float(max_pair.get('similarity', 0.0)):.3f} "
        f"({max_pair.get('left', '?')} ↔ {max_pair.get('right', '?')})"
    )


def write_release_report(path: Path, result: dict, preview_path: Path | None = None) -> Path:
    social = result.get("social", {})
    checks = result.get("duplicate_check", {})
    site = result.get("website", {})
    draft_similarity = result.get("draft_similarity") or social.get("draft_similarity")
    preview_link = "not generated"
    if preview_path:
        try:
            preview_link = f"[Open visual preview]({preview_path.relative_to(path.parent)})"
        except ValueError:
            preview_link = str(preview_path)
    body = f"""# Author Agent — review report {result.get("date", "")}

**Visual preview:** {preview_link}

## Facebook

{social.get("facebook", "")}

**Duplicate check:** {_status(checks.get("facebook"))}

## Instagram

{social.get("instagram", "")}

**Duplicate check:** {_status(checks.get("instagram"))}

## Teaser

{social.get("teaser", "")}

**Duplicate check:** {_status(checks.get("teaser"))}

## Cross-draft differentiation

{_draft_similarity_summary(draft_similarity)}

## Website

- Status: `{site.get("status", "n/a")}`
- Dry-run: `{site.get("dry_run", False)}`
- Branch: `{site.get("branch", "")}`
- File: `{site.get("file", "")}`
- GitHub compare: {site.get("compare_url", "") or "not available"}
- Automatic push: **NO**

```diff
{site.get("diff", "")}
```

## Approval checklist

- [ ] Facebook copy reviewed
- [ ] Instagram copy reviewed
- [ ] Teaser reviewed (if used)
- [ ] RAG duplicate warnings reviewed
- [ ] Visual preview reviewed
- [ ] Website diff reviewed
- [ ] Mark approved with `python run.py rag mark-approved --file ...` after approval
- [ ] Git push / merge performed manually if desired
"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return path
