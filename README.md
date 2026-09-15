# Author Agent v30.1 (package 0.30.1)


## Scope freeze

Author Agent remains explicitly **feature-frozen** after the targeted v30 review-UX completion. No new publishing platforms, promotion formats, autonomous behaviors, campaign types, or product features will be added until structural debt is under control. The acceptance criteria for lifting the freeze are responsibility-focused modules (target: under 300 lines for orchestration/CLI modules), removal or documented retention of dead/deprecated compatibility paths, and a continuously green regression suite.

The production safety contract is unchanged: **publishing remains disabled by default, dry-run remains enabled by default, human approval remains mandatory, and the global publishing kill-switch remains authoritative.**

## v30 — human-review UX completion

v30 adds only the review UX gaps required before public repository release: terminal rejection with mandatory reason, audited draft editing that forces factual re-validation, a filterable review queue in CLI/dashboard, explicit post-role metadata (`teaser`, `launch`, `reminder`, `evergreen`), and stale-review alerts through the existing alert channel. No publishing platform, autonomous behavior, campaign type, or generation capability was added.

Useful review commands:

```bash
author-agent workflow reject <workflow-id> --reason "Needs a different launch angle"
author-agent workflow edit <workflow-id> --field facebook_text --value "Revised copy"
author-agent workflow queue --sort age
```

A human edit while a workflow is in review deliberately moves it back to `DRAFTED`: because edited copy can introduce new factual claims, the existing factual validation path must run again before approval. `REJECTED` is terminal and cannot be published.

See `docs/V30_CHANGELOG.md` for the implementation and compatibility details.

## v29 — structural cleanup only

v29 introduces no user-facing feature. It completes the structural cleanup started in v28 by splitting orchestration and CLI responsibilities, removing verified-dead wrappers/imports, and documenting why retained compatibility surfaces still exist. See `docs/V29_CHANGELOG.md`.

## v28 — stabilization and production operations

v28 freezes product scope and hardens the existing live Meta publishing path. It adds no new promotion feature: the focus is emergency stop control, structured observability, failure alerts, failure-path testing, smaller responsibility-focused modules, and an operator runbook. **Publishing remains disabled by default, dry-run remains enabled by default, and human approval remains mandatory.**

Key operational controls:

- `PUBLISHING_KILL_SWITCH=true` blocks every real publication API call/retry dynamically.
- `AUTHOR_AGENT_ALERT_WEBHOOK` optionally sends publication-failure alerts to a Slack-compatible webhook.
- See `RUNBOOK.md` for verification, crash recovery, Meta token rotation, and incident shutdown.
- See `docs/DEPRECATIONS.md` for compatibility settings retained but no longer used at runtime.

## v27 — campaign intelligence and Meta preflight

v27 keeps v26's factual-grounding, approval, idempotency, and safe publishing defaults, and adds the missing layer between “a book was published” and “promote it intelligently over time.” Publishing remains **OFF by default**, dry-run remains the default, and campaign planning never bypasses the existing approval workflow.

Major v27 changes:

- **Durable multi-touch launch campaigns**: a default 5-touch sequence (launch, inside-the-book, character/theme, read-aloud hook, evergreen reminder) is planned independently for Facebook and Instagram.
- **Platform-aware cadence**: configurable local timezone and posting times, with a minimum inter-post gap to prevent accidental bursts.
- **Campaign → workflow materialization**: planned slots can create durable `INGESTED` workflows that continue through the existing review/approval/publish state machine.
- **Closed-loop editorial experiments**: hook style, copy length, and CTA style use explore-then-exploit selection backed by measured historical performance; undersampled variants are explored before winners are reused.
- **Analytics normalization**: provider metric names such as Instagram `saved` and Facebook `post_impressions_unique` are normalized to the scoring vocabulary (`saves`, `reach`, etc.).
- **Meta preflight**: validates credentials, target account lookup, and Instagram media reachability/content type before live publishing.
- **Correct Meta GET semantics**: Graph GET requests now send token/metrics/field arguments as query parameters rather than a request body.
- **Schema v27**: additive `campaigns` and `campaign_slots` tables; existing workflow/RAG data is retained.

Useful commands:

```bash
author-agent migrate
author-agent campaign plan --book /path/to/book.pdf --release-date 2026-09-15 --create-workflows
author-agent campaign status <campaign-id>
author-agent meta-preflight --platform instagram --media-url https://public.example/cover.jpg
```

The default campaign sequence is deliberately strategic rather than autonomous copy generation: every slot still enters the existing grounded generation/review/approval pipeline before publishing.

## v26 — hardening pass on v25

v26 keeps the v25 automation architecture and all safe defaults while hardening CI, Meta validation, secret handling, and the local demo path. Publishing remains **OFF by default**, automatic mode remains **OFF by default**, dry-run remains the default publishing mode, approval remains explicit, and the web UI remains localhost-only.

Major v26 changes:

