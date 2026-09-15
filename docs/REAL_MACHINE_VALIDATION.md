# Real-machine validation: systemd → draft → notification → review

This checklist is a one-time end-to-end validation for a real Linux desktop. It verifies the parts that mocked CI cannot prove: the systemd user timer actually wakes, the daemon runs in your login environment, a native desktop notification is visible, and the FastAPI UI discovers the generated backlog.

> **Safety:** this procedure does not publish to Facebook/Instagram and does not automatically push or merge Git changes. The daemon always uses the existing `today_cmd` flow with website patching in dry-run mode.

## Preconditions

From the project directory:

```bash
source .venv/bin/activate
pip install -e ".[dev]"
ollama list
```

Confirm the models configured in `config/settings.yaml` exist. Also confirm the CLI itself is healthy:

```bash
author-agent --help
```

For a visible desktop notification, install `notify-send` if your distribution does not already provide it. On Debian/Ubuntu it is normally supplied by `libnotify-bin`.

Check your graphical-session environment from a terminal opened inside the desktop session:

```bash
printf 'DISPLAY=%s\nWAYLAND_DISPLAY=%s\nDBUS_SESSION_BUS_ADDRESS=%s\n' \
  "$DISPLAY" "$WAYLAND_DISPLAY" "$DBUS_SESSION_BUS_ADDRESS"
command -v notify-send
```

At least one of `DISPLAY`, `WAYLAND_DISPLAY`, or `DBUS_SESSION_BUS_ADDRESS` should normally be set.

## 1. Schedule a run a few minutes in the future

Back up your current local settings if necessary:

```bash
cp -n config/settings.local.yaml config/settings.local.yaml.before-validation 2>/dev/null || true
```

Create or edit `config/settings.local.yaml`. Pick a time 3–5 minutes ahead using your machine's local clock:

```yaml
orchestrator:
  daily_run_time: "09:42"   # replace with a time a few minutes from now
```

`settings.local.yaml` is intentionally ignored by Git.

Install/update the user units:

```bash
author-agent-daemon --install-systemd
systemctl --user enable --now author-agent.timer
```

If you changed the time after installing the units, run the install command again so the timer file is regenerated.

## 2. Confirm systemd sees the timer

```bash
systemctl --user status author-agent.timer --no-pager
systemctl --user list-timers author-agent.timer
```

Confirm that `NEXT` is the time you selected and that the unit is `author-agent.timer`.

You can inspect the generated unit files if needed:

```bash
systemctl --user cat author-agent.service
systemctl --user cat author-agent.timer
```

The service should be `Type=oneshot`; no Python scheduling process should remain running between triggers.

## 3. Let the timer fire and confirm the daemon run

After the scheduled time:

```bash
systemctl --user status author-agent.service --no-pager
journalctl --user -u author-agent.service --since "10 minutes ago" --no-pager
```

Also inspect the project log:

```bash
tail -n 100 output/daemon.log
```

A successful new generation should contain events similar to:

```text
daemon_run_started
daemon_output_generated
desktop_notification delivered=True
```

If today's manifest already existed before this validation, the daemon should instead log an idempotent no-op. To test a fresh generation, either use a date/release state that has no existing `output/today-YYYY-MM-DD.json`, or temporarily move that day's manifest aside and restore it afterward.

Do **not** use `--force` in the systemd service for normal daily operation.

## 4. Visually confirm the desktop notification

The expected notification contains only a short status, for example:

```text
Author Agent: draft ready
New release draft ready: Bilingual Yok 4 — review at http://127.0.0.1:8765
```

It intentionally does not include the generated post copy.

This step requires a **human visual check**. A zero exit code from `notify-send` alone is not sufficient for this validation.

If no notification appears, test the desktop notification channel directly from the same graphical terminal:

```bash
notify-send --app-name="Author Agent" "Author Agent validation" "Desktop notifications are working"
```

Then inspect:

```bash
journalctl --user -u author-agent.service --since "10 minutes ago" --no-pager
```

Expected degraded behavior when no desktop session is available (for example SSH-only execution): the draft is still generated, a warning is logged, and the service exits successfully rather than crashing.

## 5. Confirm the web UI discovers the unreviewed draft

The daemon does **not** require the web server to be running. Start it only now:

```bash
author-agent-web --port 8765
```

Open:

```text
http://127.0.0.1:8765
```

Confirm all of the following:

1. The **Needs your review** banner appears near the top of the page.
2. The freshly generated item appears in **History**.
3. Opening it loads the normal editable review workspace rather than a separate read-only view.
4. Facebook/Instagram drafts, duplicate scores, and preview are present as expected.
5. If it is a release with a website change, the website section shows the dry-run diff. No Git push should have happened from the daemon.

You may then mark the draft approved normally if this is a real production draft. Approval should continue to register the social copy in the SQLite RAG corpus.

## 6. Optional manual idempotency check

Trigger the same daily service again:

```bash
systemctl --user start author-agent.service
```

Then inspect:

```bash
tail -n 50 output/daemon.log
```

With today's manifest already present, the second run should report an existing-manifest/no-op state and should not generate a duplicate draft or a second notification.

## 7. Clean up / disable the daily timer

If you are not ready to leave daily scheduling enabled:

```bash
systemctl --user disable --now author-agent.timer
```

Optionally remove the installed unit files entirely:

```bash
rm -f ~/.config/systemd/user/author-agent.service
rm -f ~/.config/systemd/user/author-agent.timer
systemctl --user daemon-reload
systemctl --user reset-failed author-agent.service 2>/dev/null || true
```

Restore your normal schedule in `config/settings.local.yaml`, or remove the temporary local override:

```bash
rm -f config/settings.local.yaml
```

If you created a backup, restore it instead.

## Pass criteria

Consider the real-machine validation successful when all of these are true:

- systemd reports the timer with the expected next trigger;
- `author-agent.service` fires as a one-shot job;
- `output/daemon.log` records the run;
- a real desktop notification is visibly displayed in a graphical session;
- absence of a graphical session degrades to a warning without failing generation;
- the new draft appears in the web UI's **Needs your review** backlog;
- a second trigger is idempotent;
- no social post is auto-published and no Git push occurs without the existing explicit web Prepare → Push action.
