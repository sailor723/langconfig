#!/usr/bin/env python
"""Point every agent's baked workspace path at the per-user tree (Slice 2 cleanup).

The problem, in one line: `config.system_prompt` and `agent_docs` embed an absolute
workspace path when an agent is created, and 55 of this install's 61 agents were
created **before** files moved into `outputs/users/<id>/`. Their prompt still says
`…/outputs/agents/agent_7`, a directory that no longer exists. A model that follows
the prompt literally looks in the wrong place, reports an empty workspace, or writes
where nothing else can find it.

New agents are already correct (the resolver renders the user root), so this is a
content rewrite of history, not a code fix.

What it rewrites, and what it refuses to touch:

* **Path prefix only.** `<install root>/…` becomes `<owner root>/…` where the target
  does not already name a `users/<id>` segment. Nothing else in the prompt changes, so
  hand-written instructions, rules and descriptions survive verbatim — a regenerate
  would silently drop every edit someone made in the editor.
* **Three places, because they are three copies**: `deep_agent_templates.config →
  system_prompt`, `deep_agent_templates.agent_docs`, and the materialized `AGENTS.md` /
  `CLAUDE.md` files inside the owner's workspace.
* **Dry run by default**, `--apply` to act, `--backup` writes a JSON copy of every row
  it is about to change so the rewrite is reversible; `--rollback <file>` restores it.

Usage::

    cd backend
    .venv/bin/python scripts/rebake_agent_workspaces.py                 # dry run
    .venv/bin/python scripts/rebake_agent_workspaces.py --apply         # rewrite
    .venv/bin/python scripts/rebake_agent_workspaces.py --rollback /tmp/rebake-backup.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from db.database import SessionLocal  # noqa: E402
from services import user_roots  # noqa: E402

DOC_FILES = ("AGENTS.md", "CLAUDE.md")


def _owner_id(db) -> int:
    from services.user_service import owner_user

    owner = owner_user(db)
    if owner is None:
        raise SystemExit("no active admin account exists — nothing to own the agents")
    return owner.id


def _rewrite(text: str, old_prefix: str, new_prefix: str) -> tuple[str, int]:
    """Replace the install-root prefix, except where it already names a user tree."""
    if not text:
        return text, 0
    pattern = re.compile(re.escape(old_prefix) + r"(?!users/)")
    new_text, count = pattern.subn(new_prefix, text)
    return new_text, count


def _plan(db, owner_id: int):
    from sqlalchemy import text

    install_root = str(user_roots.install_root()) + "/"
    owner_root = str(user_roots.root_for(owner_id)) + "/"

    rows = db.execute(text(
        "SELECT id, name, config, agent_docs FROM deep_agent_templates ORDER BY id"
    )).all()

    plan = []
    for agent_id, name, config, docs in rows:
        config = config or {}
        prompt = config.get("system_prompt") or ""
        new_config = dict(config)
        new_prompt, prompt_hits = _rewrite(prompt, install_root, owner_root)
        if prompt_hits:
            new_config["system_prompt"] = new_prompt

        new_docs, docs_hits = {}, 0
        for filename, content in (docs or {}).items():
            rewritten, hits = _rewrite(content, install_root, owner_root)
            new_docs[filename] = rewritten
            docs_hits += hits

        if prompt_hits or docs_hits:
            plan.append({
                "id": agent_id,
                "name": name,
                "prompt_hits": prompt_hits,
                "docs_hits": docs_hits,
                "config": new_config,
                "agent_docs": new_docs,
                "old_config": config,
                "old_docs": docs or {},
            })
    return plan, install_root, owner_root


def _disk_targets(owner_id: int):
    """Materialized doc files under the owner's tree that still carry the old path."""
    root = user_roots.root_for(owner_id)
    if not root.is_dir():
        return []
    return [p for p in root.rglob("*") if p.is_file() and p.name in DOC_FILES]


