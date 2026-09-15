# APPA — Author Promotion & Publishing Agent

**APPA** is a local-first assistant for preparing, reviewing, scheduling, and publishing book-promotion posts to Facebook and Instagram.

The AI pipeline runs locally through **Ollama**. Social publishing uses the Meta Graph API only after an explicit human approval step. APPA is designed around conservative production defaults: publishing is disabled by default, dry-run is enabled by default, and a global kill-switch can stop all live publication calls immediately.

> Current public release: **v1.0.0**

## What APPA does

APPA supports the complete path from a published book to reviewed social promotion:

- ingest book/release metadata and extract supporting evidence;
- generate Facebook, Instagram, teaser, reminder, and evergreen copy;
- retrieve previous books/posts through local SQLite RAG to reduce repetition;
- run factual grounding/review before human approval;
- preserve readable plain-text social formatting (no Markdown in published copy);
- let a human edit, approve, or permanently reject a workflow;
- queue and schedule approved posts;
- publish to Facebook Pages and Instagram professional accounts through Meta;
- retry transient failures, record structured publication logs, and alert on failures;
- persist workflows so scheduled work survives process restarts;
- collect post-publication metrics for lightweight campaign feedback;
- optionally update a companion author website through a human-gated Git workflow.

## Safety model

APPA is intentionally safe by default.

- `publishing.enabled: false` — live publishing is off until explicitly enabled.
- `publishing.dry_run: true` — publication commands simulate by default.
- Human approval is mandatory before a workflow can publish.
- `PUBLISHING_KILL_SWITCH=true` blocks every real Meta publication API call and retry.
- Editing reviewed/approved social copy invalidates the prior factual/approval state and requires re-validation.
- `REJECTED` workflows are terminal and cannot be published.
- Meta credentials and alert webhooks are read from environment variables, not committed configuration.
- The web UI binds to localhost by default.

See [RUNBOOK.md](RUNBOOK.md) for production operations and incident recovery.

## Scope freeze

v1.0.0 is intentionally feature-frozen. The current goal is stability, documentation, and operational confidence rather than adding publishing platforms, autonomous behavior, campaign types, or new content formats.

New features should not be added until structural debt and compatibility paths are demonstrably under control and the regression suite remains green.

## Requirements

- Python 3.11+
- Ollama running locally
- Git
- Meta developer/business credentials only if live Facebook/Instagram publishing is enabled
- Linux/systemd is optional, but supported for scheduled daemon execution

Default local models are configured in `config/settings.yaml`:

```yaml
ollama:
  base_url: http://localhost:11434
  marketing_model: qwen3:14b
  review_model: gemma4:12b
  embedding_model: embeddinggemma:latest
```

The deprecated `ollama.coding_model` setting is retained only for backward-compatible configuration parsing; no runtime publishing path depends on it.

## Installation

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Install the configured Ollama models, for example:

```bash
ollama pull qwen3:14b
ollama pull gemma4:12b
ollama pull embeddinggemma:latest
```

Verify the CLI:

```bash
author-agent --help
```

## Safe quickstart

The bundled demo exercises the local pipeline without requiring Meta credentials:

```bash
make demo
```

Equivalent command:

```bash
author-agent quickstart
```

The demo uses `author_agent/demo_data/sample_book.pdf` and keeps publication in dry-run mode.

## Configuration

The committed baseline is `config/settings.yaml`. Put machine-specific overrides in local/environment configuration rather than editing secrets into the tracked file.

Copy the environment template if useful:

```bash
cp .env.example .env
```

Important variables:

```bash
META_ACCESS_TOKEN=
AUTHOR_AGENT__META__FACEBOOK_PAGE_ID=
AUTHOR_AGENT__META__INSTAGRAM_ACCOUNT_ID=
AUTHOR_AGENT__PUBLISHING__ENABLED=false
AUTHOR_AGENT__PUBLISHING__DRY_RUN=true
PUBLISHING_KILL_SWITCH=false
AUTHOR_AGENT_ALERT_WEBHOOK=
```

Do not commit `.env`, tokens, local SQLite databases, generated output, logs, or backups. The repository `.gitignore` excludes the normal runtime locations.

## Workflow lifecycle

The durable workflow state machine is persisted in `data/automation.sqlite3`.

Typical lifecycle:

```text
INGESTED
  → ANALYZED
  → DRAFTED
  → VALIDATED
  → REVIEW_REQUIRED / IN_REVIEW
  → APPROVED
  → SCHEDULED
  → PUBLISHING
  → PUBLISHED
  → MEASURED
```

Terminal/recovery states include `REJECTED`, `FAILED`, and `CANCELLED`.

A rejected workflow can never be published. Editing a workflow during review deliberately returns it to `DRAFTED` so factual validation runs again before approval.

### Human review commands

```bash
author-agent workflow queue --sort age
author-agent workflow status <WORKFLOW_ID>
author-agent workflow reject <WORKFLOW_ID> --reason "Needs a different launch angle"
author-agent workflow edit <WORKFLOW_ID> --field facebook_text --value "Revised copy"
```

The queue exposes workflow ID, book, platform, post role, and review age, with filters for common review triage.

## Generating content

Direct release generation:

```bash
author-agent release --help
```

Evergreen generation:

```bash
author-agent evergreen --help
```

Daily orchestration:

```bash
author-agent today --help
```

Generated social copy is plain text. The generation/validation boundary rejects Markdown-style emphasis/headings/lists and rejects long single-block social drafts that should contain paragraph breaks. Invalid generations are retried rather than silently stripped.

## Campaigns

Campaign planning creates durable post slots while preserving the same factual review and human approval gates.

