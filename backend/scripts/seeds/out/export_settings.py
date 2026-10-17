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
    .venv/bin/python scripts/seeds/out/export_settings.py            # write the file
    .venv/bin/python scripts/seeds/out/export_settings.py --stdout    # preview
"""

from __future__ import annotations

import argparse
import copy
import json
import logging
import sys
from pathlib import Path

for _p in Path(__file__).resolve().parents:
    if (_p / "_seedpaths.py").exists():
        sys.path.insert(0, str(_p))
        break
from _seedpaths import BACKEND, IN_DIR, OUT_DIR, REPO, SEEDS  # noqa: E402

logger = logging.getLogger(__name__)


from sqlalchemy import text                      # noqa: E402
from db.database import SessionLocal             # noqa: E402

OUT_FILE = IN_DIR / "settings_seed.json"

# Namespaces that carry team decisions. Order is the file's order.
TEAM_NAMESPACES = ["agents", "models", "rag", "runtime", "storage", "workspace"]

# Per-namespace keys removed as MACHINE-SPECIFIC (not secrets — see below).
STRIP: dict[str, tuple[str, ...]] = {
    "workspace": ("workspace_path",),
}


def scrub(ns: str, doc: dict) -> tuple[dict, list[str]]:
    """Drop every secret the namespace schema declares, plus machine paths.

    Secrets are discovered from the schema (``role="secret"``), not from a
    hand-written list of key names. A list only strips what somebody remembered
    to add: ``models.api_keys`` was stripped while ``models.local_api_key`` —
    the same kind of value, one field away — was exported. It shipped as Fernet
    *ciphertext*, which is not a mitigation: the documented team setup leaves
    ``API_KEY_ENCRYPTION_KEY`` blank so every machine falls back to the same
    built-in key, which means any teammate can decrypt what you exported.
    """
    out = copy.deepcopy(doc)
    dropped: list[str] = []

    try:
        from core.settings import registry
        from core.settings.secrets import delete_at_path, secret_paths

        spec = registry.get(ns)
        for path in secret_paths(spec.schema):
            if delete_at_path(out, path):
                dropped.append(f"{ns}." + ".".join(path))
    except Exception as exc:                     # noqa: BLE001 — never ship on doubt
        # Fail closed: an unreadable schema must not turn into an unsanitised
        # export. Drop the whole document rather than risk a credential.
        logger.warning("scrub: cannot enumerate secrets for %r (%s); "
                       "dropping the whole namespace from the seed", ns, exc)
        return {}, [f"{ns}.* (schema unreadable)"]

    # A container whose every field was a secret (models.api_keys) is now {}.
    for key in [k for k, v in out.items() if isinstance(v, dict) and not v]:
        out.pop(key)
        dropped.append(f"{ns}.{key} (emptied)")

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
