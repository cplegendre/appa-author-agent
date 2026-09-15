from __future__ import annotations

import argparse
import logging
import os
from datetime import date
from pathlib import Path
from typing import Any, Callable

from .book_evidence import retrieve_book_evidence
from .brand_voice import load_brand_voice
from .config import ROOT, SETTINGS_MODEL
from .dashboard import build_dashboard
from .demo import run_demo
from .errors import AuthorAgentError
from .io_utils import load_json, read_text_file, validate_date
from .logging_utils import install_secret_redaction, redact_text
from .ollama_client import generate_factual_review_json, generate_json
from .orchestration import OrchestrationDeps
from .orchestration import evergreen_cmd as _evergreen_impl
from .orchestration import load_releases as _load_releases_impl
from .orchestration import regenerate_output_field as _regenerate_impl
from .orchestration import release_candidates as _release_candidates_impl
from .orchestration import release_cmd as _release_impl
from .orchestration import today_cmd as _today_impl
from .orchestration import update_output_drafts as _update_output_drafts_impl
from .persistence import AutomationStore
from .prompts import render
from .rag import RagStore, hit_to_dict
from .rag_commands import RagCommandDeps
from .rag_commands import approve_file as _approve_file_impl
from .rag_commands import check_cmd as _rag_check_impl
from .rag_commands import import_meta_cmd as _rag_import_meta_impl
from .rag_commands import ingest_book_cmd as _rag_ingest_book_impl
from .rag_commands import ingest_posts_cmd as _rag_ingest_posts_impl
from .rag_commands import ingest_rows as _ingest_rows_impl
from .rag_commands import mark_approved_cmd as _rag_mark_approved_impl
from .rag_commands import search_cmd as _rag_search_impl
from .rag_commands import stats_cmd as _rag_stats_impl
from .website import prepare_website_update

SETTINGS = SETTINGS_MODEL.legacy_dict()
OLLAMA = SETTINGS["ollama"]
RAG_CFG = SETTINGS["rag"]
LOG = logging.getLogger(__name__)


