# v27 changelog

## Goal

Raise Author Agent from a strong single-release publishing agent toward a campaign-aware social promotion system while retaining v26 safety guarantees.

## Implemented

- Added durable campaign planning (`campaigns`, `campaign_slots`).
- Added a default five-touch, 16-day post-release promotion sequence for Facebook and Instagram.
- Added timezone-aware per-platform posting slots and same-platform minimum-gap enforcement.
- Added campaign-slot materialization into the existing durable workflow state machine.
- Added measured explore/exploit selection for hook style, copy length, and CTA style.
- Persisted campaign experiment features so later metrics can train the selection policy.
- Normalized Meta analytics names into the scoring vocabulary.
- Added Meta preflight for credentials, target lookup, and Instagram media reachability/type.
- Fixed Graph GET calls to use query parameters instead of request bodies.
- Bumped additive automation schema to v27 and package version to 0.27.0.
- Added v27 architecture and command documentation.

## Verification

- `290 passed`
- total test coverage: `90.24%` (required minimum: 90%)
- `python -m compileall` passes
- CLI help loads
- campaign planner smoke test passes

Ruff and mypy remain CI requirements but could not be run in the build environment because those executables were not installed.
