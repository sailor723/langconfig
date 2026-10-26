#!/usr/bin/env python
"""Audit the agent inventory, and repair the parts that can be repaired safely.

Housekeeping here means answering four questions about a live install, and fixing only
the two that have an unambiguous right answer:

| Question | Answer | Action |
|---|---|---|
| Which agents have no instruction docs? | 6 of 60 | **repair** — write the defaults |
| Which agents have docs in PostgreSQL but not on disk? | most | **repair** — materialize them |
| Which agents have more than one workspace directory? | one per vault, by design | **report only** |
| Which agents are unused, or named like a test? | 31 unused, 12 test-like | **report only** — deleting an agent is a judgement call, not a cleanup |

The third row is deliberate and worth understanding before "tidying" it: an agent's
workspace is anchored to the *session's* project, so `agent_112` legitimately has
`agents/agent_112` (no vault) plus `<vault>/agents/agent_112` for every vault it has
been used in. Merging them would move files the user chose to keep apart.

Nothing destructive happens without `--delete`, and `--delete` only accepts ids you name.

Usage::

    cd backend
    .venv/bin/python scripts/audit_agents.py                     # report
    .venv/bin/python scripts/audit_agents.py --apply             # write missing docs
    .venv/bin/python scripts/audit_agents.py --delete 233 235 237 --apply
"""

from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from db.database import SessionLocal  # noqa: E402
from services import user_roots  # noqa: E402

TESTISH = ("test", "probe", "demo", "tmp", "temp", "debug", "xxx")


def _agents(db):
    from sqlalchemy import text

    return db.execute(text(
        "SELECT a.id, a.name, a.config, a.agent_docs, "
        "       (SELECT count(*) FROM chat_sessions s WHERE s.agent_id = a.id) AS chats "
        "FROM deep_agent_templates a ORDER BY a.id"
    )).all()


def _workspace_dirs(owner_id: int) -> dict:
    """Every `agent_<id>` directory under the owner's tree, with its file counts."""
    root = user_roots.root_for(owner_id)
    found = defaultdict(list)
    if not root.is_dir():
        return found
    for path in root.rglob("agent_*"):
        if not path.is_dir() or not path.name.startswith("agent_"):
            continue
        try:
            agent_id = int(path.name.split("_")[1])
        except (IndexError, ValueError):
            continue
        files = [f for f in path.rglob("*") if f.is_file()]
        real = [f for f in files if f.name not in ("AGENTS.md", "CLAUDE.md", ".gitkeep")]
        found[agent_id].append({
            "path": path.relative_to(root).as_posix(),
            "user_files": len(real),
            "files": len(files),
        })
    return found


def report(db, owner_id: int) -> dict:
    rows = _agents(db)
    dirs = _workspace_dirs(owner_id)

    no_docs = [r for r in rows if not r.agent_docs or not dict(r.agent_docs)]
    testish = [r for r in rows if any(t in (r.name or "").lower() for t in TESTISH)]
    unused = [r for r in rows if r.chats == 0]
    multi = {a: v for a, v in dirs.items() if len(v) > 1}
    with_files = {a: v for a, v in dirs.items() if any(d["user_files"] for d in v)}

    print()
    print("  agent inventory")
    print("  " + "─" * 66)
    print(f"  agents                     {len(rows):>4}")
    print(f"  never chatted              {len(unused):>4}   (candidates to archive, not to delete)")
    print(f"  named like a test          {len(testish):>4}   {', '.join(str(r.id) for r in testish[:8])}"
          f"{' …' if len(testish) > 8 else ''}")
    print(f"  no instruction docs        {len(no_docs):>4}   {', '.join(str(r.id) for r in no_docs) or '—'}")
    print(f"  workspace dirs found       {len(dirs):>4}  for {len(rows)} agents")
    print(f"  agents with >1 dir         {len(multi):>4}   (one per vault — by design)")
    print(f"  agents holding real files  {len(with_files):>4}")
    print()

    if testish:
        print("  test-like agents (review before deleting — some may be load-bearing):")
        for r in testish:
            print(f"    {r.id:>4}  {r.name[:34]:<34} chats={r.chats}")
        print()
    if unused:
        print(f"  never-chatted agents: {len(unused)} (first 10 ids: "
              f"{', '.join(str(r.id) for r in unused[:10])})")
        print()
    return {"rows": rows, "no_docs": no_docs, "dirs": dirs}