```bash
author-agent campaign plan --book /path/to/book.pdf --release-date 2026-09-15 --create-workflows
author-agent campaign status <CAMPAIGN_ID>
```

Roles are explicit in workflow/output metadata (`teaser`, `launch`, `reminder`, `evergreen`) rather than being inferred only from prompt text.

## Meta publishing

Live publishing is opt-in.

1. Set `META_ACCESS_TOKEN` and the Facebook/Instagram account IDs.
2. Keep `publishing.dry_run: true` while validating configuration.
3. Run preflight checks.
4. Explicitly enable publishing only when ready.

Preflight examples:

```bash
author-agent meta-preflight --platform facebook
author-agent meta-preflight --platform instagram --media-url https://public.example/cover.jpg
```

Publish an approved workflow:

```bash
author-agent publish <WORKFLOW_ID> --platform facebook --text "Approved post text"
```

Resume due deferred jobs:

```bash
author-agent publish-due
```

The Meta adapter handles bounded retries for transient network/server/rate-limit failures. Expired tokens and other non-retryable failures fail explicitly. Publication attempts are logged as structured JSON and can trigger the configured Slack-compatible alert webhook.

For an opt-in real-account validation procedure, see [docs/REAL_WORLD_VALIDATION.md](docs/REAL_WORLD_VALIDATION.md).

## Kill-switch

Emergency stop:

```bash
export PUBLISHING_KILL_SWITCH=true
```

The switch is checked dynamically before each real publication API call/retry. Dry-run remains available while the kill-switch is active because it performs no real Meta publication call.

Clear only after the incident is understood:

```bash
export PUBLISHING_KILL_SWITCH=false
```

## Local web UI

Start the localhost dashboard:

```bash
author-agent-web --port 8765
```

Then open:

```text
http://127.0.0.1:8765
```

The dashboard exposes the review backlog/history, editable drafts, preview, approval/rejection flows, and the existing human-gated website Prepare → Push workflow.

## Scheduled daemon / systemd

Run once:

```bash
python run_daemon.py --run-once
```

Install the user-level systemd units:

```bash
author-agent-daemon --install-systemd
systemctl --user enable --now author-agent.timer
```

Useful diagnostics:

```bash
systemctl --user status author-agent.timer author-agent.service
journalctl --user -u author-agent.service --since "30 minutes ago"
tail -n 100 output/daemon.log
```

See [docs/REAL_MACHINE_VALIDATION.md](docs/REAL_MACHINE_VALIDATION.md) for the one-time desktop/systemd validation checklist.

## RAG and factual grounding

APPA uses local SQLite RAG for two distinct purposes:

- previous posts provide style/repetition context;
- book/release evidence provides factual grounding.

Historical style examples are sanitized before they reach the generation model so old titles, URLs, series positions, and release facts are not treated as current facts.

Useful RAG commands are available under:

```bash
author-agent rag --help
```

## Metrics and evaluation

Refresh metrics for a published workflow:

```bash
author-agent metrics <WORKFLOW_ID> --platform facebook
```

Run the deterministic quality evaluation harness:

```bash
author-agent eval
author-agent eval --json
```

Analytics are advisory. They do not bypass factual review, approval, or publication safety gates.

## Architecture

The codebase is deliberately split by responsibility:

- `author_agent/orchestration_generation.py` — generation and retry flow
- `author_agent/orchestration_validation.py` — editorial/social-output validation
- `author_agent/orchestration_factual.py` — factual grounding/review
- `author_agent/orchestration_review.py` — review/edit/approval-oriented operations
- `author_agent/orchestration_scheduling.py` — release selection/scheduling
- `author_agent/publishing_orchestration.py` — publication workflow coordination
- `author_agent/publishing/` — provider abstraction and Meta implementation
- `author_agent/workflow/` — durable workflow state machine
- `author_agent/campaigns/` — campaign planning/materialization
- `author_agent/analytics/` — metric snapshots/scoring
- `author_agent/rag.py` / `rag_commands.py` — local retrieval/index operations
- `author_agent/cli/` — CLI parser and command handlers
- `author_agent/web.py` / `dashboard.py` — localhost review UI/API

`author_agent/orchestration.py` remains a thin compatibility facade for stable imports.

A current architectural overview is in [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Development

Install hooks:

```bash
pre-commit install
```

Run the same quality gates as CI:

```bash
ruff check .
mypy .
pytest --cov=author_agent --cov-fail-under=90
```

GitHub Actions runs linting, type checking, and the test/coverage gate on pushes and pull requests.

## Public-repository hygiene

Never commit:

- `.env` or Meta/Slack credentials;
- `data/` or SQLite runtime databases;
- `output/` or generated social drafts/logs;
- backups;
- local virtual environments/caches;
- private book manuscripts unless they are intentionally redistributable fixtures.

The included `sample_book.pdf` is a deliberately small fictional demo fixture.

## Documentation

- [RUNBOOK.md](RUNBOOK.md) — production operations and incident recovery
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — current system architecture
- [docs/CHANGELOG.md](docs/CHANGELOG.md) — public release notes and development-history summary
- [docs/DEPRECATIONS.md](docs/DEPRECATIONS.md) — retained compatibility settings
- [docs/REAL_WORLD_VALIDATION.md](docs/REAL_WORLD_VALIDATION.md) — opt-in live Meta validation
- [docs/REAL_MACHINE_VALIDATION.md](docs/REAL_MACHINE_VALIDATION.md) — systemd/desktop validation
- `docs/archive/` — historical pre-v1 engineering notes

## License

Copyright 2026 Cédric Legendre.

Licensed under the **Apache License 2.0**. See [LICENSE](LICENSE) and [NOTICE](NOTICE).
