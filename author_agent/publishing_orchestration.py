from __future__ import annotations

from pathlib import Path
from typing import Any

from .io_utils import load_json, save_json, validate_book, validate_date, validate_optional_image
from .preview import write_post_preview
from .report import write_release_report
from .orchestration_types import OrchestrationDeps
from .orchestration_generation import _generate_social_with_retry
from .orchestration_validation import _current_release_facts, _reject_social_formatting, _validate_release_social_contract
from .orchestration_factual import _validate_factual_grounding, _cross_draft_similarity

def output_dir(root: Path, dry_run: bool) -> Path:
    return root / "output" / "dry-run" if dry_run else root / "output"


def release_output(root: Path, args: Any, run_date: str | None = None, dry_run: bool = False) -> Path:
    name = f"release-{run_date}-{args.date}.json" if run_date else f"release-{args.date}.json"
    return output_dir(root, dry_run) / name


def preview_and_report(out: Path, result: dict) -> tuple[Path, Path]:
    preview = write_post_preview(out.with_name(out.stem + "-preview.html"), result)
    report = write_release_report(out.with_suffix(".md"), result, preview)
    return preview, report


def release_cmd(
    args: Any,
    deps: OrchestrationDeps,
    *,
    emit: bool = True,
    run_date: str | None = None,
) -> tuple[dict, Path]:
    release_date = validate_date(args.date, "release date")
    book = validate_book(args.book)
    image = validate_optional_image(getattr(args, "image", ""))
    dry_run = bool(getattr(args, "dry_run", False))
    profile = deps.analyze_book(book)
    store = deps.rag_store()
    themes = profile.get("themes", []) if isinstance(profile.get("themes"), list) else []
    summary = profile.get("summary_short", "") or profile.get("plot_summary", "")
    query = " ".join([profile.get("title", ""), " ".join(themes), summary]).strip() or book.stem
    rag_context = deps.rag_context(store, query)
    style_examples = deps.style_examples(store, query, deps.brand_voice)
    book_evidence = deps.book_evidence(store, book, query, top_k=10)
    ollama = deps.settings["ollama"]
    status = "published" if args.published else "scheduled"

    def validate_release_payload(payload: dict[str, Any]) -> None:
        for field in ("facebook", "instagram", "teaser"):
            _reject_social_formatting(field, str(payload.get(field, "")))
        _validate_release_social_contract(
            payload,
            status=status,
            release_url=str(args.url or ""),
            brand_voice=deps.brand_voice,
            profile=profile,
        )
        _validate_factual_grounding(deps, ollama, profile, payload, book_path=book)

    social = _generate_social_with_retry(
        deps,
        ollama,
        "social_release.txt",
        ("facebook", "instagram", "teaser"),
        {
            "RELEASE_STATUS": status,
            "RELEASE_DATE": release_date,
            "RELEASE_URL": args.url,
            "CURRENT_RELEASE_FACTS": _current_release_facts(
                profile, status=status, release_date=release_date, release_url=str(args.url or "")
            ),
            "BOOK_PROFILE": profile,
            "BOOK_EVIDENCE": book_evidence,
            "BRAND_VOICE": deps.brand_voice,
            "RAG_CONTEXT": rag_context,
            "STYLE_EXAMPLES": style_examples,
        },
        label="release",
        post_validate=validate_release_payload,
    )
    duplicate_check = {
        "facebook": deps.duplicate_report(store, social.get("facebook", ""), "facebook"),
        "instagram": deps.duplicate_report(store, social.get("instagram", ""), "instagram"),
        "teaser": deps.duplicate_report(store, social.get("teaser", ""), "instagram"),
    }
    draft_similarity = _cross_draft_similarity(
        store,
        {field: str(social.get(field, "")) for field in ("facebook", "instagram", "teaser")},
        float(deps.brand_voice.get("cross_draft_similarity_warning", 0.84)),
    )
    website_cfg = deps.settings.get("website", {})
    if args.published:
        website = deps.prepare_website_update(
            website_cfg.get("repo_path", ""),
            profile.get("title", book.stem),
            release_date,
            args.url,
            calendar_data_file=website_cfg.get("calendar_data_file", ""),
            branch_prefix=website_cfg.get("branch_prefix", "author-agent"),
            commit=bool(website_cfg.get("allow_commit", True)),
            dry_run=bool(getattr(args, "website_dry_run", dry_run)),
        )
    else:
        website = {
            "status": "skipped",
            "reason": "Scheduled release/teaser: website was not modified.",
            "dry_run": dry_run,
        }
    result = {
        "date": run_date or release_date,
        "release_date": release_date,
        "book": str(book),
        "image": str(image) if image else "",
        "url": args.url,
        "published": bool(args.published),
        "profile": profile,
        "rag_context": rag_context,
        "style_examples": style_examples,
        "book_evidence": book_evidence,
        "social": social,
        "post_roles": {"facebook": "launch", "instagram": "launch", "teaser": "teaser"},
        "duplicate_check": duplicate_check,
        "draft_similarity": draft_similarity,
        "website": website,
        "approved": False,
        "approval_required": True,
        "editorial_contract_version": "0.25",
        "dry_run": dry_run,
    }
    out = release_output(deps.root, args, run_date, dry_run)
    save_json(out, result)
    preview, report = preview_and_report(out, result)
    result.update({"preview": str(preview), "report": str(report)})
    save_json(out, result)
    if emit:
        mode = "DRY-RUN" if dry_run else "Generated"
        deps.user_output(f"{mode}: {out}\nReport: {report}\nPreview: {preview}\nManual approval required.")
    return result, out