def main() -> int:
    parser = argparse.ArgumentParser(description="Re-anchor baked agent workspace paths.")
    parser.add_argument("--apply", action="store_true", help="rewrite the rows and files")
    parser.add_argument("--backup", default=None, help="write a rollback JSON here")
    parser.add_argument("--rollback", default=None, metavar="FILE", help="restore from a backup")
    parser.add_argument("--owner", type=int, default=None, help="user id owning the agents")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        if args.rollback:
            return rollback(db, args.rollback)

        owner_id = args.owner or _owner_id(db)
        plan, install_root, owner_root = _plan(db, owner_id)

        print()
        print("  agent workspace re-anchor")
        print("  " + "─" * 60)
        print(f"  install root : {install_root}")
        print(f"  owner root   : {owner_root} (user {owner_id})")
        print()

        if not plan:
            print("  every agent already points inside the user tree — nothing to do")
        else:
            print(f"  {'id':>4}  {'agent':<32} {'prompt':>7} {'docs':>5}")
            print(f"  {'-' * 4}  {'-' * 32} {'-' * 7} {'-' * 5}")
            for item in plan:
                print(f"  {item['id']:>4}  {item['name'][:32]:<32} {item['prompt_hits']:>7} {item['docs_hits']:>5}")
            print(f"  {'-' * 4}  {'-' * 32} {'-' * 7} {'-' * 5}")
            print(f"  {len(plan)} agent(s) to re-anchor")

        targets = _disk_targets(owner_id)
        stale_files = [p for p in targets if install_root in str(p.read_text(errors='ignore')) and
                       not re.search(re.escape(install_root) + r"users/", str(p.read_text(errors='ignore')))]
        print(f"  {len(targets)} materialized doc file(s) under the owner tree, "
              f"{len(stale_files)} of them still naming the old path")

        if not args.apply:
            print()
            print("  DRY RUN — nothing written. Re-run with --apply (and --backup FILE).")
            return 0

        backup_path = args.backup or str(BACKEND_DIR / "outputs" / "rebake-backup.json")
        payload = {
            "owner_id": owner_id,
            "install_root": install_root,
            "owner_root": owner_root,
            "rows": [
                {"id": i["id"], "config": i["old_config"], "agent_docs": i["old_docs"]}
                for i in plan
            ],
        }
        Path(backup_path).write_text(json.dumps(payload, indent=1), encoding="utf-8")
        print(f"\n  backup written: {backup_path} ({len(plan)} row(s))")

        from sqlalchemy import text as _text

        for item in plan:
            db.execute(_text(
                "UPDATE deep_agent_templates SET config = CAST(:c AS jsonb), "
                "agent_docs = CAST(:d AS jsonb) WHERE id = :i"
            ), {"c": json.dumps(item["config"]), "d": json.dumps(item["agent_docs"]), "i": item["id"]})
        db.commit()
        print(f"  rewrote {len(plan)} agent row(s)")

        rewritten_files = 0
        for path in targets:
            original = path.read_text(errors="ignore")
            updated, hits = _rewrite(original, install_root, owner_root)
            if hits:
                path.write_text(updated, encoding="utf-8")
                rewritten_files += 1
        print(f"  rewrote {rewritten_files} doc file(s) on disk")

        remaining = db.execute(_text(
            "SELECT count(*) FROM deep_agent_templates "
            "WHERE config->>'system_prompt' LIKE :p AND config->>'system_prompt' NOT LIKE :u"
        ), {"p": install_root + "%", "u": install_root + "users/%"}).scalar()
        print(f"  agents still naming the old root: {remaining}")
        return 0 if remaining == 0 else 1
    finally:
        db.close()


def rollback(db, path: str) -> int:
    from sqlalchemy import text

    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = payload.get("rows", [])
    for row in rows:
        db.execute(text(
            "UPDATE deep_agent_templates SET config = CAST(:c AS jsonb), "
            "agent_docs = CAST(:d AS jsonb) WHERE id = :i"
        ), {"c": json.dumps(row["config"]), "d": json.dumps(row["agent_docs"]), "i": row["id"]})
    db.commit()
    print(f"  restored {len(rows)} row(s) from {path}")
    print("  note: files on disk are not reverted — re-run --apply after a rollback if needed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
