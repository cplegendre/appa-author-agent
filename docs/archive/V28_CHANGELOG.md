# v28 changelog — stabilization only

- Scope frozen: no new promotion formats, platforms, campaign types, or autonomous behavior.
- Added dynamic global `PUBLISHING_KILL_SWITCH` checked before every real Meta publication call/retry.
- Added structured JSON publication-attempt/API-attempt logs with redaction.
- Added optional Slack-compatible failure webhook (`AUTHOR_AGENT_ALERT_WEBHOOK`).
- Publication failures are persisted as failed attempts; active publishing workflows move to `FAILED` and alerts are best-effort.
- Hardened Meta transport handling for network failures and timeouts with bounded retries.
- Added failure-path tests for network errors, timeouts, expired tokens, rate limiting, dry-run/no-network, kill-switch, alerts, and JSON logs.
- Split publishing/campaign CLI operations out of `main.py` and scheduling out of `orchestration.py`, keeping compatibility exports/wrappers.
- Archived obsolete v26 operational/architecture documents and documented compatibility deprecations.
- Added `RUNBOOK.md` for publication verification, daemon recovery, token rotation, alerts, and kill-switch use.
- Default behavior is unchanged: publishing disabled by default, dry-run enabled by default, and explicit human approval remains mandatory.