- deterministic evaluation fixtures resolve from the installed package, independent of the invoking working directory;
- strict GitHub Actions CI runs `ruff check .`, `mypy .`, and pytest with a 90% coverage floor on every push and pull request;
- typed Meta failures distinguish rate limiting, expired tokens, and invalid media while sanitizing secrets;
- live publishing configuration fails fast before execution if credentials or a target account are missing;
- `scripts/validate_meta_publish.py` provides an opt-in dry-run/live Meta validation cycle with an idempotency assertion;
- `make demo` / `author-agent quickstart` runs a bundled sample PDF through ingest → analyze → draft → factual review → approval → dry-run publish without requiring Meta credentials;
- pre-commit hooks run Ruff and mypy locally.

### Developer setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pre-commit install
```

Run the same quality gates as CI:

```bash
ruff check .
mypy .
pytest --cov=author_agent --cov-fail-under=90
```

Run the safe end-to-end demo:

```bash
make demo
# equivalent:
author-agent quickstart
```

For opt-in Meta test-Page validation, see `docs/REAL_WORLD_VALIDATION.md`. The validation script is dry-run-only unless `--live --confirm LIVE_META_TEST` is supplied.


## v25 — durable author-marketing automation

v25 evolves the existing local-first assistant into a production-oriented automation pipeline while retaining human approval, factual grounding, dry-run behavior, and the website Git safety gates. Social publishing remains **OFF by default**, automatic mode remains **OFF by default**, and edits after approval invalidate approval.

Major additions:

- durable SQLite workflow state machine with explicit transition history, retry/error state, restart recovery, and manual CLI recovery;
- provider-based social publishing abstraction plus Meta Facebook Page / Instagram Business or Creator implementation, bounded retries, rate-limit handling, audit records, dry-run, idempotency, and duplicate-publish protection;
- page-level multimodal PDF evidence with rendered pages, provenance, content-hash caching, optional local Ollama vision analysis, and graceful text-only fallback;
- timestamped social metric snapshots, configurable weighted performance scoring, feature capture, minimum-sample thresholds, and soft historical guidance;
- deterministic generated-content evaluation harness available with `author-agent eval` / `author-agent eval --json`;
- safe v25 schema migration through `author-agent migrate`. Existing v24 RAG data is left intact; v25 creates a separate `data/automation.sqlite3` database.

> **Social publishing is disabled by default. Configure credentials and explicitly enable publishing before Author Agent can post externally.**

### v24 → v25 migration

Back up `data/` and your configuration, install v25, then run:

```bash
author-agent migrate
```

The migration is additive and versioned. It does not delete or recreate the existing RAG database. Safe defaults are:

```yaml
automation:
  mode: manual
publishing:
  enabled: false
  dry_run: true
book_analysis:
  multimodal_enabled: false