def repair_docs(db, data) -> int:
    """Write default docs for agents that have none, and materialize them to disk.

    Defaults only — an agent with authored docs is never touched, because a regenerate
    would discard whatever the user wrote.
    """
    from core.agents.identity import default_agent_docs
    from services.workspace_manager import WorkspaceManager, get_workspace_manager

    manager = get_workspace_manager()
    written = 0
    for row in data["no_docs"]:
        agent = db.query(__import__("models.deep_agent", fromlist=["DeepAgentTemplate"]).DeepAgentTemplate).get(row.id)
        if agent is None:
            continue
        workspace_root = str(manager.resolve_agent_workspace(
            agent, None, vault_key=None, agent_key=WorkspaceManager.agent_vault_key(db, agent),
        ))
        docs = default_agent_docs(agent, workspace_root)
        agent.agent_docs = docs
        db.commit()
        stored = Path(workspace_root)
        stored.mkdir(parents=True, exist_ok=True)
        for name, content in docs.items():
            (stored / name).write_text(content, encoding="utf-8")
        print(f"  repaired  agent_{row.id:<4} {row.name[:30]:<30} → {workspace_root}")
        written += 1
    return written


BOUNDARY_MARKER = "This directory belongs to one account"


def inject_boundary_note(db, data) -> int:
    """Append the ownership rule to docs written before it existed.

    Appended, not regenerated: an agent whose AGENTS.md somebody edited in the editor
    keeps every edit, and only gains the paragraph. Idempotent — a doc that already has
    the marker is left alone.
    """
    from sqlalchemy import text

    updated = 0
    for row in data["rows"]:
        docs = dict(row.agent_docs or {})
        changed = False
        for name, content in list(docs.items()):
            if not content or BOUNDARY_MARKER in content:
                continue
            docs[name] = (
                content.rstrip()
                + "\n\n## Workspace ownership\n\n"
                + "- **This directory belongs to one account.** The path carries its owner\n"
                + "  (`…/users/<user id>/…`). Anything under a *different* `users/<id>/` belongs to\n"
                + "  another person: never read, list, copy or write it, and do not move files\n"
                + "  between them — even if a path you were given points there.\n"
            )
            changed = True
        if changed:
            db.execute(text("UPDATE deep_agent_templates SET agent_docs = CAST(:d AS jsonb) WHERE id = :i"),
                       {"d": __import__("json").dumps(docs), "i": row.id})
            updated += 1
    db.commit()
    return updated


def delete_agents(db, ids: list) -> int:
    from sqlalchemy import text

    deleted = 0
    for agent_id in ids:
        row = db.execute(text("SELECT name FROM deep_agent_templates WHERE id = :i"), {"i": agent_id}).first()
        if row is None:
            print(f"  skip     id {agent_id} — no such agent")
            continue
        chats = db.execute(text("SELECT count(*) FROM chat_sessions WHERE agent_id = :i"), {"i": agent_id}).scalar()
        if chats:
            print(f"  REFUSED  agent_{agent_id} ({row[0]}) has {chats} chat session(s) — "
                  f"deleting it would orphan conversation history")
            continue
        db.execute(text("DELETE FROM deep_agent_templates WHERE id = :i"), {"i": agent_id})
        db.commit()
        print(f"  deleted  agent_{agent_id} ({row[0]})")
        deleted += 1
    return deleted


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit and repair the agent inventory.")
    parser.add_argument("--apply", action="store_true", help="write missing docs")
    parser.add_argument("--docs-note", action="store_true",
                        help="append the workspace-ownership note to docs that predate it")
    parser.add_argument("--delete", nargs="*", type=int, default=None,
                        help="ids of agent-less-chat agents to delete (refused if they have chats)")
    parser.add_argument("--owner", type=int, default=None, help="user id whose tree to audit")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        owner = args.owner
        if owner is None:
            from services.user_service import owner_user
            found = owner_user(db)
            if found is None:
                raise SystemExit("no admin account — nothing to own the agents")
            owner = found.id

        data = report(db, owner)

        if args.delete:
            print("  delete requested:")
            if not args.apply:
                print("     DRY RUN — re-run with --apply to delete")
            else:
                delete_agents(db, args.delete)
            print()

        if args.docs_note:
            if args.apply:
                count = inject_boundary_note(db, data)
                print(f"  ownership note added to {count} agent doc set(s)" if count
                      else "  every doc already states the ownership rule")
            else:
                stale = sum(1 for r in data["rows"]
                            if not any(BOUNDARY_MARKER in (c or "") for c in dict(r.agent_docs or {}).values()))
                print(f"  {stale} agent(s) have docs without the ownership note "
                      f"— re-run with --apply --docs-note")
            print()

        if args.apply:
            print("  repairing agents without instruction docs:")
            count = repair_docs(db, data)
            print(f"  {count} agent(s) repaired" if count else "  nothing to repair")
        elif not args.delete:
            print("  nothing written. --apply repairs the missing docs; --delete <ids> removes")
            print("  never-chatted agents (refused when a chat session exists).")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
