from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Callable

import httpx

from .config import ROOT, Settings
from .io_utils import read_text_file
from .ollama_client import generate_json
from .persistence import AutomationStore
from .publishing import MetaConfig, MetaPublisher, PublishingService
from .workflow import WorkflowService, WorkflowState


def _ollama_available(settings: Settings) -> bool:
    try:
        response = httpx.get(f"{settings.ollama.base_url.rstrip('/')}/api/tags", timeout=1.5)
        return response.status_code == 200
    except httpx.HTTPError:
        return False


def _deterministic_draft(text: str) -> str:
    title = next((line.strip() for line in text.splitlines() if line.strip()), "Our sample story")
    return (
        f"Meet {title}. A small fox named Milo finds a red kite and asks Lila the rabbit for help. "
        "A gentle story about patient teamwork."
    )


def run_demo(
    *,
    root: Path = ROOT,
    settings: Settings,
    output: Callable[[str], None] = print,
    sample_pdf: Path | None = None,
) -> dict[str, str]:
    book = sample_pdf or root / "author_agent" / "demo_data" / "sample_book.pdf"
    if not book.is_file():
        raise FileNotFoundError(f"Demo sample PDF is missing: {book}")

    output(f"[1/7] INGEST  {book.name}")
    book_text = read_text_file(book).strip()
    if not book_text:
        raise ValueError("Demo PDF produced no extractable text")

    output("[2/7] ANALYZE extracted local text evidence")
    ollama_ready = _ollama_available(settings)
    mode = "mocked deterministic generator (Ollama unavailable)"

    with tempfile.TemporaryDirectory(prefix="author-agent-demo-") as tmp:
        store = AutomationStore(Path(tmp) / "automation.sqlite3")
        workflow = WorkflowService(store)
        workflow_id = workflow.create(
            book=book.name,
            campaign="public-demo",
            platform="facebook",
            state=WorkflowState.INGESTED,
            text=book_text,
        )
        workflow.transition(workflow_id, WorkflowState.ANALYZED, reason="demo analysis complete")

        output("[3/7] DRAFT   generate grounded sample marketing copy")
        draft = _deterministic_draft(book_text)
        if ollama_ready:
            try:
                generated = generate_json(
                    settings.ollama.base_url,
                    settings.ollama.marketing_model,
                    (
                        "Return JSON with one key named draft. Write one short factual Facebook post using only "
                        f"these facts, without adding details: {book_text[:3000]}"
                    ),
                    min(settings.ollama.timeout_seconds, 60),
                )
                candidate = str(generated.get("draft", "")).strip()
                required = ("Milo", "red kite", "Lila", "teamwork")
                if candidate and all(term.lower() in candidate.lower() for term in required):
                    draft = candidate
                    mode = "local Ollama generator"
                else:
                    mode = "mocked deterministic generator (Ollama output failed grounding check)"
            except Exception:
                mode = "mocked deterministic generator (Ollama request failed)"
        output(f"      Generator mode: {mode}")
        workflow.transition(workflow_id, WorkflowState.DRAFTED, reason="demo draft generated")
        workflow.update_content(workflow_id, draft)

        output("[4/7] REVIEW  factual grounding check")
        required = ("Milo", "red kite", "Lila", "teamwork")
        if not all(term.lower() in book_text.lower() and term.lower() in draft.lower() for term in required):
            raise ValueError("Demo factual grounding check failed")
        workflow.transition(workflow_id, WorkflowState.VALIDATED, reason="demo factual grounding passed")
        workflow.transition(workflow_id, WorkflowState.REVIEW_REQUIRED, reason="demo review gate")

        output("[5/7] APPROVE explicit demo-only auto-approval")
        workflow.approve(workflow_id, draft)

        output("[6/7] PUBLISH Meta provider dry-run (network disabled)")
        publisher = MetaPublisher(MetaConfig(dry_run=True))
        publish_service = PublishingService(store, workflow, publisher)
        result = publish_service.publish(workflow_id, platform="facebook", text=draft)

        final = workflow.get(workflow_id)
        output("[7/7] SUMMARY")
        output(f"      State: {final['state']}")
        output(f"      Grounding: PASS")
        output(f"      Approval: explicit demo auto-approval")
        output(f"      Publish: {result.status} / {result.external_id}")
        output("      External network posts created: 0")
        return {
            "workflow_id": workflow_id,
            "state": str(final["state"]),
            "draft": draft,
            "publish_status": result.status,
            "external_id": result.external_id,
            "generator_mode": mode,
        }
