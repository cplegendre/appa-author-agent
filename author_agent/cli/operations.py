from __future__ import annotations
import getpass
import json
from pathlib import Path
from typing import Any, Callable
from ..evaluation import report_dict, run_evaluation
from ..vision import MultimodalBookAnalyzer, OllamaVisionProvider
from ..workflow import WorkflowService, WorkflowState
from . import campaigns as cli_campaigns
from . import publishing as cli_publishing

def migrate(args: Any, *, store_factory: Callable[[], Any], output: Callable[[Any], None]) -> None:
    store = store_factory()
    output(json.dumps({'schema_version': store.schema_version(), 'database': str(store.path)}, indent=2))

def workflow_status(args: Any, *, store_factory: Callable[[], Any], output: Callable[[Any], None]) -> None:
    service = WorkflowService(store_factory())
    row = service.get(args.id)
    row['history'] = service.history(args.id)
    output(json.dumps(row, ensure_ascii=False, indent=2))

def workflow_create(args: Any, *, store_factory: Callable[[], Any], output: Callable[[Any], None]) -> None:
    service = WorkflowService(store_factory())
    output(service.create(book=args.book, campaign=args.campaign, platform=args.platform, state=WorkflowState(args.state), text=args.text))

def workflow_transition(args: Any, *, store_factory: Callable[[], Any], output: Callable[[Any], None]) -> None:
    service = WorkflowService(store_factory())
    output(json.dumps(service.transition(args.id, WorkflowState(args.state), reason=args.reason), ensure_ascii=False, indent=2))

def workflow_reject(args: Any, *, store_factory: Callable[[], Any], output: Callable[[Any], None]) -> None:
    service = WorkflowService(store_factory())
    output(json.dumps(service.reject(args.id, args.reason), ensure_ascii=False, indent=2))

def workflow_edit(args: Any, *, store_factory: Callable[[], Any], output: Callable[[Any], None]) -> None:
    service = WorkflowService(store_factory())
    actor = (getattr(args, 'actor', '') or getpass.getuser() or 'unknown').strip()
    row = service.edit_draft(args.id, field=args.field, value=args.value, edited_by=actor)
    row['edits'] = service.edits(args.id)
    output(json.dumps(row, ensure_ascii=False, indent=2))

def workflow_queue(args: Any, *, store_factory: Callable[[], Any], output: Callable[[Any], None]) -> None:
    service = WorkflowService(store_factory())
    rows = service.review_queue(
        book=args.book, platform=args.platform, min_age_days=args.min_age_days,
        max_age_days=args.max_age_days, sort_by=args.sort,
    )
    output('ID\tBOOK\tPLATFORM\tROLE\tAGE_DAYS')
    for row in rows:
        output(f"{row['id']}\t{row['book']}\t{row['platform']}\t{row['post_role']}\t{row['age_days']}")

def evaluate(args: Any, *, fixture_dir: Path, output: Callable[[Any], None]) -> None:
    report = report_dict(run_evaluation(fixture_dir))
    if args.json:
        output(json.dumps(report, ensure_ascii=False, indent=2))
        return
    output(f"Evaluation: {report['overall_score']:.2f}/100 ({report['cases']} cases)")
    output(f"Factual precision: {report['factual_precision']:.3f}; unsupported claim rate: {report['unsupported_claim_rate']:.3f}")
    output(f"Duplicate rate: {report['duplicate_rate']:.3f}; platform differentiation: {report['platform_differentiation']:.3f}")

def analyze_visual(args: Any, *, settings: dict[str, Any], ollama: dict[str, Any], store_factory: Callable[[], Any], output: Callable[[Any], None]) -> None:
    cfg = settings['book_analysis']
    provider = None
    enabled = bool(cfg.get('multimodal_enabled', False))
    if enabled and cfg.get('vision_provider') == 'ollama' and cfg.get('vision_model'):
        provider = OllamaVisionProvider(ollama['base_url'], cfg['vision_model'], ollama.get('timeout_seconds', 240))
    analyzer = MultimodalBookAnalyzer(store_factory(), provider=provider)
    evidence = analyzer.analyze_pdf(Path(args.book), enabled=enabled, max_pages=args.max_pages or int(cfg.get('max_pages', 0)))
    output(json.dumps(analyzer.serializable(evidence), ensure_ascii=False, indent=2))

def publish(args: Any, **kw: Any) -> None:
    cli_publishing.publish_command(args, **kw)

def publish_due(args: Any, **kw: Any) -> None:
    cli_publishing.publish_due_command(args, **kw)

def campaign_plan(args: Any, **kw: Any) -> None:
    cli_campaigns.plan_command(args, **kw)

def campaign_status(args: Any, **kw: Any) -> None:
    cli_campaigns.status_command(args, **kw)

def preflight(args: Any, **kw: Any) -> None:
    cli_publishing.preflight_command(args, **kw)

def metrics(args: Any, **kw: Any) -> None:
    cli_publishing.metrics_command(args, **kw)

def rag_sync_approved(*, root: Path, load_json: Callable[..., Any], approve_file: Callable[[Path, bool], dict], output: Callable[[Any], None]) -> None:
    results = []
    for path in sorted((root / 'output').glob('*.json')):
        data = load_json(path, {})
        if data.get('approved') and (not data.get('rag_registered')) and (data.get('social') or data.get('facebook')):
            results.append(approve_file(path, False))
    output(json.dumps({'synced': len(results), 'files': results}, ensure_ascii=False, indent=2))

def dashboard(args: Any, *, root: Path, rag_store: Callable[[], Any], load_releases: Callable[[], list[dict]], build_dashboard: Callable[..., Any], validate_date: Callable[..., str], output: Callable[[Any], None], store_factory: Callable[[], Any] | None = None) -> None:
    from datetime import date
    import inspect
    out = root / 'output' / 'dashboard.html'
    day = date.fromisoformat(validate_date(args.date or date.today().isoformat()))
    queue = WorkflowService(store_factory()).review_queue() if store_factory is not None else []
    if 'review_queue' in inspect.signature(build_dashboard).parameters:
        build_dashboard(rag_store(), load_releases(), out, day, review_queue=queue)
    else:
        build_dashboard(rag_store(), load_releases(), out, day)
    output(f'Dashboard: {out}')

def quickstart(args: Any, *, root: Path, load_settings: Callable[[Path], Any], run_demo: Callable[..., dict], output: Callable[[Any], None]) -> None:
    result = run_demo(root=root, settings=load_settings(root), output=output)
    if getattr(args, 'json', False):
        output(json.dumps(result, ensure_ascii=False, indent=2))
