# APPA v1.0 — Operations Runbook

APPA is **dry-run by default** and requires explicit human approval before a workflow can publish. Treat `PUBLISHING_KILL_SWITCH=true` as the immediate emergency stop control.

## 1. Verify that a post was published

Inspect the durable workflow:

```bash
author-agent workflow status <WORKFLOW_ID>
```

A completed live post should be `PUBLISHED` (or `MEASURED` after metrics refresh) and contain an `external_id`.

Then:

1. Check `output/daemon.log` or service logs for a structured `publication_attempt` event with `"outcome":"success"` for the same workflow/platform.
2. Confirm the post directly on the Facebook Page or Instagram account. The Meta object ID is the authoritative remote reference; local state alone is not proof that the post is visible.
3. Optionally refresh metrics:

```bash
author-agent metrics <WORKFLOW_ID> --platform facebook
# or
author-agent metrics <WORKFLOW_ID> --platform instagram
```

## 2. Recover after a daemon/process crash

Workflow and publication state are stored in `data/automation.sqlite3`; restarting the process does not erase scheduled work.

```bash
systemctl --user status author-agent.timer author-agent.service
systemctl --user restart author-agent.timer
python run_daemon.py --run-once
author-agent publish-due
```

Before manually retrying a failed publication, inspect the workflow status, publication attempts/logs, and Meta itself. Idempotency prevents replay of an already recorded success, but an ambiguous network failure should still be verified remotely before forcing recovery.

## 3. Revoke or renew a Meta token

1. Stop publication first:

```bash
export PUBLISHING_KILL_SWITCH=true
```

2. Revoke/rotate the token in the relevant Meta developer/business tooling.
3. Replace the environment variable configured by `meta.access_token_env` (default `META_ACCESS_TOKEN`). Never commit the token.
4. Restart any long-running process/service that needs to reload the environment.
5. Validate the target(s):

```bash
author-agent meta-preflight --platform facebook
author-agent meta-preflight --platform instagram --media-url https://public.example/image.jpg
```

6. Clear the kill-switch only after preflight succeeds.

Expired-token errors are non-retryable; they generate a failed publication event and the configured alert.

## 4. Activate / clear the global kill-switch

Immediate stop:

```bash
export PUBLISHING_KILL_SWITCH=true
```

For a systemd deployment, set the same value in the environment loaded by `author-agent.service`. The switch is checked dynamically before every real publication API call/retry, including the publish step of Instagram container publishing. Dry-run remains usable because it makes no live Meta publication call.

Resume only after the incident is understood:

```bash
export PUBLISHING_KILL_SWITCH=false
```

## 5. Publication failure alerts

Set a Slack-compatible incoming webhook in the variable configured by `notifications.alert_webhook_env` (default `AUTHOR_AGENT_ALERT_WEBHOOK`). Publication failures, exhausted retry budgets, and stale-review warnings use the existing alert mechanism.

Alert delivery is best-effort and never hides the original publishing error.

## 6. Stale human review

The daemon checks workflows left in review longer than `notifications.stale_review_days` (default: 3 days). Inspect the queue with:

```bash
author-agent workflow queue --sort age
```

Approve, edit, or reject the workflow explicitly. Editing review copy returns it to `DRAFTED` so factual validation runs again.

## 7. Reject a workflow permanently

```bash
author-agent workflow reject <WORKFLOW_ID> --reason "Reason for rejection"
```

`REJECTED` is terminal. A rejected workflow cannot be published.
