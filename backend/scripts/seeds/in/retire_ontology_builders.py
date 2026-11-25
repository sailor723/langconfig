#!/usr/bin/env python3
"""Retire the per-key ontology BUILDER agents, pointing them at the one builder template.

Why: seven builder rows were created before the naming decision, each a copy of the same prompt with a
key and a database baked in. Measured 2026-11-12 — 348/349 carry a 9-tool set, 355/376/378/379 carry
11 (the difference is `ontology_open` + `read_any_file`, i.e. the REBUILD path), and every prompt
names its own ontology in four places. Six copies of one prompt is six places a fix has to land.

What this does, per row: `is_public = false` (it stops appearing as a choice in the Agent list) and
`config.superseded_by` + `config.retired = {at, reason, superseded_by}` (an audit can answer "where
did this agent go?" without reading git). Nothing is deleted: the row, its prompt and its key stay,
so `--restore` puts it back exactly as it was, and a key it alone knew about is still readable.

    cd backend && .venv/bin/python scripts/seeds/in/retire_ontology_builders.py            # dry run
    cd backend && .venv/bin/python scripts/seeds/in/retire_ontology_builders.py --apply
    cd backend && .venv/bin/python scripts/seeds/in/retire_ontology_builders.py --restore --apply

The pointer must NAME an agent that exists — or the retirement points at nothing, which is the state
this script is meant to end. It warns (and, with `--require-target`, refuses) when it does not.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import pathlib
import sys

BACKEND = pathlib.Path(__file__).resolve().parents[3]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

REASON = ("per-key builder copied one prompt with its ontology and database baked in; the single "
          "`Ontology Builder` template takes the key per conversation instead")


def _ok(m: str) -> None:
    print(f"  OK   {m}")


def _todo(m: str) -> None:
    print(f"  PLAN {m}")


def _warn(m: str) -> None:
    print(f"  WARN {m}")


def _session():
    from db.database import SessionLocal  # noqa: PLC0415

    return SessionLocal()


def _rows(db) -> list[dict]:
    from sqlalchemy import text  # noqa: PLC0415

    sql = text("""
        select id, name, is_public, config from deep_agent_templates
         where name like 'Ontology Builder (%'
         order by id
    """)
    out = []
    for rid, name, public, config in db.execute(sql).fetchall():
        cfg = config or {}
        sp = cfg.get("skill_params") or {}
        key = next((v.get("ontology_key") for v in sp.values() if isinstance(v, dict)), None)
        out.append({"id": rid, "name": name, "is_public": bool(public), "config": cfg,
                    "key": key, "tools": len(cfg.get("native_tools") or []), "action": "retire"})
    return out


def _target(db, name: str) -> dict | None:
    from sqlalchemy import text  # noqa: PLC0415

    row = db.execute(text("select id, name, is_public from deep_agent_templates where name = :n"),
                     {"n": name}).fetchone()
    return {"id": row[0], "name": row[1], "is_public": bool(row[2])} if row else None


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--superseded-by", default="Ontology Builder",
                    help="the agent these rows hand over to (default: 'Ontology Builder')")
    ap.add_argument("--require-target", action="store_true",
                    help="refuse to retire when the target agent does not exist yet")
    ap.add_argument("--restore", action="store_true",
                    help="undo: is_public=true and drop the retirement block")
    ap.add_argument("--apply", action="store_true", help="write (default: dry run)")
    args = ap.parse_args()

    db = _session()
    try:
        rows = _rows(db)
        if not rows:
            print("no per-key builder rows found — nothing to do")
            return 0
        print(f"per-key builder rows: {len(rows)}   target: {args.superseded_by!r}   "
              f"mode={'RESTORE' if args.restore else 'RETIRE'}  "
              f"{'APPLY' if args.apply else 'DRY RUN'}")
        target = _target(db, args.superseded_by)
        if target:
            _ok(f"target agent exists: id={target['id']} name={target['name']!r} "
                f"public={target['is_public']}")
            if args.restore and not target["is_public"]:
                _warn("the target itself is not public — restoring the copies would leave no builder "
                      "visible in the Agent list")
        else:
            _warn(f"no agent named {args.superseded_by!r} yet — the pointer would name nothing")
            if args.require_target and not args.restore:
                print("  refusing (--require-target): create the single template first")
                return 1

        changed = 0
        for r in rows:
            cfg = dict(r["config"] or {})
            if args.restore:
                want_public, has_block = True, "retired" in cfg
                if r["is_public"] and not has_block:
                    print(f"  = {r['id']:>4} {r['name']:<42} already restored")
                    continue
            else:
                want_public, has_block = False, "retired" in cfg
                if not r["is_public"] and has_block and \
                        cfg.get("superseded_by") == args.superseded_by:
                    print(f"  = {r['id']:>4} {r['name']:<42} already retired → "
                          f"{args.superseded_by}")
                    continue

            print(f"\n  {'restore' if args.restore else 'retire'} {r['id']} {r['name']!r} "
                  f"(key={r['key'] or '-'}, tools={r['tools']})")
            if args.restore:
                cfg.pop("retired", None)
                cfg.pop("superseded_by", None)
                _ok("would set is_public=true and drop config.retired/superseded_by")
            else:
                cfg["superseded_by"] = args.superseded_by
                cfg["retired"] = {
                    "at": _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "reason": REASON,
                    "superseded_by": args.superseded_by,
                }
                _todo(f"would set is_public=false, config.superseded_by={args.superseded_by!r}")
            if args.apply:
                from sqlalchemy import text  # noqa: PLC0415

                db.execute(text("update deep_agent_templates set is_public = :p, config = "
                                "cast(:c as jsonb) where id = :i"),
                           {"p": want_public, "c": json.dumps(cfg, ensure_ascii=False), "i": r["id"]})
                changed += 1
        if args.apply and changed:
            db.commit()
            _ok(f"{changed} row(s) written")
        elif args.apply:
            print("\n  (nothing changed)")
        else:
            print("\n  dry run — re-run with --apply to write")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