def configure_logging(level: str | None = None) -> None:
    chosen = (level or os.getenv("AUTHOR_AGENT_LOG_LEVEL") or SETTINGS["logging"].get("level", "INFO")).upper()
    logging.basicConfig(
        level=getattr(logging, chosen, logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    install_secret_redaction()


def user_output(value: Any) -> None:
    print(value)


def rag_store() -> RagStore:
    from .content_services import make_rag_store

    return make_rag_store(ROOT, RAG_CFG, OLLAMA, RagStore)


def analyze_book(book_path: Path) -> dict:
    from .content_services import analyze_book_file

    return analyze_book_file(book_path, read_text=read_text_file, generate=generate_json, render=render, ollama=OLLAMA)


def _rag_context(store: RagStore, query: str, top_k: int | None = None) -> list[dict]:
    from .content_services import rag_context

    return rag_context(store, query, RAG_CFG, hit_to_dict, top_k)


def _sanitize_style_text(text: str) -> str:
    from .content_services import sanitize_style_text

    return sanitize_style_text(text)


def _style_examples(
    store: RagStore, query: str, brand_voice: dict[str, Any], *, platforms: tuple[str, ...] = ("facebook", "instagram")
) -> dict[str, list[dict]]:
    from .content_services import style_examples

    return style_examples(store, query, brand_voice, platforms=platforms)


def _duplicate_report(store: RagStore, post_text: str, platform: str) -> dict:
    from .content_services import duplicate_report

    return duplicate_report(
        store,
        post_text,
        platform,
        rag_cfg=RAG_CFG,
        ollama=OLLAMA,
        generate=generate_json,
        render=render,
        hit_to_dict=hit_to_dict,
    )


def _orchestration_deps() -> OrchestrationDeps:
    return OrchestrationDeps(
        root=ROOT,
        settings=SETTINGS,
        rag_store=rag_store,
        analyze_book=analyze_book,
        generate_json=generate_json,
        render=render,
        prepare_website_update=prepare_website_update,
        duplicate_report=_duplicate_report,
        rag_context=_rag_context,
        style_examples=_style_examples,
        book_evidence=retrieve_book_evidence,
        factual_review_json=generate_factual_review_json,
        brand_voice=load_brand_voice(ROOT).prompt_dict(),
        user_output=user_output,
        release_cmd=release_cmd,
        evergreen_cmd=evergreen_cmd,
    )


def _rag_deps() -> RagCommandDeps:
    return RagCommandDeps(
        root=ROOT,
        rag_store=rag_store,
        analyze_book=analyze_book,
        duplicate_report=_duplicate_report,
        user_output=user_output,
    )


def release_cmd(args: Any, *, emit: bool = True, run_date: str | None = None) -> tuple[dict, Path]:
    return _release_impl(args, _orchestration_deps(), emit=emit, run_date=run_date)


def evergreen_cmd(args: Any, *, emit: bool = True, run_date: str | None = None) -> tuple[dict, Path]:
    return _evergreen_impl(args, _orchestration_deps(), emit=emit, run_date=run_date)


def regenerate_output_field(path: Path, field: str) -> dict:
    return _regenerate_impl(path, field, _orchestration_deps())


def update_output_drafts(path: Path, drafts: dict[str, str]) -> dict:
    return _update_output_drafts_impl(path, drafts)


def approve_output_file(path: Path) -> dict:
    return _approve_file(path, True)


def _load_releases() -> list[dict]:
    return _load_releases_impl(ROOT)


def _release_candidates(today: date, releases: list[dict], window: int) -> list[tuple[int, dict]]:
    return _release_candidates_impl(today, releases, window)


def today_cmd(args: Any) -> dict:
    return _today_impl(args, _orchestration_deps())


def rag_ingest_posts_cmd(args: Any) -> None:
    _rag_ingest_posts_impl(args, _rag_deps())


def _ingest_rows(rows: list[dict], default_platform: str, source: str) -> dict:
    return _ingest_rows_impl(rows, default_platform, source, _rag_deps())


def rag_import_meta_cmd(args: Any) -> None:
    _rag_import_meta_impl(args, _rag_deps())


def rag_ingest_book_cmd(args: Any) -> None:
    _rag_ingest_book_impl(args, _rag_deps())


def rag_search_cmd(args: Any) -> None:
    _rag_search_impl(args, _rag_deps())


def rag_check_cmd(args: Any) -> None:
    _rag_check_impl(args, _rag_deps())


def rag_stats_cmd(args: Any) -> None:
    _rag_stats_impl(args, _rag_deps())


def _approve_file(path: Path, set_approved: bool) -> dict:
    return _approve_file_impl(path, set_approved, _rag_deps())


def rag_mark_approved_cmd(args: Any) -> None:
    _rag_mark_approved_impl(args, _rag_deps())


def rag_sync_approved_cmd(args: Any) -> None:
    from .cli import operations

    operations.rag_sync_approved(root=ROOT, load_json=load_json, approve_file=_approve_file, output=user_output)


def dashboard_cmd(args: Any) -> None:
    from .cli import operations

    operations.dashboard(
        args,
        root=ROOT,
        rag_store=rag_store,
        load_releases=_load_releases,
        build_dashboard=build_dashboard,
        validate_date=validate_date,
        output=user_output,
        store_factory=automation_store,
    )


def quickstart_cmd(args: Any) -> None:
    from .cli import operations
    from .config import load_settings

    operations.quickstart(args, root=ROOT, load_settings=load_settings, run_demo=run_demo, output=user_output)


def automation_store() -> AutomationStore:
    return AutomationStore(ROOT / SETTINGS["automation"].get("db_path", "data/automation.sqlite3"))


def migrate_cmd(args: Any) -> None:
    from .cli import operations

    operations.migrate(args, store_factory=automation_store, output=user_output)


def workflow_status_cmd(args: Any) -> None:
    from .cli import operations

    operations.workflow_status(args, store_factory=automation_store, output=user_output)


def workflow_create_cmd(args: Any) -> None:
    from .cli import operations

    operations.workflow_create(args, store_factory=automation_store, output=user_output)


def workflow_transition_cmd(args: Any) -> None:
    from .cli import operations

    operations.workflow_transition(args, store_factory=automation_store, output=user_output)


def workflow_reject_cmd(args: Any) -> None:
    from .cli import operations

    operations.workflow_reject(args, store_factory=automation_store, output=user_output)


def workflow_edit_cmd(args: Any) -> None:
    from .cli import operations

    operations.workflow_edit(args, store_factory=automation_store, output=user_output)


def workflow_queue_cmd(args: Any) -> None:
    from .cli import operations

    operations.workflow_queue(args, store_factory=automation_store, output=user_output)


def eval_cmd(args: Any) -> None:
    from .cli import operations

    operations.evaluate(args, fixture_dir=Path(__file__).with_name("evaluation") / "fixtures", output=user_output)


def analyze_visual_cmd(args: Any) -> None:
    from .cli import operations

    operations.analyze_visual(
        args, settings=SETTINGS, ollama=OLLAMA, store_factory=automation_store, output=user_output
    )


def publish_cmd(args: Any) -> None:
    from .cli import operations

    operations.publish(args, store_factory=automation_store, settings=SETTINGS, ollama=OLLAMA, output=user_output)


def publish_due_cmd(args: Any) -> None:
    from .cli import operations

    operations.publish_due(args, store_factory=automation_store, settings=SETTINGS, ollama=OLLAMA, output=user_output)


def campaign_plan_cmd(args: Any) -> None:
    from .cli import operations

    operations.campaign_plan(args, store_factory=automation_store, settings=SETTINGS, output=user_output)


def campaign_status_cmd(args: Any) -> None:
    from .cli import operations

    operations.campaign_status(args, store_factory=automation_store, settings=SETTINGS, output=user_output)


def meta_preflight_cmd(args: Any) -> None:
    from .cli import operations

    operations.preflight(args, settings=SETTINGS, ollama=OLLAMA, output=user_output)


def metrics_cmd(args: Any) -> None:
    from .cli import operations

    operations.metrics(args, store_factory=automation_store, settings=SETTINGS, ollama=OLLAMA, output=user_output)


def parser() -> argparse.ArgumentParser:
    from .cli.parser import build_parser

    handlers: dict[str, Callable[..., Any]] = {
        "release": release_cmd,
        "evergreen": evergreen_cmd,
        "today": today_cmd,
        "dashboard": dashboard_cmd,
        "rag_ingest_posts": rag_ingest_posts_cmd,
        "rag_import_meta": rag_import_meta_cmd,
        "rag_ingest_book": rag_ingest_book_cmd,
        "rag_search": rag_search_cmd,
        "rag_check": rag_check_cmd,
        "rag_stats": rag_stats_cmd,
        "rag_mark_approved": rag_mark_approved_cmd,
        "rag_sync_approved": rag_sync_approved_cmd,
        "migrate": migrate_cmd,
        "quickstart": quickstart_cmd,
        "eval": eval_cmd,
        "analyze_visual": analyze_visual_cmd,
        "workflow_create": workflow_create_cmd,
        "workflow_status": workflow_status_cmd,
        "workflow_transition": workflow_transition_cmd,
        "workflow_reject": workflow_reject_cmd,
        "workflow_edit": workflow_edit_cmd,
        "workflow_queue": workflow_queue_cmd,
        "publish": publish_cmd,
        "publish_due": publish_due_cmd,
        "metrics": metrics_cmd,
        "campaign_plan": campaign_plan_cmd,
        "campaign_status": campaign_status_cmd,
        "meta_preflight": meta_preflight_cmd,
    }
    return build_parser(SETTINGS, handlers)


def main() -> Any:
    args = parser().parse_args()
    configure_logging(args.log_level)
    try:
        return args.func(args)
    except (AuthorAgentError, ValueError) as exc:
        LOG.error("command_failed command=%s error=%s", getattr(args, "command", "unknown"), redact_text(exc))
        user_output(f"Error: {exc}")
        raise SystemExit(2) from exc
    except Exception as exc:
        LOG.exception("unexpected_error command=%s", getattr(args, "command", "unknown"))
        user_output("Unexpected error. Re-run with --log-level DEBUG for diagnostics.")
        raise SystemExit(1) from exc


if __name__ == "__main__":
    main()
