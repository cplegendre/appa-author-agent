# Real-world validation — Meta publishing

This procedure validates the current publishing path against a **dedicated Meta test Page**. It is deliberately opt-in: the script runs only a dry-run unless both `--live` and the literal confirmation `LIVE_META_TEST` are supplied.

## Safety prerequisites

Use a Page/account intended for testing, not a production author Page. Keep `publishing.enabled: false` for ordinary development. Store the token only in the environment; never add it to YAML, shell history, fixtures, logs, or the repository.

Configure a local-only override (or equivalent `AUTHOR_AGENT__META__...` environment override) with a Facebook Page ID, and export the token:

```bash
export META_ACCESS_TOKEN='...'
export AUTHOR_AGENT__META__FACEBOOK_PAGE_ID='YOUR_TEST_PAGE_ID'
```

The validation script constructs its own temporary workflow databases. It drives each workflow through:

```text
INGESTED → ANALYZED → DRAFTED → VALIDATED → REVIEW_REQUIRED → APPROVED → PUBLISHING → PUBLISHED
```

## 1. Mocked/unit validation

From a clean checkout:

```bash
pip install -e ".[dev]"
pytest -q
```

The mocked tests cover successful publishing, retry/idempotency, HTTP 429/rate-limit payloads, Meta error code 190/expired tokens, invalid media URL payloads, and secret redaction.

## 2. Local dry-run validation

No Meta credentials are required:

```bash
python scripts/validate_meta_publish.py
```

Expected result:

```text
DRY-RUN PASS: ...; duplicate call returned same publication
LIVE NOT RUN: ...
```

The script publishes the same approved workflow twice through the dry-run provider and asserts both calls resolve to the same external ID, proving the duplicate-publish guard is active.

## 3. Live test-Page validation — human opt-in required

After configuring a dedicated test Page and reviewing `TEST_TEXT` in `scripts/validate_meta_publish.py`:

```bash
python scripts/validate_meta_publish.py --live --confirm LIVE_META_TEST
```

This creates **one real low-risk Facebook test post**, then invokes the same publish operation again with the same workflow/content idempotency key and asserts that no second post is created.

If Meta returns an error, APPA surfaces domain-specific failures for rate limiting, expired tokens, and invalid media while redacting configured secrets from logs and exception text.

## Validation record

Date: **2026-09-14**

- Mocked Meta error-path tests: implemented and run locally.
- Local dry-run workflow/idempotency cycle: run locally; passed.
- Real Meta live publish: **NOT RUN in this build environment** because no live Meta credentials/test Page were provided. This step remains a deliberate human action using the command above.

A live validation result should be appended here after a human runs it against the dedicated test Page, including the date, Page type, resulting Meta post ID, and any API/version-specific issues observed. Do not record the access token.
