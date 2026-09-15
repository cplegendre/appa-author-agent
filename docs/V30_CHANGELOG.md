# v30 changelog — human-review UX completion

## Scope

v30 is a narrowly scoped UX/safety release. It does not add publishing platforms, autonomous publishing, campaign types, or new generation capabilities. Existing defaults remain unchanged: publishing disabled, dry-run enabled, explicit human approval required, and the global kill-switch authoritative.

## Review state and rejection

- Added terminal `REJECTED`.
- `workflow reject <ID> --reason "..."` requires a non-empty reason.
- Rejection is allowed only before publication (including approved/scheduled work that has not been sent yet).
- The reason and timestamp are persisted in the existing transition history.
- `REJECTED` has no outgoing transitions; the publishing service's existing approved/scheduled guard therefore rejects it before any provider call.
- Existing persisted `REVIEW_REQUIRED` remains supported. `IN_REVIEW` is accepted as a compatibility spelling without migrating old rows.

## Draft editing and factual review

- Added `workflow edit <ID> --field ... --value ... [--actor ...]`.
- Edits are persisted in `workflow_edits` with field, old/new text, actor, timestamp and `factual_recheck_required`.
- Editing is only allowed while in review.
- An edited review workflow moves back to `DRAFTED`, clears approval, and records a transition explaining that factual re-validation is required. This intentionally preserves the existing factual-review safety contract.

## Human review queue

- Added `workflow queue` with book/platform/age filtering and age/book/platform sorting.
- Rows expose ID, book, platform, post role and review age in days.
- The existing HTML dashboard now includes the same human-review queue rather than introducing a separate web UI.

## Explicit post roles

- Release generation returns `post_roles`: Facebook/Instagram=`launch`, teaser=`teaser`.
- Evergreen generation returns Facebook/Instagram=`evergreen`.
- Campaign workflows persist normalized `post_role`; intermediate campaign touches map to `reminder`.
- Queue/dashboard views display this role explicitly.

## Stale-review alerting

- Added `notifications.stale_review_days` (default `3`).
- The daily daemon checks review age and sends stale-review notifications through the existing Slack-compatible alert webhook mechanism.
- Alert failure remains best-effort and cannot stop normal draft generation.

## Verification

- 300 pre-v30 regression tests remain green.
- 9 v30 tests cover rejection/history/publication guard, edit auditing and factual recheck, queue filtering/roles, dashboard rendering, generation role metadata, stale-review alert reuse, CLI operations and invalid-state guards.
- Total: 309 tests passing.
- Coverage: 90.03% with the existing 90% CI floor unchanged.

## v30.1 bugfix — plain-text social formatting

- Social-generation prompts now explicitly forbid Markdown emphasis, headings and Markdown bullet lists for Facebook, Instagram and teaser copy.
- Prompts explicitly require blank-line paragraph separators (`\n\n` inside JSON strings) instead of collapsed one-block prose.
- Added a post-generation validation guard that rejects Markdown-formatted drafts and long single-block drafts; invalid model output uses the existing bounded regeneration path rather than silently stripping characters.
- Instagram hashtags remain valid; the guard distinguishes `#ChildrensBooks` from Markdown headings such as `# Title`.
- Targeted field regeneration uses the same formatting guard and one corrective retry.
- Evergreen generation uses the same plain-text/paragraph contract as release generation.
- Regression tests cover Markdown retry, missing-paragraph retry, and clean multi-paragraph acceptance.
- No publishing, approval, dry-run, kill-switch, or workflow-state behavior changed.