def evergreen_cmd(
    args: Any,
    deps: OrchestrationDeps,
    *,
    emit: bool = True,
    run_date: str | None = None,
) -> tuple[dict, Path]:
    day = validate_date(args.date, "date")
    dry_run = bool(getattr(args, "dry_run", False))
    history = load_json(deps.root / "data/post_history.json", [])
    limit = deps.settings["social"].get("recent_post_limit", 30)
    recent = history[-limit:]
    store = deps.rag_store()
    evergreen_query = "children books reading educational author character activity promotion"
    context = deps.rag_context(store, evergreen_query, top_k=12)
    style_examples = deps.style_examples(store, evergreen_query, deps.brand_voice)
    ollama = deps.settings["ollama"]
    post = _generate_social_with_retry(
        deps,
        ollama,
        "evergreen.txt",
        ("facebook", "instagram"),
        {
            "RECENT_POSTS": recent,
            "BRAND_VOICE": deps.brand_voice,
            "RAG_CONTEXT": context,
            "STYLE_EXAMPLES": style_examples,
        },
        label="evergreen",
        post_validate=lambda payload: [
            _reject_social_formatting(field, str(payload.get(field, "")))
            for field in ("facebook", "instagram")
        ],
    )
    post.update(
        {
            "date": day,
            "post_roles": {"facebook": "evergreen", "instagram": "evergreen"},
            "approved": False,
            "approval_required": True,
            "dry_run": dry_run,
            "style_examples": style_examples,
        }
    )
    post["duplicate_check"] = {
        "facebook": deps.duplicate_report(store, post.get("facebook", ""), "facebook"),
        "instagram": deps.duplicate_report(store, post.get("instagram", ""), "instagram"),
    }
    post["draft_similarity"] = _cross_draft_similarity(
        store,
        {field: str(post.get(field, "")) for field in ("facebook", "instagram")},
        float(deps.brand_voice.get("cross_draft_similarity_warning", 0.84)),
    )
    out = output_dir(deps.root, dry_run) / f"evergreen-{run_date or day}.json"
    save_json(out, post)
    report_result = {
        "date": day,
        "image": getattr(args, "image", ""),
        "social": post,
        "duplicate_check": post["duplicate_check"],
        "website": {"status": "not-applicable", "dry_run": dry_run},
    }
    preview, report = preview_and_report(out, report_result)
    post.update({"preview": str(preview), "report": str(report)})
    save_json(out, post)
    if emit:
        mode = "DRY-RUN" if dry_run else "Generated"
        deps.user_output(f"{mode}: {out}\nReport: {report}\nPreview: {preview}\nManual approval required.")
    return post, out


_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "facebook": ("facebook", "facebook_post", "fb", "fb_post"),
    "instagram": ("instagram", "instagram_post", "ig", "ig_post"),
    "teaser": ("teaser", "teaser_post", "preview", "coming_soon"),
}
_TEXT_KEYS = ("text", "caption", "content", "copy", "post", "body", "message")
_CONTAINER_KEYS = ("social", "drafts", "posts", "result", "output", "response", "data")


