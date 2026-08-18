"""Import `.env` API-key-style values into the encrypted `models.api_keys` settings doc.

Background
==========
After this commit the only things left in `.env` are operator-only
infrastructure (Postgres creds, Fernet master, ENV, OAuth callback URL).
Per-team API keys live in the DB, encrypted at rest, editable from
the Settings panel.

This script is the **canonical import path** for these values
(one-shot for legacy installs; no-op for fresh ones):

  LANGSMITH_API_KEY       -> models.api_keys.langsmith_api_key
  GOOGLE_CLIENT_ID         -> models.api_keys.google_client_id
  GOOGLE_CLIENT_SECRET     -> models.api_keys.google_client_secret
  SLACK_WEBHOOK_URL        -> models.api_keys.slack_webhook_url
  DISCORD_WEBHOOK_URL      -> models.api_keys.discord_webhook_url

The values are passed plain to `mutate()`; the store's
`encrypt_document_secrets` walk automatically encrypts every field marked
``json_schema_extra={"role":"secret"}`` (langsmith / google_client_secret /
slack / discord), while `google_client_id` (a public identifier, not
secret) stays plain.

The script is **idempotent**:
  - reads the current .env
  - reads the current `models.api_keys` from the DB
  - for each key:
      * if the .env value is empty/placeholder  -> skip
      * if the DB already has a non-empty value  -> skip (don't overwrite)
      * else                                    -> write the .env value to DB
  - prints a short report

After running once, the team can delete those keys from
their local `.env` (already done in this commit).

Usage
=====
    cd backend
    uv run python scripts/import_api_keys_to_db.py            # import
    uv run python scripts/import_api_keys_to_db.py --dry-run  # show plan
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Allow `from db...` etc. when run as a script.
_BACKEND = Path(__file__).resolve().parents[1]
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from db.database import SessionLocal
from core.settings.store import (
    ensure_table,
    get_document,
    mutate,
)

# (env_key, doc_field, placeholder_substrings)
# If a .env value contains any placeholder_substring, we skip it (it's a
# template/default, not a real secret).
_KEYS = [
    ("LANGSMITH_API_KEY",   "langsmith_api_key",   ("CHANGE", "YOUR", "REPLACE", "lsv2_pt_xxx")),
    ("GOOGLE_CLIENT_ID",     "google_client_id",    ("YOUR", "REPLACE")),
    ("GOOGLE_CLIENT_SECRET", "google_client_secret", ("GOCSPX-", "REPLACE")),
    ("SLACK_WEBHOOK_URL",    "slack_webhook_url",   ("YOUR", "REPLACE", "slack.com/services/YOUR")),
    ("DISCORD_WEBHOOK_URL",  "discord_webhook_url", ("YOUR", "REPLACE", "discord.com/api/webhooks/YOUR")),
]


def _is_placeholder(value: str, placeholders: tuple[str, ...]) -> bool:
    """True if the value looks like a template placeholder, not a real secret."""
    if not value:
        return True
    lowered = value.lower()
    return any(ph.lower() in lowered for ph in placeholders)


def _load_env() -> dict[str, str]:
    """Tiny .env parser — no external dependency, mirrors what the backend
    would do at startup (pydantic-settings also reads .env)."""
    env = {}
    p = _BACKEND.parent / ".env"
    if not p.exists():
        return env
    for line in p.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        env[k.strip()] = v.strip()
    return env


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="Show what would change, do not write to DB")
    args = ap.parse_args()

    env = _load_env()
    # We also honour the live process env (overrides file), so a CI invocation
    # can override without editing .env.
    env.update({k: v for k, v in os.environ.items() if k in {e for e, _, _ in _KEYS}})

    db = SessionLocal()
    try:
        ensure_table(db)
        doc = get_document(db, "models") or {}
        api_keys = (doc.get("value") or {}).get("api_keys") or {}

        applied: list[tuple[str, str, int]] = []  # (field, value-prefix, length)
        skipped_empty: list[str] = []
        skipped_placeholder: list[str] = []
        skipped_present: list[str] = []
        errors: list[str] = []

        for env_key, doc_field, placeholders in _KEYS:
            value = env.get(env_key, "").strip()
            if not value:
                skipped_empty.append(f"{env_key} (empty in .env)")
                continue
            if _is_placeholder(value, placeholders):
                skipped_placeholder.append(f"{env_key} (placeholder)")
                continue
            if api_keys.get(doc_field):
                skipped_present.append(
                    f"{env_key} -> {doc_field} (already set in DB, preserved)"
                )
                continue

            # Pass plain value to mutate; the store's encrypt_document_secrets
            # walk will Fernet-encrypt it on persist (since the schema marks
            # this field as `role: "secret"`).
            try:
                if not args.dry_run:
                    mutate(
                        db,
                        "models",
                        [{"op": "set", "path": ["api_keys", doc_field], "value": value}],
                    )
                applied.append((doc_field, value[:8] + "...", len(value)))
            except Exception as e:
                errors.append(f"{env_key} -> {doc_field}: {e}")
                continue
            # refresh local cache (next loop iteration reads from doc again)
            doc = get_document(db, "models") or {}
            api_keys = (doc.get("value") or {}).get("api_keys") or {}

        # ── Report ──
        print("\n== migrate_api_keys_to_db ==")
        if args.dry_run:
            print("(DRY-RUN — no DB writes performed)\n")
        print(f"applied: {len(applied)}")
        for field, prefix, n in applied:
            print(f"  + {field:<22s} ({n} chars, prefix={prefix})")
        print(f"skipped (empty in .env):     {len(skipped_empty)}")
        for s in skipped_empty:
            print(f"    - {s}")
        print(f"skipped (placeholder value): {len(skipped_placeholder)}")
        for s in skipped_placeholder:
            print(f"    - {s}")
        print(f"skipped (already set in DB): {len(skipped_present)}")
        for s in skipped_present:
            print(f"    - {s}")
        if errors:
            print(f"ERRORS: {len(errors)}")
            for s in errors:
                print(f"    ! {s}")
            return 1
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
