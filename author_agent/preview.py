from __future__ import annotations

import html
import re
from pathlib import Path

_PREVIEW_STYLE = """
body { font-family: system-ui, -apple-system, sans-serif;
background: #f3f4f6; color: #171717; margin: 0; padding: 24px; }
.wrap { max-width: 1050px; margin: auto; }
h1 { font-size: 1.25rem; margin-top: 0; }
.note { color: #666; margin-bottom: 20px; }
.grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 20px; align-items: start; }
.card { background: #fff; border: 1px solid #ddd;
border-radius: 16px; overflow: hidden; box-shadow: 0 5px 20px rgba(0,0,0,.06); }
.platform { padding: 10px 16px; font-weight: 700; border-bottom: 1px solid #eee; }
.author { display: flex; gap: 10px; padding: 14px 16px; align-items: center; }
.avatar { width: 42px; height: 42px; border-radius: 50%;
background: #eee; display: grid; place-items: center; font-weight: 700; }
small { display: block; color: #777; margin-top: 2px; }
.media { display: block; width: 100%; max-height: 480px; object-fit: cover; background: #eee; }
.placeholder { height: 200px; display: grid; place-items: center; color: #777; }
.caption { padding: 16px 16px 6px; line-height: 1.45; white-space: normal; }
.hashtags { padding: 0 16px 14px; color: #345; line-height: 1.4; }
.actions { border-top: 1px solid #eee; padding: 12px 16px; color: #555; font-size: .92rem; }
""".strip()


def _split_hashtags(text: str) -> tuple[str, str]:
    tags = re.findall(r"(?<!\w)#\w+", text)
    if not tags:
        return text, ""
    clean = text
    for tag in tags:
        clean = clean.replace(tag, "")
    return clean.strip(), " ".join(tags)


def render_post_preview_html(result: dict, *, image_src: str = "") -> str:
    social = result.get("social", result)
    cards: list[str] = []
    image_html = (
        f'<img class="media" alt="Promotional image preview" src="{html.escape(image_src, quote=True)}">'
        if image_src
        else '<div class="placeholder">No promotional image</div>'
    )
    for platform, label in (("facebook", "Facebook"), ("instagram", "Instagram")):
        text = str(social.get(platform, ""))
        body, tags = _split_hashtags(text) if platform == "instagram" else (text, "")
        cards.append(
            '<article class="card">'
            f'<div class="platform">{label}</div>'
            '<div class="author"><div class="avatar">LN</div><div>'
            "<strong>LéoN NoèL</strong><small>Preview · not published</small></div></div>"
            f"{image_html}"
            f'<div class="caption">{html.escape(body).replace(chr(10), "<br>")}</div>'
            f'<div class="hashtags">{html.escape(tags)}</div>'
            '<div class="actions">♡ Like &nbsp;&nbsp; ◇ Comment &nbsp;&nbsp; ↗ Share</div>'
            "</article>"
        )
    return (
        '<!doctype html><html><head><meta charset="utf-8"><title>Social preview</title>'
        f'<style>{_PREVIEW_STYLE}</style></head><body><div class="wrap">'
        "<h1>Author Agent social preview</h1>"
        '<p class="note">Static local mockup only. Nothing has been published.</p>'
        f'<div class="grid">{"".join(cards)}</div></div></body></html>'
    )


def write_post_preview(path: Path, result: dict) -> Path:
    image = str(result.get("image", ""))
    image_src = Path(image).resolve().as_uri() if image and Path(image).exists() else ""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_post_preview_html(result, image_src=image_src), encoding="utf-8")
    return path
