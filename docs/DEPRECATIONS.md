# Deprecated compatibility settings

APPA v1.0 keeps two legacy configuration keys so existing local configurations continue to validate. They are not required for new deployments.

## `ollama.coding_model`

Retained for backward-compatible configuration parsing. No current runtime generation, review, RAG, or publishing path consumes this setting.

## `automation.mode`

Retained for backward-compatible configuration parsing. Publication safety is controlled by the durable workflow state machine, explicit human approval, `publishing.enabled`, `publishing.dry_run`, and the global publishing kill-switch.

## Removal policy

Because settings validation rejects unknown keys, removing either key would break existing configuration files. Their removal is therefore reserved for a future explicit breaking configuration revision.

Historical version-specific deprecation notes are preserved under `docs/archive/` where relevant.
