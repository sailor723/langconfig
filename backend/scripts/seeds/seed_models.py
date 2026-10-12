"""
Seed the unified `models` table from /tmp/models_with_url.csv (the "initial query").

Run once after dropping + recreating the `models` table:
    cd backend && DATABASE_URL="postgresql://langconfig:langconfig_dev@localhost:5432/langconfig" \
        .venv/bin/python scripts/seeds/seed_models.py

Source of truth: /tmp/models_with_url.csv. Run /tmp/export_models.py first if the CSV
is missing.

Columns read: provider, model_id, display_name, is_active, source, api_base_url_default
Columns written: model_id, display_name, provider, source, capabilities (default), is_active

Local models are NOT touched — they are managed by the user via Settings > Local Models.
"""
import csv
import os
import sys
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from db.database import SessionLocal
from models.model import Model

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

CSV_PATH = os.environ.get("MODELS_CSV", "/tmp/models_with_url.csv")
# --refresh-existing restores the previous overwrite behaviour (see the branch below).
_REFRESH_EXISTING = "--refresh-existing" in sys.argv

# Default capability set per provider — used when seeding since the CSV does not
# carry full capability JSONs. Keeping this minimal but realistic.
DEFAULT_CAPS = {
    "openai":     {"streaming": True, "tools": True, "structured_output": True, "vision": True},
    "anthropic":  {"streaming": True, "tools": True, "structured_output": True, "vision": True},
    "google":     {"streaming": True, "tools": True, "structured_output": True, "vision": True},
    "deepseek":   {"streaming": True, "tools": True, "structured_output": True},
    "glm":        {"streaming": True, "tools": True, "structured_output": True},
    "minimax":    {"streaming": True, "tools": True, "structured_output": True, "vision": True},
    "qwen":       {"streaming": True, "tools": True, "structured_output": True},
    "kimi":       {"streaming": True, "tools": True, "structured_output": True},
    "agnes":      {"streaming": True, "tools": True, "structured_output": True},
}


def main() -> int:
    refresh_existing = _REFRESH_EXISTING
    if not os.path.exists(CSV_PATH):
        print(f"ERROR: CSV not found at {CSV_PATH}. Run /tmp/export_models.py first.")
        return 1

    added = 0
    updated = 0
    kept = 0
    skipped_local = 0
    with open(CSV_PATH, newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        print(f"ERROR: {CSV_PATH} is empty")
        return 1

    print(f"Read {len(rows)} rows from {CSV_PATH}")
    db = SessionLocal()
    try:
        for row in rows:
            provider = (row.get("provider") or "").lower()
            model_id = (row.get("model_id") or "").strip()
            display_name = (row.get("display_name") or model_id).strip()
            source = (row.get("source") or "cloud").strip().lower()
            is_active = (row.get("is_active") or "t").strip().lower() in ("t", "true", "1", "yes")

            if not provider or not model_id:
                print(f"  skip: missing provider/model_id -> {row}")
                continue

            # Skip local rows (managed by user via Settings UI, not by seed).
            if source != "cloud":
                skipped_local += 1
                continue

            existing = db.query(Model).filter(Model.model_id == model_id).first()
            caps = dict(DEFAULT_CAPS.get(provider, {"streaming": True}))
            if existing:
                # INSERT-ONLY by default. This used to overwrite display_name,
                # provider, source, capabilities and is_active on every run —
                # and `caps` comes from the PER-PROVIDER DEFAULT_CAPS table, so a
                # re-seed silently flattened per-model metadata (pricing, vision,
                # max_context, strength, aliases) back to the provider default.
                # A teammate's own catalogue edits were collateral too. Pass
                # --refresh-existing to opt into the old behaviour.
                if not refresh_existing:
                    kept += 1
                    continue
                existing.display_name = display_name
                existing.provider = provider
                existing.source = source
                existing.capabilities = caps
                existing.is_active = is_active
                updated += 1
            else:
                db.add(Model(
                    model_id=model_id,
                    display_name=display_name,
                    provider=provider,
                    source=source,
                    capabilities=caps,
                    is_active=is_active,
                ))
                added += 1
        db.commit()
    finally:
        db.close()

    print(f"Done. Added={added} Updated={updated} Kept_existing={kept} "
          f"Skipped_local={skipped_local}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())