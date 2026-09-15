# Changelog

## v1.0.0 — initial public release

v1.0.0 is the first public stable release of APPA (Author Promotion & Publishing Agent).

The public release consolidates the pre-v1 development series into a stable baseline with:

- local Ollama generation, factual review, and embeddings;
- durable workflow state and transition history;
- explicit human edit/approve/reject review flow;
- terminal `REJECTED` workflows;
- review queue and stale-review alerts;
- explicit post-role metadata (`teaser`, `launch`, `reminder`, `evergreen`);
- Facebook/Instagram Meta publishing with dry-run, idempotency, bounded retries, structured logging, alerting, and a global kill-switch;
- - plain-text social-output validation that retries Markdown/paragraph-formatting failures with corrective prompts, and only falls back to a conservative, wording-preserving auto-fix (strip stray emphasis markers, split long unbroken text at sentence boundaries) after repeated retries — never a silent, unbounded strip;;
- durable campaign planning/scheduling and metric capture;
- localhost review dashboard and human-gated website Git workflow;
- CI with Ruff, mypy, pytest, and a 90% minimum coverage gate;
- Apache-2.0 licensing and public-repository hygiene.
- removal of an obsolete pre-v1 paragraph auto-reflow regression test that contradicted the current reject-and-regenerate formatting contract.

### Compatibility

The public package version is `1.0.0`. Internal SQLite schema versions are persistence implementation details and are not reset to `1`.

Two legacy configuration keys remain accepted for backward compatibility; see `DEPRECATIONS.md`.

## Pre-v1 development history

The project evolved through a private/internal `0.x` series. Detailed engineering notes for the later stabilization/refactor releases are retained under `docs/archive/releases/`, and historical architecture notes are retained under `docs/archive/architecture/`.

These files are historical records, not current setup/operations documentation.
