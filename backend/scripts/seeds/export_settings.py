"""Export the team's settings documents as a committable seed.

Writes ``scripts/seeds/settings_seed.json``. Settings had no export path at all:
`seed_settings.py` writes the CODE defaults for missing namespaces, so a value
changed in the UI (a default model, a token limit, the embedding model) stayed on
one machine and nothing said so.

Two things are stripped on the way out, both load-bearing:

  * **secrets** — ``models.api_keys`` holds provider keys encrypted with this
    machine's ``API_KEY_ENCRYPTION_KEY``. Shipping them would ship the key too,
    and every teammate needs their own anyway.
  * **machine paths** — ``workspace.workspace_path`` is an absolute path from the
    exporting machine (the same reason agent rows are scrubbed to
    WORKSPACE_BASE).

What is exported, and what is deliberately not: the namespaces that carry TEAM
decisions — agents, models, rag, runtime, storage, workspace. `general` (theme,
language) and `onboarding` (setup_complete) are skipped: one is per-person
cosmetic, the other would let a teammate's install skip the setup wizard that
asks for their API keys.

Usage:
    cd backend
    .venv/bin/python scripts/seeds/export_settings.py            # write the file
    .venv/bin/python scripts/seeds/export_settings.py --stdout    # preview
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import text                      # noqa: E402
from db.database import SessionLocal             # noqa: E402

SEEDS_DIR = Path(__file__).resolve().parent
OUT_FILE = SEEDS_DIR / "settings_seed.json"

# Namespaces that carry team decisions. Order is the file's order.
TEAM_NAMESPACES = ["agents", "models", "rag", "runtime", "storage", "workspace"]

# Per-namespace keys removed before writing (secrets / machine-specific).
STRIP: dict[str, tuple[str, ...]] = {
    "models": ("api_keys",),
    "workspace": ("workspace_path",),
}


def scrub(ns: str, doc: dict) -> tuple[dict, list[str]]:
    """Drop secrets and machine paths; return (clean doc, what was dropped)."""
    out = copy.deepcopy(doc)
    dropped: list[str] = []
    for key in STRIP.get(ns, ()):
        if key in out:
            out.pop(key)
            dropped.append(f"{ns}.{key}")

    # Any absolute path left anywhere in the document is machine-specific.
    def walk(node, path=""):
        if isinstance(node, dict):
            for k, v in list(node.items()):
                if isinstance(v, str) and v.startswith("/") and len(v) > 1:
                    node[k] = ""
                    dropped.append(f"{ns}.{path}{k}")
                else:
                    walk(v, f"{path}{k}.")
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{path}{i}.")

    walk(out)
    return out, dropped


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--stdout", action="store_true", help="print instead of writing")
    ap.add_argument("--out", default=str(OUT_FILE))
    args = ap.parse_args(argv)

    db = SessionLocal()
    try:
        rows = {r[0]: r[1] for r in db.execute(text(
            "SELECT ns, document FROM settings_documents"))}
    finally:
        db.close()

    payload: dict = {"__meta__": {
        "exported_namespaces": [],
        "skipped": {},
        "stripped": [],
        "note": "Applied by seed_all.py with a three-way merge: a key the "
                "teammate has changed is left alone, an untouched one adopts "
                "the team value. See core/settings/team_seed.py.",
    }}

    for ns in TEAM_NAMESPACES:
        doc = rows.get(ns)
        if not isinstance(doc, dict):
            payload["__meta__"]["skipped"][ns] = "no document in this database"
            continue
        clean, dropped = scrub(ns, doc)
        payload[ns] = clean
        payload["__meta__"]["exported_namespaces"].append(ns)
        payload["__meta__"]["stripped"].extend(dropped)

    for ns in sorted(set(rows) - set(TEAM_NAMESPACES)):
        payload["__meta__"]["skipped"][ns] = "not a team namespace (see module docstring)"

    text_out = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    if args.stdout:
        print(text_out)
        return 0

    Path(args.out).write_text(text_out, encoding="utf-8")
    print(f"wrote {args.out} — {len(payload['__meta__']['exported_namespaces'])} namespace(s), "
          f"{len(payload['__meta__']['stripped'])} value(s) stripped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
