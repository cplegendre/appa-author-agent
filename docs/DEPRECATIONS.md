# v28 deprecations and scope freeze

v28 is a stabilization release. No new end-user publishing capability was added.

## Deprecated compatibility settings

- `ollama.coding_model`: retained so existing configuration files still validate, but no runtime path consumes it. Do not use it for new deployments; removal is reserved for a future breaking configuration revision.
- `automation.mode`: retained for backward-compatible configuration parsing. The production safety model is the explicit workflow state machine + human approval + `publishing.enabled`/`publishing.dry_run`; no runtime publication decision currently depends on `automation.mode`.

These settings are intentionally **not removed in v28** because `extra="forbid"` configuration validation would turn their removal into a breaking change for existing production `.yaml`/environment configurations.

## Removed / archived obsolete material

- v26 architecture and pre-live validation documents were moved to `docs/archive/`; they are historical and no longer describe the production operating baseline.
- Publishing/campaign CLI implementation was removed from the monolithic `main.py` and moved to `author_agent/cli/`.
- Daily release selection/scheduling was removed from the monolithic `orchestration.py` and moved to `author_agent/orchestration_scheduling.py`.

No inactive experimental runtime module was deleted because the apparently experimental `demo` and `evaluation` packages are still reachable from supported CLI commands (`quickstart` and `eval`). Removing them would therefore be a feature removal rather than dead-code cleanup.
