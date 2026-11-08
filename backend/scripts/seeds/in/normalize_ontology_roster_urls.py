"""
Clear what the `ontology` roster still claims about OTHER machines (idempotent).

Two fields, one failure: a roster row that names where a machine keeps its files.

The roster was written when each ontology ran on its OWN workbench process (`:8092`, `:8093`,
`:8096`, `:8098`…), so a row's `url` WAS its identity. Every page is now served by this app at
`/api/ontology/{key}/page/…`, which means the url names nothing: the app compiled the ontology in
the request that answered. Measured on the deployment: four roster rows still said
`http://127.0.0.1:8765` and the installed-only rows said `''`, so a list that compared urls
highlighted five rows at once and a reload picked whichever row sorted first — reported as
"I click coldchain v6 but every other ontology is highlighted".

Rows are normalised to `url: ""` (same-origin). The key stays the identity; `profile` still says
which file the profile is. Labels, notes, order and `default_key` are left exactly as they are.

The same rule applies to the namespace's two machine-specific knobs, `python` and `repo_path`:
they are cleared when they name a path that does not exist on THIS machine (`python: ''` means
"the interpreter that runs the app", `repo_path: ''` means "this app's own feature directory").
Measured on the deployment: `python` still said `/Users/weiping/dev/Learn/cube/tutorial/.venv/bin/python`.

Run from backend/:
    .venv/bin/python scripts/seeds/in/normalize_ontology_roster_urls.py [--dry-run]

Safety: only writes the `ontology` namespace of `settings_documents`, only the `url` field of its
items, only when it is not already empty, and bumps the revision through the ordinary store so the
schema validates and concurrent edits are guarded.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

for _p in Path(__file__).resolve().parents:
    if (_p / "_seedpaths.py").exists():
        sys.path.insert(0, str(_p))
        break
from _seedpaths import BACKEND  # noqa: E402

sys.path.insert(0, str(BACKEND))

from core.settings import store  # noqa: E402
from db.database import SessionLocal  # noqa: E402
from core.settings.store import SettingsDocument  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[1].strip())
    ap.add_argument("--dry-run", action="store_true", help="report what would change, write nothing")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        rows = db.query(SettingsDocument).filter(SettingsDocument.ns == "ontology").all()
        if not rows:
            print("no `ontology` roster rows — nothing to normalise")
            return 0
        changed_total = 0
        for row in rows:
            doc = store.get_document(db, "ontology", user_id=row.user_id)
            items = doc.get("items") or []
            cleared = [(it.get("key"), it.get("url")) for it in items if (it.get("url") or "").strip()]
            fields: list[str] = []
            for key in ("python", "repo_path"):
                value = (doc.get(key) or "").strip()
                if value and not Path(value).exists():
                    fields.append(f"{key}={value!r}")
                    doc[key] = ""
            if not cleared and not fields:
                print(f"user {row.user_id}: already clean ({len(items)} rows, url '', no foreign paths)")
                continue
            if cleared:
                for it in items:
                    it["url"] = ""
                print(f"user {row.user_id}: clearing url on {len(cleared)} row(s): "
                      + ", ".join(f"{k or '?'}={u!r}" for k, u in cleared))
            if fields:
                print(f"user {row.user_id}: clearing foreign path(s): " + ", ".join(fields))
            if args.dry_run:
                continue
            before = row.revision
            _, rev = store.put_document(db, "ontology", doc,
                                        expected_revision=before, user_id=row.user_id)
            print(f"user {row.user_id}: written, revision {before} -> {rev}")
            changed_total += len(cleared) + len(fields)
        if args.dry_run:
            print("dry run — nothing written")
        else:
            print(f"{changed_total} field(s) normalised (same-origin urls, no foreign paths)")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
