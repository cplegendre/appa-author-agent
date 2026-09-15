from datetime import date

from author_agent.dashboard import build_dashboard
from author_agent.preview import write_post_preview
from author_agent.report import write_release_report


class Store:
    def recent_posts(self):
        return [
            {
                "date": "2026-09-12",
                "platform": "instagram",
                "topic": "kindness",
                "text": "x",
                "source": "s",
                "metadata": {},
            },
            {
                "date": "2026-09-11",
                "platform": "facebook",
                "topic": "kindness",
                "text": "x",
                "source": "s",
                "metadata": {},
            },
            {
                "date": "2026-09-10",
                "platform": "instagram",
                "topic": "kindness",
                "text": "x",
                "source": "s",
                "metadata": {},
            },
        ]


def test_dashboard_contains_repeat_alert(tmp_path):
    out = build_dashboard(Store(), [{"date": "2026-09-14", "title": "Next"}], tmp_path / "d.html", date(2026, 9, 13))
    text = out.read_text()
    assert "kindness: 3 posts" in text
    assert "Next" in text


def test_preview_contains_both_platforms_and_image(tmp_path):
    image = tmp_path / "promo.png"
    image.write_bytes(b"png")
    out = write_post_preview(
        tmp_path / "preview.html",
        {"image": str(image), "social": {"facebook": "Hello FB", "instagram": "Hello IG #books"}},
    )
    text = out.read_text()
    assert "Facebook" in text and "Instagram" in text
    assert "#books" in text
    assert image.resolve().as_uri() in text


def test_report_links_preview(tmp_path):
    preview = tmp_path / "preview.html"
    preview.write_text("x")
    out = write_release_report(
        tmp_path / "r.md",
        {
            "date": "2026-09-13",
            "social": {"facebook": "FB", "instagram": "IG", "teaser": "T"},
            "duplicate_check": {"facebook": {"max_similarity": 0.5, "warning": False}},
            "website": {"status": "prepared", "diff": "+x"},
        },
        preview,
    )
    text = out.read_text()
    assert "## Facebook" in text
    assert "Approval checklist" in text
    assert "preview.html" in text
    assert "+x" in text
