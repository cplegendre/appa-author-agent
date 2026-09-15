# APPA v1.0 architecture

APPA is a local-first author-promotion pipeline. AI generation, embeddings, and factual review run through a local Ollama endpoint; Meta Graph API is used only for explicit social publication/metrics operations.

## High-level flow

```text
Book / release metadata
        ↓
Evidence extraction + local RAG
        ↓
Social generation (Ollama)
        ↓
Formatting/editorial validation
        ↓
Factual grounding/review (Ollama)
        ↓
Human review: edit / approve / reject
        ↓
Scheduling
        ↓
Meta publisher (dry-run or live)
        ↓
Metrics + durable history
```

## Safety boundaries

- Publishing is disabled by default.
- Dry-run is enabled by default.
- Human approval is mandatory.
- `PUBLISHING_KILL_SWITCH=true` is checked before each live publication call/retry.
- Edited review copy requires factual re-validation.
- `REJECTED` is terminal and non-publishable.
- Credentials remain environment-only.
- Structured logs redact configured secrets.

## Durable state

`data/automation.sqlite3` stores workflows, transition history, campaigns, publishing attempts, scheduled work, and metric snapshots. `data/rag.sqlite3` stores local retrieval data.

The database schema version is an internal persistence version and is intentionally independent of the public package version (`1.0.0`).

## Responsibility split

### Orchestration

- `orchestration_generation.py` — prompt execution, parsing, regeneration/retry flow
- `orchestration_validation.py` — editorial, plain-text social, paragraph, duplication, and output guards
- `orchestration_factual.py` — factual claim review/evidence handling
- `orchestration_review.py` — review/edit-related orchestration helpers
- `orchestration_scheduling.py` — release/date selection and scheduling helpers
- `publishing_orchestration.py` — workflow-to-publication coordination
- `orchestration.py` — compatibility facade only

### Workflow and persistence

- `workflow/service.py` — state machine and transition rules
- `persistence.py` — SQLite persistence and migration primitives

### Publishing

- `publishing/base.py` — provider contract
- `publishing/meta.py` — Meta Graph API adapter, retries, preflight, kill-switch checks
- `publishing/service.py` — durable publishing/idempotency layer

### Content intelligence

- `book_evidence.py` — book/release evidence model
- `rag.py`, `rag_commands.py` — local retrieval/indexing
- `brand_voice.py` — style/voice configuration
- `prompt_templates/` — generation/review contracts
- `analytics/` — metric capture and advisory scoring
- `campaigns/` — campaign/slot planning and workflow materialization

### Interfaces

- `cli/` — CLI parser and command handlers
- `web.py`, `dashboard.py`, `web_static/` — localhost review UI/API
- `daemon.py`, `daemon_runner.py` — scheduled one-shot orchestration

## External dependencies

- Ollama: local text generation, factual review, embeddings; optional local vision.
- Meta Graph API: Facebook/Instagram publishing, preflight, and metrics.
- SQLite: durable workflow/RAG state.
- FastAPI/Uvicorn: localhost dashboard.
- systemd user units: optional Linux scheduling.

No hosted LLM provider is required by the default pipeline.
