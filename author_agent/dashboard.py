from __future__ import annotations

import html
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

from .rag import RagStore

_DASHBOARD_STYLE = """
body { font-family: system-ui; max-width: 1100px;
margin: 40px auto; padding: 0 20px; background: #fafafa; color: #222; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 18px; }
section { background: white; border: 1px solid #ddd; border-radius: 12px; padding: 18px; }
table { width: 100%; border-collapse: collapse; }
th, td { text-align: left; padding: 7px; border-bottom: 1px solid #eee; }
code { background: #eee; padding: 2px 5px; border-radius: 4px; }
""".strip()


def build_dashboard(
    store: RagStore, releases: list[dict], output: Path, today: date, review_queue: list[dict] | None = None
) -> Path:
    posts = store.recent_posts()
    windows: dict[int, dict] = {}
    for days in (30, 90, 365):
        cutoff = today - timedelta(days=days)
        selected = []
        for post in posts:
            try:
                post_day = date.fromisoformat(post.get("date") or "1900-01-01")
            except ValueError:
                continue
            if post_day >= cutoff:
                selected.append(post)
        topics = Counter((post.get("topic") or "unclassified").strip() or "unclassified" for post in selected)
        windows[days] = {"count": len(selected), "topics": topics.most_common(12)}

    alerts = []
    for topic, count in windows[30]["topics"]:
        if topic != "unclassified" and count >= 3:
            alerts.append(f"{topic}: {count} posts in 30 days")

    upcoming = []
    for release in releases:
        raw = str(release.get("date", ""))
        try:
            release_day = date.fromisoformat(raw)
        except ValueError:
            continue
        if release_day >= today:
            upcoming.append(release)
    upcoming = sorted(upcoming, key=lambda item: item.get("date", ""))[:12]

    def topic_table(days: int) -> str:
        rows = "".join(
            f"<tr><td>{html.escape(topic)}</td><td>{count}</td></tr>" for topic, count in windows[days]["topics"]
        )
        return (
            f"<h3>{days} days — {windows[days]['count']} posts</h3>"
            f"<table><tr><th>Topic</th><th>Count</th></tr>{rows}</table>"
        )

    release_rows = "".join(
        "<tr>"
        f"<td>{html.escape(str(release.get('date', '')))}</td>"
        f"<td>{html.escape(str(release.get('title') or release.get('book') or ''))}</td>"
        "</tr>"
        for release in upcoming
    )
    alert_html = "".join(f"<li>⚠️ {html.escape(alert)}</li>" for alert in alerts)
    if not alert_html:
        alert_html = "<li>✅ No obvious topic over-repetition in the last 30 days.</li>"
    queue_rows = "".join(
        "<tr>"
        f"<td><code>{html.escape(str(item.get('id', '')))}</code></td>"
        f"<td>{html.escape(str(item.get('book', '')))}</td>"
        f"<td>{html.escape(str(item.get('platform', '')))}</td>"
        f"<td>{html.escape(str(item.get('post_role', '')))}</td>"
        f"<td>{int(item.get('age_days', 0))}</td>"
        "</tr>"
        for item in (review_queue or [])
    )
    if not queue_rows:
        queue_rows = "<tr><td colspan='5'>No workflows awaiting human review.</td></tr>"
    body = (
        "<!doctype html><html><head><meta charset='utf-8'><title>Author Agent Dashboard</title>"
        f"<style>{_DASHBOARD_STYLE}</style></head><body>"
        f"<h1>Author Agent editorial dashboard</h1><p>Generated for {today.isoformat()}.</p>"
        "<div class='grid'>"
        f"<section>{topic_table(30)}</section>"
        f"<section>{topic_table(90)}</section>"
        f"<section>{topic_table(365)}</section>"
        "</div>"
        f"<section><h2>Over-repetition alerts</h2><ul>{alert_html}</ul></section>"
        "<section><h2>Human review queue</h2>"
        "<table><tr><th>ID</th><th>Book</th><th>Platform</th>"
        "<th>Role</th><th>Age (days)</th></tr>"
        f"{queue_rows}</table></section>"
        "<section><h2>Upcoming releases</h2>"
        f"<table><tr><th>Date</th><th>Release</th></tr>{release_rows}</table></section>"
        "</body></html>"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(body, encoding="utf-8")
    return output
