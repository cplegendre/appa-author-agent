# v29 changelog — structural cleanup only

## Scope

No product feature was added. v29 is a pure refactor/removal release. The default safety contract is unchanged: publishing disabled by default, dry-run enabled by default, explicit human approval required, and `PUBLISHING_KILL_SWITCH` checked by the existing live-publish path.

## Orchestration split

The former 943-line `author_agent/orchestration.py` monolith is now a 22-line compatibility facade. Implementation is split by responsibility:

- `publishing_orchestration.py` — release/evergreen orchestration (215 lines)
- `orchestration_generation.py` — model-payload normalization/retry (211 lines)
- `orchestration_validation.py` — release/editorial contract validation (221 lines)
- `orchestration_factual.py` — factual grounding and cross-draft similarity (169 lines)
- `orchestration_review.py` — draft regeneration/manual edits (140 lines)
- `orchestration_scheduling.py` — release schedule selection (104 lines)
- `orchestration_types.py` — dependency contract (24 lines)

The facade preserves the import names exercised by `test_editorial_v15.py`, `test_editorial_v16.py`, `test_factual_grounding_v21.py`, `test_factual_review_v23.py`, `test_hashtag_trim.py`, `test_release_url_placeholder_leak.py`, `test_cross_series_and_status_bugs.py`, and `test_rag_sanitization_v22.py`.

## CLI split

`author_agent/main.py` was reduced from 567 lines in v28 to 254 lines. Parsing now lives in `author_agent/cli/parser.py`; workflow/publish/evaluation dispatch lives in `author_agent/cli/operations.py`; reusable RAG/content context helpers live in `author_agent/content_services.py`. `main.py` is now the compatibility/composition boundary: configure runtime dependencies, expose thin historical wrappers used by web/daemon callers, parse arguments, and dispatch.

Behavioral compatibility is covered by `test_main.py`, `test_main_more.py`, `test_web.py`, `test_web_more.py`, `test_daemon.py`, `test_runners.py`, and the existing publishing/campaign tests.

## Dead code removed

- Removed the private `_meta_publisher()` wrapper from `main.py`. Repository-wide reference search showed no caller; active publishing already goes through `cli/publishing.py` and is covered by `test_v25_publishing.py`, `test_meta.py`, `test_social_retry.py`, and `test_v28_operational_hardening.py`.
- Removed the private `_output_dir()` wrapper from `main.py`. Repository-wide reference search showed no caller; output path behavior remains implemented in `publishing_orchestration.output_dir()` and is exercised through release/evergreen tests.
- Removed imports made obsolete by the split (`re`, evaluation/vision/workflow imports, campaign/publishing facade imports) from `main.py`. These were static dead imports after delegation.
- Removed a stale v28 compatibility comment left behind in `orchestration_review.py`; scheduling compatibility now lives only in the `orchestration.py` facade.

No externally exercised compatibility function was removed. Thin wrappers still referenced by the web UI, daemon, or the 300-test regression suite are intentionally retained rather than falsely classified as dead code.

## Versioning / freeze

Package version is `0.29.0`. The README now contains an explicit **Scope freeze** section: no new functionality until module-size/code-debt targets are under control.
