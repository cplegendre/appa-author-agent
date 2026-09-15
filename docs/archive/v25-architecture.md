# Author Agent v25 architecture

v25 preserves the v24 local-first architecture and adds four dependency-inverted subsystems around the existing generation/RAG code.

- `author_agent/workflow/`: durable state machine, transition audit trail, approval hashes, retry/error metadata and publish idempotency registration.
- `author_agent/publishing/`: `SocialPublisher` protocol, Meta adapter and publishing service. External calls are mockable; secrets are never stored in repository configuration.
- `author_agent/vision/`: PDF page rendering, page-level text/visual provenance, hash cache and optional Ollama vision provider.
- `author_agent/analytics/`: metric snapshots, weighted score, post features and minimum-sample guidance.
- `author_agent/evaluation/`: deterministic quality regression harness and fixture corpus.
- `author_agent/persistence.py`: lightweight SQLite schema/version migration (`schema_version=25`) in `data/automation.sqlite3`.

The existing `data/rag.sqlite3` database is not recreated or destructively migrated. v25 state is additive. Publishing and automatic mode both default to off. Changing approved copy clears the approval hash and returns the workflow to `REVIEW_REQUIRED`.

## Operational commands

```bash
pip install -e ".[dev]"
author-agent migrate
author-agent --help
author-agent eval --json
pytest --cov=author_agent --cov-fail-under=90
ruff check .
mypy .
```

For normal local operation, keep `automation.mode: manual` and `publishing.enabled: false`. For integration testing, keep publishing disabled or use `publishing.dry_run: true`.
