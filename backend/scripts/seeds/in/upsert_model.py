"""Idempotently add or update ONE row in the `models` catalog table.

Why this exists: the legacy ``scripts/seed_models.py`` (since removed) deleted
every ``source='cloud'`` row
and re-inserts the hardcoded list, which would also throw away models added
through ``POST /api/settings/models``. Use this script to bring a live database
in line with a catalog change (e.g. the DeepSeek vision model) without touching
any other row.

Examples
--------
    cd backend

    # Show what the presets contain / what is already in the DB
    .venv/bin/python scripts/seeds/in/upsert_model.py --list
    .venv/bin/python scripts/seeds/in/upsert_model.py --show deepseek-flash

    # Add (or refresh) the DeepSeek image-input model
    .venv/bin/python scripts/seeds/in/upsert_model.py --preset deepseek-flash

    # Any other model, ad hoc
    .venv/bin/python scripts/seeds/in/upsert_model.py \
        --model-id my-vl-model --display-name "My VL" --provider deepseek \
        --caps '{"streaming": true, "tools": true, "structured_output": true, "vision": true, "max_context": 1000000}'

    # Soft-disable a row (keeps history, hides it from pickers)
    .venv/bin/python scripts/seeds/in/upsert_model.py --deactivate deepseek-v4-flash

The script only ever touches the ``models`` table. It never deletes rows, and
``--caps`` is merged into the existing capabilities JSON unless you pass
``--replace-caps``.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from pathlib import Path

for _p in Path(__file__).resolve().parents:
    if (_p / "_seedpaths.py").exists():
        sys.path.insert(0, str(_p))
        break
from _seedpaths import BACKEND, REPO  # noqa: E402


# ── Presets ──────────────────────────────────────────────────────────────────
# Facts sourced from the vendor docs (verified 2026-10):
#   https://api-docs.deepseek.com/quick_start/pricing   (Vision ✓ flash / ✗ pro, 1M ctx, 384K out)
#   https://api-docs.deepseek.com/guides/vision/        (image payload shapes + limits)
PRESETS: dict[str, dict] = {
    "deepseek-flash": {
        "model_id": "deepseek-flash",
        "display_name": "DeepSeek Flash (V4.1, Vision)",
        "provider": "deepseek",
        "capabilities": {
            "streaming": True,
            "tools": True,
            "structured_output": True,
            "vision": True,
            "max_context": 1000000,
            "max_output": 384000,
            # USD / 1M tokens at peak (cache-miss input, output); off-peak is half.
            "input_price": 0.30,
            "output_price": 1.20,
            # Spelling the registry cost path actually reads (core/models/registry.py:421).
            "price_per_1m_input": 0.30,
            "price_per_1m_output": 1.20,
            "speed_tps": 83,
            "thinking": True,
            "open_source": True,
            "license": "MIT",
            "release": "2026-09",
            "strength": "Native image understanding + agents (screenshots, scans, charts)",
            "aliases": ["deepseek-v4-flash", "deepseek-v4-flash-vision-exp"],
            "notes": (
                "Images: base64 data URL, public http(s) URL, or Files API file_id. "
                "JPEG/PNG/GIF/WebP, <=600 images/request, ~1024 tokens per image."
            ),
            "architecture": "DeepSeek-V4.1-Flash",
        },
    },
}


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Upsert or inspect one row of the `models` catalog table.")
    p.add_argument("--preset", choices=sorted(PRESETS), help="Upsert a known catalog entry by name.")
    p.add_argument("--model-id", help="Model id to upsert (e.g. deepseek-flash).")
    p.add_argument("--display-name", help="Human-readable name (defaults to the model id).")
    p.add_argument("--provider", help="Provider key (e.g. deepseek).")
    p.add_argument("--caps", help="Capabilities JSON object, e.g. '{\"vision\": true}'.")
    p.add_argument("--replace-caps", action="store_true",
                   help="Replace capabilities instead of merging into the existing JSON.")
    p.add_argument("--deactivate", metavar="MODEL_ID", help="Set is_active=false on an existing row.")
    p.add_argument("--activate", metavar="MODEL_ID", help="Set is_active=true on an existing row.")
    p.add_argument("--show", metavar="MODEL_ID", help="Print one row's capabilities and exit.")
    p.add_argument("--list", action="store_true", help="List cloud rows (model_id, provider, vision, active).")
    p.add_argument("--dry-run", action="store_true", help="Print the intended write without committing.")
    return p.parse_args(argv)


def _connect():
    """Open a DB session, or exit with a clear message when Postgres is down."""
    try:
        from db.database import SessionLocal
    except Exception as e:  # pragma: no cover - import-time environment problem
        sys.exit(f"✗ Could not import the app DB layer: {e}")

    db = SessionLocal()
    try:
        from sqlalchemy import text
        db.execute(text("SELECT 1"))
    except Exception as e:
        db.close()
        sys.exit(
            "✗ Cannot reach Postgres. The catalog lives in the app database "
            "(POSTGRES_HOST/PORT/DB in the project-root .env; docker-compose maps 5433).\n"
            f"  Underlying error: {e}"
        )
    return db


def _resolve_spec(args: argparse.Namespace) -> dict:
    """Build the row spec from --preset, or from the ad-hoc CLI flags."""
    if args.preset:
        return PRESETS[args.preset]
    if not args.model_id:
        sys.exit("✗ Pass --preset <name>, or --model-id with --display-name/--provider.")
    caps: dict = {}
    if args.caps:
        try:
            caps = json.loads(args.caps)
        except json.JSONDecodeError as e:
            sys.exit(f"✗ --caps is not valid JSON: {e}")
        if not isinstance(caps, dict):
            sys.exit("✗ --caps must be a JSON object.")
    if not args.provider:
        sys.exit("✗ --provider is required when --model-id is used.")
    return {
        "model_id": args.model_id,
        "display_name": args.display_name or args.model_id,
        "provider": args.provider,
        "capabilities": caps,
    }


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    from models.model import Model

    db = _connect()
    try:
        if args.list:
            rows = db.query(Model).filter(Model.source == "cloud").order_by(
                Model.provider, Model.model_id
            ).all()
            print(f"{len(rows)} cloud models:")
            for m in rows:
                caps = m.capabilities or {}
                vision = "vision" if caps.get("vision") else "     -"
                active = "active  " if m.is_active else "inactive"
                print(f"  {active} {vision} {m.provider:<10} {m.model_id:<32} {m.display_name}")
            return 0

        if args.show:
            row = db.query(Model).filter(Model.model_id == args.show).first()
            if not row:
                sys.exit(f"✗ '{args.show}' is not in the models table.")
            print(json.dumps(row.to_dict(), indent=2, default=str))
            return 0

        if args.deactivate or args.activate:
            target = args.deactivate or args.activate
            row = db.query(Model).filter(Model.model_id == target).first()
            if not row:
                sys.exit(f"✗ '{target}' is not in the models table.")
            wanted = bool(args.activate)
            if args.dry_run:
                db.rollback()
                print(f"(dry-run) would set is_active={wanted} on {target}")
            else:
                row.is_active = wanted
                db.commit()
                print(f"✓ {row.model_id}: is_active={row.is_active}")
            return 0

        spec = _resolve_spec(args)
        row = db.query(Model).filter(Model.model_id == spec["model_id"]).first()
        action = "update" if row else "insert"

        if row:
            merged = dict(row.capabilities or {})
            if args.replace_caps:
                merged = dict(spec["capabilities"])
            else:
                merged.update(spec["capabilities"])
            planned = {
                "display_name": spec["display_name"],
                "provider": spec["provider"],
                "source": "cloud",
                "is_active": True,
                "capabilities": merged,
            }
        else:
            planned = {
                "model_id": spec["model_id"],
                "display_name": spec["display_name"],
                "provider": spec["provider"],
                "source": "cloud",
                "is_active": True,
                "capabilities": dict(spec["capabilities"]),
            }

        print(f"{action}: {spec['model_id']}")
        print(json.dumps(planned, indent=2, sort_keys=True))

        if args.dry_run:
            db.rollback()
            print("(dry-run) nothing committed")
            return 0

        if row:
            for key, value in planned.items():
                setattr(row, key, value)
        else:
            row = Model(**planned)
            db.add(row)
        db.commit()

        saved = db.query(Model).filter(Model.model_id == spec["model_id"]).first()
        print(f"✓ committed ({action}) — vision={bool((saved.capabilities or {}).get('vision'))}, "
              f"active={saved.is_active}")
        print("  Next: verify with `GET /api/settings/models`, then select it on the "
              "agent/workflow node (Settings → Models for the default).")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
