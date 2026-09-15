# Author Agent v27 architecture

v27 extends the v26 local-first safety architecture with a campaign-intelligence layer. It does not replace factual grounding, approval, publishing idempotency, or the durable workflow state machine.

## New components

### `author_agent/campaigns/service.py`

`CampaignPlanner` creates a durable post-release campaign with separate Facebook and Instagram slots. The default sequence is:

1. release day — launch / availability,
2. day +2 — inside-the-book curiosity,
3. day +5 — character or theme connection,
4. day +9 — read-aloud / reader-value hook,
5. day +16 — evergreen rediscovery.

Each slot records platform, goal, CTA intent, scheduled timestamp, experiment attributes, status, and (once materialized) its workflow ID. The planner enforces a configurable minimum same-platform spacing and uses timezone-aware datetimes.

Campaign slots can be materialized into ordinary `INGESTED` workflows. This is intentional: campaign intelligence decides **what kind of post and when**, while the existing grounded generation and human-approval pipeline decides **what the post actually says**.

## Experiment policy

`AnalyticsService.recommend_variant()` implements a bounded explore-then-exploit policy. For a defined candidate set, variants below `analytics.minimum_samples` are selected first. Once every variant has adequate evidence, the candidate with the highest median weighted performance score is selected.

v27 experiments only editorial attributes such as hook style, copy length, and CTA style. It never experiments with factual claims about a book.

## Meta preflight and request hardening

`MetaPublisher.preflight()` validates the configured target before live publication and, for Instagram, validates that the public media URL is reachable and image-like. Graph GET calls now transmit arguments as URL query parameters rather than request bodies.

Provider metrics are normalized before analytics. For example:

- `saved` → `saves`
- `post_impressions_unique` → `reach`
- `post_impressions` → `impressions`

This ensures fetched engagement actually participates in the existing weighted scoring model.

## Persistence

`schema_version=27` adds two tables:

- `campaigns`
- `campaign_slots`

The migration remains additive. Existing workflow, publish-attempt, visual-evidence, metric, feature, and RAG data are not deleted or recreated.

## Safety invariants retained

- publishing disabled by default,
- publishing dry-run by default,
- explicit approval required by the workflow,
- copy changes invalidate approval,
- publish attempts are idempotent,
- platform credentials stay in environment variables,
- campaign planning does not publish or auto-approve content.