```

### Meta setup

Credentials are environment-only. Set `META_ACCESS_TOKEN`, configure the Page/account IDs in local configuration or `AUTHOR_AGENT__META__...` environment overrides, then explicitly set `publishing.enabled: true`. Start with `publishing.dry_run: true`. Facebook Page text posts are supported; Facebook image URLs and Instagram image publishing use Meta's media endpoints. Instagram requires a publicly reachable media URL. Scheduled Facebook posts use Meta scheduling; deferred Instagram jobs are stored durably and can be resumed after restart by the publishing service.

### Multimodal book analysis

Set `book_analysis.multimodal_enabled: true`, `vision_provider: ollama`, and a vision-capable local model. Pages are rendered with PyMuPDF and visual observations are stored separately from extracted text. Unconfigured vision falls back to text-only extraction. Cached page hashes prevent unchanged pages from being reprocessed.

### Analytics and learning

Published-post metrics are stored as timestamped snapshots. Performance uses configurable weights (shares/comments/saves/clicks/reach plus a small like weight), and historical guidance is suppressed until `analytics.minimum_samples` is reached. Guidance is soft context only; factual claims must still come from book evidence.

### Evaluation

```bash
author-agent eval
author-agent eval --json
```

CI-oriented evaluation uses deterministic project-owned fixtures and requires no paid API. Optional real-model evaluation remains disabled by default.

### Workflow inspection and recovery

```bash
author-agent workflow create --book mybook.pdf --campaign launch --platform instagram
author-agent workflow status WORKFLOW_ID
author-agent workflow transition WORKFLOW_ID FAILED --reason "manual recovery note"
```

The lifecycle is `INGESTED → ANALYZED → DRAFTED → VALIDATED → REVIEW_REQUIRED → APPROVED → SCHEDULED → PUBLISHING → PUBLISHED → MEASURED`, with `FAILED` and `CANCELLED` recovery states.


## v0.23 — robust compact factual review

The factual-grounding reviewer now uses a dedicated compact Ollama JSON schema that returns only blocking
(`unsupported` / `contradicted`) claims. The local review model gets a larger 4096-token output budget,
`temperature=0`, and one automatic retry when the first response is malformed or truncated. Supported claims
and repeated evidence excerpts are omitted from reviewer output to keep responses small and reliable.


## v0.8 — production hardening

v0.8 keeps the v0.7 feature set and focuses on installability, static-analysis hygiene, modularity, typed configuration, and operational robustness. Public CLI commands, localhost-only web behavior, dry-run semantics, human approval, and the Prepare → Push safety gate are preserved.

Highlights:

- `pyproject.toml` is the canonical package/dependency definition;
- editable install plus `author-agent`, `author-agent-web`, and `author-agent-daemon` console scripts;
- Ruff + mypy + pytest/coverage CI;
- orchestration/RAG commands, calendar parsing, Git operations, history serialization, and push-gate state split into focused modules;
- Pydantic-backed typed settings with YAML + local YAML + environment overrides;
- consistent domain exception hierarchy;
- `/health` and `/api/health` readiness endpoints;
- short-lived prepared-push state persisted under `output/` so a web-server restart does not silently invalidate an already-issued token;
- human-readable contextual logging for CLI/daemon/web operations.

## v0.7 — daily scheduling, notifications, and review history

v0.7 turns the existing `today_cmd` workflow into a boring/reliable Linux daily job without introducing a long-running Python scheduler. A **systemd user timer** starts a one-shot `run_daemon.py` process at the configured time; the process calls the same `today_cmd` used by the CLI/web UI and exits. Existing manifest idempotency prevents duplicate daily generation.

New in v0.7:

- systemd user service + timer with configurable `orchestrator.daily_run_time`;
- `output/daemon.log` plus systemd journal visibility;
- best-effort Linux desktop notifications through `notify-send`;
- prominent **Needs your review** backlog banner in the local web UI;
- History tab sourced entirely from existing `output/*.json` files;
- history filters for all / needs review / approved;
- past outputs reopen in the same editable regenerate/preview/approve workspace;
- website Push state is persisted back to the output JSON so history can display it;
- no additional database or scheduler service;
- SQLite connections are now explicitly closed, eliminating the inherited ResourceWarnings from the v0.6 test run.

The web UI remains localhost-only and independent of the daemon. The timer does **not** require FastAPI to be running. It only writes the normal output files; the notification merely tells you where to review them later.

Local-first author-marketing assistant built around **Ollama + SQLite RAG**, with both the original CLI and a new local FastAPI web interface. It generates release, teaser, and evergreen social copy, checks semantic repetition against previous posts/books, previews posts visually, and supports a human-gated website branch/commit/push workflow.


## Operations and health

The web server remains intentionally localhost-only (`127.0.0.1`). Do **not** expose it through a LAN bind, reverse proxy, public tunnel, or Internet-facing service; it has no authentication by design.

Readiness endpoints:

```text
http://127.0.0.1:8765/health
http://127.0.0.1:8765/api/health
```

They report whether configuration loaded and whether the local SQLite RAG database is reachable. Ollama generation is intentionally not called by health checks.

Expected operational failures use domain-specific, actionable errors (configuration, validation, Ollama, RAG, website/Git) rather than raw tracebacks in normal CLI/web paths. Logs remain human-readable and include useful context such as date, mode, and output path for daemon runs.

### Prepared Push resilience

The web Push button still requires a successful explicit **Prepare** first. v0.8 also persists the short-lived prepared token/branch state in `output/.prepared-pushes.json` (ignored by Git). This means a FastAPI process restart no longer silently invalidates an already-issued token while the browser page remains open. Tokens expire automatically; the default TTL is one hour and can be changed with:

```yaml
web:
  push_token_ttl_seconds: 3600
```

This does **not** create automatic pushes: the real `git push` still happens only on the explicit Push click, and merge remains manual.

### Logging

CLI logging level can be selected with `--log-level` or `AUTHOR_AGENT_LOG_LEVEL`. The systemd job also writes `output/daemon.log` and the user journal:

```bash
tail -f output/daemon.log
journalctl --user -u author-agent.service -f
```

## Safety boundaries

These are intentional product features, not missing functionality:

- **No automatic Facebook or Instagram publishing.**
- **No automatic `git push` or merge.** The CLI still stops at local branch + commit.
- The web UI can run a real `git push` **only after you explicitly click Prepare and then Push**. It never pushes during generation or page load, and it never merges.
- `--dry-run` never changes the website repository.
- Dry-run outputs cannot be marked approved and inserted into the RAG.
- SQLite remains the only vector/document store; there is no server vector database.

## Ollama models

The default configuration is compatible with the models already used by this project:

```yaml
ollama:
  marketing_model: qwen3:14b
  review_model: gemma4:12b
  embedding_model: embeddinggemma:latest
  coding_model: devstral-small-2:latest
```

`qwen3:14b` generates marketing copy, `embeddinggemma:latest` powers semantic retrieval/duplicate detection, and `gemma4:12b` reviews suspiciously similar drafts. The coding model remains available for later site/code tasks.

## Install (editable)

`pyproject.toml` is the source of truth for runtime and development dependencies. `requirements.txt` is kept as a runtime-only compatibility file.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
ollama serve
```

Installed entry points:

```bash
author-agent --help
author-agent-web --port 8765
author-agent-daemon --run-once
```

The legacy wrappers remain supported:

```bash
python run.py --help
python run_web.py --port 8765
python run_daemon.py --run-once
```

Check the local models:

```bash
ollama list
```

## Local configuration


### Typed settings and overrides

Settings are validated at process startup with Pydantic. Invalid model names, thresholds, timeout values, log levels, or `orchestrator.daily_run_time` values fail fast with a clear configuration error before generation starts.

Load order, later values winning:

1. `config/settings.yaml`
2. optional ignored `config/settings.local.yaml`
3. environment overrides

Nested environment overrides use double underscores:

```bash
export AUTHOR_AGENT__OLLAMA__TIMEOUT_SECONDS=300
export AUTHOR_AGENT__ORCHESTRATOR__DAILY_RUN_TIME=08:30
export AUTHOR_AGENT__RAG__DUPLICATE_THRESHOLD=0.88
```

`AUTHOR_AGENT_WEBSITE_REPO` remains the convenient dedicated override for the local website repository path, and `AUTHOR_AGENT_LOG_LEVEL` overrides the logging level.

### Release calendar

`config/releases.yaml` is intentionally **not committed** because it can contain absolute paths to manuscripts/images.

```bash
cp config/releases.example.yaml config/releases.yaml
```

Example:

```yaml
releases:
  - date: 2026-09-14
    title: "Bilingual Yok 4"
    book: "/home/me/books/bilingual-04.pdf"
    image: "/home/me/promo/bilingual-04.png"
    url: "https://amazon.example/..."
```

### Website repository

Do not put your machine-local repository path in tracked configuration. Set:

```bash
export AUTHOR_AGENT_WEBSITE_REPO=/home/me/src/yokstories-site
```

Or copy `.env.example` to `.env` and load it in your shell:

```bash
set -a
source .env
set +a
```

`config/settings.local.yaml` is also ignored and may be used for machine-specific overrides.

## Daily orchestrator

```bash
python run.py today
```

`today` reads `config/releases.yaml` and selects the nearest release within the configured window:

- release **today** → release post + website-calendar proposal;
- release **in the future but inside the window** → teaser, no website modification;
- no release inside the window → evergreen post.

Default window:

```yaml
orchestrator:
  window_days: 1
```

Override:

```bash
python run.py today --window 3
```

### Idempotence

A daily manifest prevents accidental regeneration:

```text
output/today-YYYY-MM-DD.json
```

Use:

```bash
python run.py today --force
```

when you intentionally want a new generation.

## Dry-run mode

Supported by `release`, `evergreen`, and `today`:

```bash
python run.py today --dry-run

python run.py release \
  --book /path/book.pdf \
  --image /path/promo.png \
  --date 2026-09-14 \
  --url https://example.com/book \
  --published \
  --dry-run
```

Dry-run still performs the **real LLM generation and RAG duplicate checks**, but:

- no website file is written;
- no Git branch is created;
- no Git commit is created;
- nothing is pushed;
- generated review artifacts go under `output/dry-run/` instead of normal output.

The website diff is calculated in memory so you can review what would change.

## Direct release generation

Published release:

```bash
python run.py release \
  --book /path/book.pdf \
  --image /path/promo.png \
  --date 2026-09-14 \
  --url https://example.com/book \
  --published
```

Teaser/scheduled release: omit `--published`.

## Evergreen generation

```bash
python run.py evergreen --date 2026-09-15 --image /path/optional-promo.png
```

## Review artifacts

A normal generation creates three human-review artifacts:

```text
output/release-....json
output/release-....md
output/release-....-preview.html
```

The Markdown report groups:

- Facebook copy;
- Instagram copy;
- teaser;
- duplicate status (`✅` / `⚠️` / `❌` + similarity score);
- website status and diff;
- GitHub compare URL when available;
- approval checklist;
- link to the visual preview.

The HTML preview renders simple Facebook/Instagram-style cards with the promotional image, caption, hashtags, and an explicit **not published** label. It is intentionally a lightweight review mockup, not a pixel-perfect Meta clone.

## Website patching

The website patcher supports calendar sources in:

- JSON;
- YAML;
- JavaScript arrays (`const/let/var releases = [...]`);
- HTML calendars using `.release-month`, `.release-events`, and `.release-event` blocks.

Auto-detection candidates include:

```text
data/releases.yaml
calendar/releases.yaml
calendar/releases.json
calendar/data.js
calendar/releases.js
calendar/index.html
...
```

The HTML support was added specifically because the live Yok Stories site currently stores its publication calendar directly in `calendar/index.html`, rather than a separate JSON/YAML data file.

For the current site structure, an existing entry such as:

```html
<div class="release-event bilingual">
  <strong>14</strong><span>Bilingual 4</span>
</div>
```

is updated idempotently to the equivalent of:

```html
<div class="release-event bilingual" title="Bilingual Yok 4 — available now">
  <strong>14</strong><span>Bilingual 4 · Published</span>
</div>
```

The patcher keeps the existing short calendar label and does not create a duplicate entry on repeated runs.

### Normal Git flow

For a published release:

```text
validate repository
  ↓
require clean working tree + attached branch
  ↓
detect/validate calendar
  ↓
create or reuse author-agent/YYYY-MM-DD-title branch
  ↓
patch calendar
  ↓
local commit
  ↓
report diff + GitHub comparison URL
  ↓
STOP
```

The **CLI path** deliberately stops here without pushing; v0.5 adds a separate explicit-click Push action in the localhost web UI only.

### Protected error cases

Website patching fails before mutation with actionable English messages for:

- Git not installed/on `PATH`;
- invalid repo path;
- dirty working tree;
- detached HEAD;
- configured calendar file missing;
- unsupported calendar extension;
- malformed JSON/YAML/JS release data;
- malformed/unsupported HTML month structure.

## RAG

SQLite database:

```text
data/rag.sqlite3
```

### Import previous posts

Generic files:

```bash
python run.py rag ingest-posts --file posts.csv --platform facebook
```

Official Meta exports:

```bash
python run.py rag import-meta \
  --file facebook/your_posts_1.json \
  --platform facebook

python run.py rag import-meta \
  --file instagram/posts_1.json \
  --platform instagram
```

Auto-detection is available when filenames follow the Meta export convention:

```bash
python run.py rag import-meta --file your_posts_1.json
python run.py rag import-meta --file posts_1.json
```

### Import previous books

```bash
python run.py rag ingest-book --book /path/to/old-book.pdf --date 2026-08-24
```

### Search / duplicate check

```bash
python run.py rag search "bedtime routine"

python run.py rag check \
  --platform instagram \
  --text "Try asking your child what happens next..."
```

### Approve a generated post

After manual review:

```bash
python run.py rag mark-approved --file output/release-2026-09-14.json
```

This marks it approved and upserts the Facebook/Instagram text into the RAG so later generations can avoid repeating it.

To synchronize JSON outputs whose `approved` field was edited manually:

```bash
python run.py rag sync-approved
```

Dry-run outputs are rejected by approval commands.

## Editorial dashboard

```bash
python run.py dashboard
```

Generates:

```text
output/dashboard.html
```

It summarizes topic frequency over 30/90/365 days, upcoming releases, and over-repetition alerts from the local RAG corpus.

## Error handling

Ollama requests use three attempts with exponential backoff. Typical failure:

```text
Ollama is not reachable at http://localhost:11434.
Run `ollama serve` and verify that the requested model is installed.
```

User-facing validation/errors are consistently English in v0.5.

## Logging

```bash
python run.py --log-level DEBUG today
```

or:

```bash
export AUTHOR_AGENT_LOG_LEVEL=DEBUG
```

Internal status uses Python's `logging` module. `print` is reserved for final CLI-facing output.

## Tests

```bash
python -m pytest -q
```

Coverage:

```bash
python -m pytest -q --cov=author_agent --cov-report=term-missing
```

All Git/Ollama boundaries are mockable; the suite does not require a running Ollama server or a real Git repository.

## CI

`.github/workflows/ci.yml` runs on push and pull request:

```text
pip install -e ".[dev]"
ruff check author_agent tests run.py run_web.py run_daemon.py
ruff format --check run.py run_web.py run_daemon.py
mypy author_agent
python -m pytest -q --cov=author_agent --cov-report=term-missing --cov-fail-under=88
```

No Ollama service or real website repository is required in GitHub Actions.

## Privacy / public-repo hygiene

Ignored local files include:

```text
.env
.env.*
config/releases.yaml
config/releases.local.yaml
config/settings.local.yaml
*.local.yaml
output/
data/rag.sqlite3*
```

The tracked `config/settings.yaml` contains safe defaults only and keeps `website.repo_path` empty. `config/releases.example.yaml` contains placeholders rather than real local filesystem paths.

## Daily scheduling with systemd (v0.7)

Configure the daily time in `config/settings.local.yaml` (recommended) or `config/settings.yaml`:

```yaml
orchestrator:
  window_days: 1
  daily_run_time: "09:00"

notifications:
  desktop: true

web:
  url: "http://127.0.0.1:8765"
```

`daily_run_time` uses local 24-hour `HH:MM` time. The systemd timer is rendered from this value when installed.

Install/update the user units:

```bash
python run_daemon.py --install-systemd
systemctl --user enable --now author-agent.timer
```

The generated service also loads an optional project `.env` (`EnvironmentFile=-.../.env`), so `AUTHOR_AGENT_WEBSITE_REPO` and other machine-local environment values remain available to systemd without being committed.

The generated units live under:

```text
~/.config/systemd/user/author-agent.service
~/.config/systemd/user/author-agent.timer
```

The repository also ships reference templates under `systemd/`. The installed service contains the actual project directory and active Python interpreter, so no machine-specific absolute path is committed to the repo. If you change `daily_run_time`, rerun `python run_daemon.py --install-systemd`, then restart the timer.

Useful commands:

```bash
# See the next scheduled run
systemctl --user list-timers author-agent.timer

# Trigger the exact one-shot daemon manually
python run_daemon.py --run-once

# Run the service through systemd now
systemctl --user start author-agent.service

# Follow systemd logs
journalctl --user -u author-agent.service -f

# Inspect the persistent project-local daemon log
tail -f output/daemon.log

# Disable scheduling
systemctl --user disable --now author-agent.timer
```

The daemon deliberately passes `website_dry_run=True`: background generation may calculate the website diff, but it does not silently create/commit/push a Git branch. Website Prepare and Push remain explicit review actions. Social publishing is still manual.

### Desktop notifications

When a new daily output is created, v0.7 calls the lightweight Linux `notify-send` command. The notification contains only a summary such as:

```text
New release draft ready: Bilingual Yok 4 — review at http://127.0.0.1:8765
```

It does not include generated post content. `notify-send` is optional: if it is missing, or the timer runs without a graphical desktop/session environment (for example SSH), the daemon logs a warning and still completes successfully. Check `output/daemon.log` or `journalctl --user -u author-agent.service` in that case.

The FastAPI server does **not** need to be running when the timer fires. The URL is just a reminder for later review.

## Review backlog and history (v0.7)

On web UI load, `/api/history?filter=needs_review` scans the existing top-level `output/*.json` artifacts. If any generated release, teaser, or evergreen output is still unapproved, a **Needs your review** banner appears above the main tabs.

The new History tab shows most-recent-first entries with:

- generation date;
- mode: release / teaser / evergreen;
- approval state;
- website state: not applicable / not pushed / prepared / pushed.

Filters are available for **All**, **Needs review**, and **Approved**. Clicking an entry reopens the same editor used immediately after generation, including editable textareas, RAG duplicate checks, targeted regeneration, preview, approval, and (for eligible published releases) the existing Prepare → Push workflow. There is intentionally no second read-only history UI.

No new history database is introduced; deleting/moving an output JSON naturally removes it from this browser.

## Local web UI (v0.7)

The web frontend is intentionally **plain HTML/JavaScript with no build step**: for a localhost-only personal tool this keeps installation, debugging, and upgrades simpler than introducing a Node/React toolchain.

Start it with:

```bash
python run_web.py
```

Default URL:

```text
http://127.0.0.1:8765
```

Choose another local port if needed:

```bash
python run_web.py --port 9000
```

### Security boundary — local only

**Do not expose this server to your LAN, the public internet, a reverse proxy, Tailscale funnel, Cloudflare tunnel, or similar network service.** It has no authentication because it is designed to bind only to `127.0.0.1`. `run_web.py` deliberately hard-codes the host to loopback; only the port is configurable.

The FastAPI app also uses a trusted-host check for `127.0.0.1` / `localhost` (plus `testserver` for tests).

### Release screen

The Release tab provides:

1. manuscript upload (`PDF`, text, Markdown);
2. optional promotional image upload;
3. release date, URL, and Published/Scheduled selection;
4. generation through the existing `release_cmd` pipeline;
5. editable Facebook, Instagram, and teaser drafts;
6. inline semantic duplicate scores/warnings from the existing RAG;
7. per-field **Regenerate**, **Check duplicates**, and **Copy** actions;
8. a refreshable visual FB/IG mockup using `preview.py`;
9. website dry-run diff before any Git mutation;
10. explicit **Prepare (branch + commit)** and then **Push** controls;
11. **Mark approved**, which writes the final FB/IG drafts into the existing SQLite RAG.

Generation never creates a website branch from the web page by itself. The initial release call asks `website.py` only for the dry-run diff. The repository changes begin only when **Prepare** is clicked.

### Targeted regeneration

Regenerating one field does **not** re-read or re-analyze the manuscript. The web layer calls the shared generation helper using the already-generated book profile and RAG context:

```text
Facebook Regenerate -> only Facebook changes
Instagram Regenerate -> only Instagram changes
Teaser Regenerate -> only teaser changes
```

Manual edits in the other textareas are persisted before regeneration and remain untouched.

### Live visual preview

The Preview pane renders the same card-style markup used by the CLI-generated preview artifact. After editing text, click **Refresh preview** to persist the current textarea values and re-render the mockup without a full page reload.

The preview is deliberately approximate rather than a pixel-perfect Meta clone; it is a fast visual review surface for image/caption balance and obvious formatting issues.

### Website Prepare → Push gate

For published releases the website panel initially displays the same **dry-run diff** from `website.py`, including the detected calendar format (`HTML`, `JSON`, `YAML`, or `JS`).

The web flow is:

```text
Generate
  ↓
website dry-run only
  ↓
review diff
  ↓
click Prepare
  ↓
local branch + commit
  ↓
short-lived persisted push token
  ↓
click Push
  ↓
git push -u origin <prepared-branch>
  ↓
STOP — merge remains manual
```

The Push button is disabled until Prepare succeeds. The backend also enforces this independently of the browser: a push request without the matching short-lived Prepare token is rejected. The token/branch gate is persisted under ignored `output/` state so a FastAPI restart does not silently invalidate a prepared push; it expires automatically and is consumed after a successful push, so the same approval cannot be replayed.

There is still **no automatic merge** and no social-network publishing.

### Evergreen screen

The Evergreen tab calls the existing `evergreen_cmd` and exposes the same edit/regenerate/check/copy/preview/approval workflow. It intentionally has no website panel.

### Today screen

The Today tab calls the existing `today_cmd`. The date-window/release-selection logic lives in the shared orchestration module and is re-exported through `author_agent.main`; the FastAPI layer does not duplicate it. For a release selected by `today`, website generation is again dry-run-only until the explicit Prepare action.

### Web API design

`author_agent/web.py` remains a route façade. Serialization/history helpers and the persisted push gate live in focused web helper modules, while routes delegate to the existing package rather than maintaining a second implementation of business logic:

```text
release_cmd / evergreen_cmd / today_cmd
regenerate_output_field
_duplicate_report + rag_store
preview.render_post_preview_html
website.prepare_website_update
website.push_website_branch
approve_output_file
```

Uploaded source files are stored under ignored local output state:

```text
output/web_uploads/
```

They are therefore covered by the existing `output/` `.gitignore` rule.

## CLI compatibility

All v0.4 CLI commands remain valid and unchanged. In particular, CLI website behavior still stops at branch + commit and reports the manual `git push` command; the new push capability exists only behind the web UI's explicit human click.

## Tests

```bash
python -m pytest -q
```

Coverage:

```bash
python -m pytest -q --cov=author_agent --cov-report=term-missing
```

The FastAPI route tests use `TestClient` and mock the author-agent generation / Git boundaries. The full test suite requires neither a running Ollama server nor a real Git repository.

## Current v0.11 quality baseline

Run locally with:

```bash
pytest -q --cov=author_agent --cov-report=term-missing
```

The v25 suite extends the legacy tests and CI enforces a **90% minimum overall coverage**. v0.21 adds regression coverage for actual-book passage retrieval, claim-level grounding statuses, contradiction detection, faithful-paraphrase acceptance, and constrained factual correction retries.

## Development quality checks

```bash
pip install -e ".[dev]"
ruff check author_agent tests run.py run_web.py run_daemon.py
ruff format --check run.py run_web.py run_daemon.py
mypy author_agent
python -W error::ResourceWarning -m pytest -q --cov=author_agent --cov-report=term-missing
```

The mypy configuration targets the oldest supported runtime (Python 3.11) while skipping recursive checking of the third-party `pypdf` package. This keeps package type checking focused on `author_agent` and avoids transitive dependency-stub syntax being mistaken for an Author Agent error when development happens on Python 3.12/3.13.

### Social-generation payload robustness

Ollama is still requested to return structured JSON, but local models do not always reproduce the requested schema exactly. v0.11 normalizes common flat and nested payloads such as `social.facebook.caption`, `posts.instagram.content`, `result.facebook.post`, and the simpler platform/text forms.

Initial release generation requires usable Facebook, Instagram, and teaser drafts before writing an output file. Evergreen generation requires usable Facebook and Instagram drafts. If required copy is missing, generation fails clearly and **no empty output is persisted**. Targeted regeneration uses the same nested normalization and still rejects genuinely empty or unrelated payloads. Diagnostic errors expose payload key shapes only, not generated post content.

GitHub Actions runs the same lint/type/test gates without requiring Ollama or a real website repository; network and Git boundaries are mocked by tests.

## Real-machine daemon validation

Before relying on the systemd timer for daily use, run the one-time Linux desktop checklist in [`docs/REAL_MACHINE_VALIDATION.md`](docs/REAL_MACHINE_VALIDATION.md). It verifies the real timer wake-up, daemon log, visible `notify-send` delivery, UI review backlog, idempotency, and cleanup/disable procedure.

The notification path is intentionally best-effort: if no graphical desktop session is available, generation continues and the delivery failure is logged rather than treated as a daemon failure.

## Known limitations

- The web UI is a trusted localhost tool, not a multi-user/authenticated service.
- Prepared Push state is intentionally short-lived and local to the `output/` directory; clearing `output/` requires running Prepare again.
- Health verifies config and SQLite readiness but does not perform a live Ollama model inference.
- Social publishing remains manual by design.
- Git merge remains manual by design.


## v0.14 — established author voice + style-aware RAG

v0.14 changes the social editor from generic short-form marketing copy to the established LéoN NoèL / Yok Stories voice. Facebook launch posts are intentionally long-form and reflective; Instagram posts are narrative but tighter; teasers are curiosity-first and spoiler-safe.

The editorial contract lives in `config/brand_voice.yaml`. It controls target word ranges, hashtag ranges, platform structure, phrases to avoid, the number of historical style exemplars, and the warning threshold for similarity between newly generated drafts. The default Facebook target is 250–450 words; Instagram is 140–260 words plus 10–18 relevant hashtags; teaser copy is 30–70 words.

The existing SQLite RAG now has two distinct jobs during generation:

1. **Anti-duplication context** — semantically similar books/posts tell the model what topics, hooks, phrases, and angles to avoid repeating.
2. **Style exemplars** — up to three historical posts per platform are retrieved from `kind=post` and the matching platform. They are explicitly used only for cadence, paragraph length, structural rhythm, and level of reflection; prompts prohibit copying sentences, hooks, distinctive phrases, or hashtag runs.

Release generation also passes the exact release URL and the richer factual book profile (`series`, `book_number`, `series_total`, `bilingual`, `language_pair`) into the social prompt. Unknown metadata must be omitted rather than guessed. Published Facebook posts can therefore include a direct Amazon link, while published Instagram posts use the established `link in bio` wording.

The three generated release drafts are also compared with each other using the existing local embedding model. The result is stored as `draft_similarity`; a warning highlights when Facebook, Instagram, and teaser are semantically too close even if none duplicates historical content. This is advisory only: it never auto-publishes or silently replaces copy.

Historical style quality improves automatically as approved posts are written back into the existing RAG. Importing the official Meta exports remains the recommended bootstrap path if you want the first generations to already reflect your established posting cadence.


## v0.15 — factual grounding and established launch-post rhythm

v0.15 is a focused editorial-quality pass. It keeps the v0.14 RAG/style architecture, but tightens the generation contract to match the author's real Facebook and Instagram posts more closely.

### Factual grounding

The factual BookProfile is now explicitly the only source of story facts. The social prompts forbid invented scenery, weather, gestures, body language, dialogue, appearance details, emotions, plot events, character gender/pronouns, and unsupported educational/developmental claims. Historical RAG examples remain style/anti-duplication references only; they are never sources of facts for the current book.

Release URLs are also protected deterministically. Facebook may use only the exact configured `RELEASE_URL`; guessed or altered URLs are rejected. Instagram must not print a raw product URL and continues to use the manual `link in bio` workflow.

### Facebook rhythm

Facebook launch copy remains 250–450 words, but the prompt now explicitly prefers the established Yok Stories rhythm: one concrete profile-supported moment followed by 2–4 short reflective paragraphs, usually 1–2 sentences each. It discourages ornate scene-setting, grand metaphors, and generic copywriter prose. When metadata exists, the model is instructed to include the compact `📚 title / series · Book X of Y` block and, for published books, the exact Amazon URL.

### Instagram rhythm

Instagram remains narrative rather than ad-like, with a target of 140–260 words and **12–16 hashtags**. The hashtag mix should include brand/series tags, category/discovery tags, and book-specific theme/language tags, with canonical capitalization such as `#YokStories`, `#ChildrensBooks`, `#PictureBooks`, and `#ReadAloud` when relevant. Raw URLs are rejected.

### Teasers

Teasers remain 30–70 words and are explicitly prohibited from summarizing the full book, revealing the resolution/lesson, saying `available now` before publication, or saying `coming soon` after publication.


## v0.22 — sanitized style RAG and authoritative release metadata

v0.22 hardens the boundary between historical style examples and current-release facts. Historical Facebook/Instagram posts are still retrieved as style exemplars, but before they reach the marketing model Author Agent now masks factual identifiers such as Amazon URLs, `📚` title/footer values, series names found in footer blocks, and `Book X of Y` positions. The prompt receives only a minimal sanitized style record (`platform`, `date`, sanitized `text`, similarity `score`) rather than raw RAG metadata.

Every release prompt also receives an explicit **CURRENT RELEASE FACTS — AUTHORITATIVE** block containing the current title, series, book number, series total, status, date, and exact release URL. Those values override all historical exemplars. Targeted regeneration uses the same block.

Strict deterministic validation now rejects Facebook/Instagram drafts that omit or alter the current title/series, use a conflicting `Book N` / `Book N of M` position, or leak an invented/altered URL. A validation failure is fed into the existing one-retry correction path, so the model is explicitly told which current metadata must be used rather than being allowed to copy values from historical posts.

New release outputs are marked with `editorial_contract_version: "0.23"`.

## v0.21 — book-evidence-assisted factual grounding

v0.21 keeps the existing local-first architecture but upgrades factual review from a compressed BookProfile-only check to a two-source evidence model:

1. the factual BookProfile; and
2. semantically retrieved passages from the **current book file**.

Historical social posts remain style/anti-duplication context only and are never accepted as factual evidence. Current-book passages are extracted page-by-page for PDFs (or chunked for TXT/Markdown), embedded with the configured local embedding model, ranked against the generated draft, and cached in-process for subsequent reviews/regenerations.

The factual reviewer now classifies claims as `direct_fact`, `supported_paraphrase`, `clear_entailment`, `unsupported`, or `contradicted`. Only `unsupported` and `contradicted` claims block generation. This means a faithful paraphrase such as “Tom doesn't rush her” can be accepted when the book explicitly says “Tom waited patiently,” while an invented action such as “Tom nods” is rejected and a statement that conflicts with the book is marked as a contradiction.

On the one permitted corrective retry, the model receives the rejected claims, reasons/evidence, and the retrieved verified book passages. It is instructed to preserve supported claims and platform structure, rewrite only what is necessary, and **not replace one rejected detail with another invented detail**.

New release outputs are marked with `editorial_contract_version: "0.21"`.

## v0.16 editorial hardening

v0.16 tightens the final publication-copy boundary without changing the pipeline architecture.
The shipped `config/brand_voice.yaml` enables strict release metadata validation: published Facebook
copy must include the exact supplied release URL, published Instagram copy must use `link in bio`, and
Instagram must stay within the configured 12–16 hashtag range.

A second-pass factual-grounding review uses the configured Ollama review model against the factual
BookProfile only. Unsupported concrete scene embellishments (invented scenery, gestures, appearance,
pronouns, actions, dialogue, emotions, or plot facts) cause one corrective generation retry before the
copy can reach the UI. Historical RAG posts remain style/anti-duplication context, never factual sources.


## License

Licensed under the Apache License, Version 2.0.
See [LICENSE](LICENSE) for details.
