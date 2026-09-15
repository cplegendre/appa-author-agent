# Author Agent v28 — Operations Runbook

Author Agent remains **dry-run by default** and **requires explicit human approval** before a workflow can publish. Production operators should treat `PUBLISHING_KILL_SWITCH=true` as the immediate stop control.

## 1. Verify that a post was published

1. Inspect the durable workflow:
   ```bash
   python run.py workflow status <WORKFLOW_ID>
   ```
   A completed live post should be `PUBLISHED` (or `MEASURED` after metrics refresh) and contain an `external_id`.
2. Check `output/daemon.log` / service logs for a JSON `publication_attempt` event with `"outcome":"success"` and the same workflow/platform.
3. Confirm the post in the Facebook Page / Instagram account itself. The Meta object ID is the authoritative remote reference; local state alone is not proof that the content is visible.
4. Optionally refresh metrics after publication:
   ```bash
   python run.py metrics <WORKFLOW_ID> --platform facebook
   # or --platform instagram
   ```

## 2. Recover after a daemon/process crash

The queue and workflow state are stored in `data/automation.sqlite3`; a process restart does not erase scheduled work.

```bash
systemctl --user status author-agent.timer author-agent.service
systemctl --user restart author-agent.timer
python run_daemon.py --run-once
python run.py publish-due
```

Before manually retrying a failed publication, inspect `workflow status`, `publish_attempts`/logs, and Meta itself to avoid creating a duplicate. Idempotency prevents replay of an already recorded successful attempt, but operators must still verify ambiguous network failures remotely before forcing recovery.

## 3. Revoke or renew a Meta token

1. **Stop publication first:** `export PUBLISHING_KILL_SWITCH=true` (and put the same value in the service `.env` if systemd loads it there).
2. Revoke/rotate the token in the Meta developer/business tooling associated with the Facebook Page and Instagram professional account.
3. Replace the value of the environment variable configured by `meta.access_token_env` (default: `META_ACCESS_TOKEN`). Never commit the token.
4. Restart the service process so the new token is loaded where applicable.
5. Validate credentials/target/media with:
   ```bash
   python run.py meta-preflight --platform facebook
   python run.py meta-preflight --platform instagram --media-url https://public.example/image.jpg
   ```
6. Only after preflight succeeds, clear the kill-switch.

Expired-token errors are non-retryable; they generate a failed publication event and the configured alert.

## 4. Activate / clear the global kill-switch

Immediate stop:
```bash
export PUBLISHING_KILL_SWITCH=true
```

For a systemd deployment, set `PUBLISHING_KILL_SWITCH=true` in the `.env` loaded by `author-agent.service`. The switch is checked dynamically **before every real publication API call/retry**, including the second step of Instagram container publishing. Dry-run remains usable while the switch is active because it performs no Meta publication call.

Resume only after the incident is understood:
```bash
export PUBLISHING_KILL_SWITCH=false
```

## 5. Publication failure alerts

Set a Slack-compatible incoming webhook in the variable configured by `notifications.alert_webhook_env` (default `AUTHOR_AGENT_ALERT_WEBHOOK`). Publication failures and exhausted retry budgets produce structured JSON error logs and trigger the webhook. Alert delivery is best-effort and never hides the original publishing error.
