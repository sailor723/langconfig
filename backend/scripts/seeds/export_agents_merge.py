"""Export the live agents as an ADDITIVE, machine-agnostic seed.

Writes ``scripts/seeds/deep_agents_merge.sql``: one INSERT per agent, with

  * **no ``id``** — the target database assigns it from the sequence, so a
    teammate's own agents keep their ids and the insert cannot collide;
  * **``WHERE NOT EXISTS (... name = ...)``** — an agent whose name is already
    present is left completely untouched, including one the teammate wrote
    themselves under the same name;
  * ``base_template_id`` kept as-is: it is a varchar holding a NAME reference
    (DEEP_ARCHITECT, DEEP_DEBUGGER, …), not a foreign key to ``id``, so
    re-numbering on the target cannot break it;
  * ``workspace_path`` nulled — it is a machine path. seed_all's identity
    backfill (step 8.5) re-resolves each agent's workspace on the target once
    the row is in.

Why not the old path: ``deep_agents_dump.sql`` carries explicit ids and is
restored after a ``TRUNCATE ... CASCADE`` whenever the table has fewer rows than
the dump — which deletes a teammate's own agents AND, through the FK, their chat
sessions. This file is meant to be applied on any database, first install or
already in use, without touching a single existing row.

Usage:
    cd backend
    .venv/bin/python scripts/seeds/export_agents_merge.py            # write the file
    .venv/bin/python scripts/seeds/export_agents_merge.py --stdout   # preview
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from sqlalchemy import text                     # noqa: E402
from db.database import SessionLocal            # noqa: E402

SEEDS_DIR = Path(__file__).resolve().parent
OUT_FILE = SEEDS_DIR / "deep_agents_merge.sql"

# Columns copied. `id` is absent on purpose — see the module docstring.
COLUMNS = [
    "name", "description", "category", "base_template_id", "workspace_path",
    "agent_docs", "config", "middleware_config", "subagents_config",
    "backend_config", "guardrails_config", "export_settings", "usage_count",
    "last_used_at", "version", "is_public", "is_community", "created_at",
    "updated_at", "lock_version",
]

JSON_COLUMNS = {
    "agent_docs", "config", "middleware_config", "subagents_config",
    "backend_config", "guardrails_config", "export_settings",
}


def scrub_prefixes() -> list[tuple[str, str]]:
    """Absolute prefixes to replace with the WORKSPACE_BASE placeholder.

    The agent rows embed their workspace path in ``config.system_prompt`` and in
    ``agent_docs``, so exporting them verbatim ships the author's home directory
    inside 56 agents and hard-codes a path that does not exist on any other
    machine. core/agents/identity.py already knows how to rewrite
    ``WORKSPACE_BASE/...`` at run time (and seed_all's identity backfill re-bakes
    it per install), so that is the form the seed stores.

    Longest first, so the workspace root is replaced before the repo root it
    sits under.
    """
    from sqlalchemy import text as _text
    from db.database import SessionLocal as _SessionLocal

    base = ""
    with _SessionLocal() as db:
        doc = db.execute(_text(
            "SELECT document FROM settings_documents WHERE ns = 'workspace'"
        )).scalar()
        if isinstance(doc, dict):
            base = str(doc.get("workspace_path") or "")
    prefixes = []
    if base:
        prefixes.append(base)                     # …/backend/outputs
        parts = Path(base).parts
        if "backend" in parts:
            root = str(Path(base).parents[len(parts) - 1 - parts.index("backend")])
            prefixes.append(root)                 # the repo root
    # Any remaining home-directory prefix, so a stray absolute path is still
    # neutralised rather than shipped.
    home = str(Path.home())
    if home:
        prefixes.append(home)
    seen, out = set(), []
    for pfx in sorted(prefixes, key=len, reverse=True):
        if pfx and pfx not in seen:
            seen.add(pfx)
            out.append((pfx, "WORKSPACE_BASE"))
    return out


def scrub(value, prefixes: list[tuple[str, str]]):
    """Replace machine prefixes in every string, including inside JSON."""
    if isinstance(value, str):
        for pfx, repl in prefixes:
            if pfx in value:
                value = value.replace(pfx, repl)
        return value
    if isinstance(value, dict):
        return {k: scrub(v, prefixes) for k, v in value.items()}
    if isinstance(value, list):
        return [scrub(v, prefixes) for v in value]
    return value


def lit(value) -> str:
    """A SQL literal for one value, escaped for a single-quoted string."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, (dict, list)):
        return "'" + json.dumps(value, ensure_ascii=False).replace("'", "''") + "'"
    return "'" + str(value).replace("'", "''") + "'"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--stdout", action="store_true", help="print instead of writing the file")
    ap.add_argument("--out", default=str(OUT_FILE), help="output path")
    args = ap.parse_args(argv)

    prefixes = scrub_prefixes()
    db = SessionLocal()
    try:
        rows = [scrub(dict(r._mapping), prefixes) for r in db.execute(text(
            f"SELECT {', '.join(COLUMNS)} FROM deep_agent_templates ORDER BY name"
        ))]
    finally:
        db.close()

    if not rows:
        print("no agents in the database — nothing written")
        return 1

    lines = [
        "-- LangConfig additive agent seed — generated by export_agents_merge.py",
        f"-- {len(rows)} agent(s) from the live database.",
        "--",
        "-- Safe to run on a database that already has agents: ids are assigned by",
        "-- the target sequence and every name already present is skipped, so no",
        "-- existing row (yours or a teammate's) is modified or removed.",
        "--",
        "-- Machine paths are stored as WORKSPACE_BASE/... and re-resolved per install",
        "-- by seed_all step 8.5 (backfill_agent_identity.py).",
        "--",
        "--   psql \"$DATABASE_URL\" -v ON_ERROR_STOP=1 -f deep_agents_merge.sql",
        "",
        "BEGIN;",
        "",
    ]

    for row in rows:
        cols = ", ".join(COLUMNS)
        vals = []
        for col in COLUMNS:
            value = row.get(col)
            if col == "workspace_path":
                value = None            # machine path; resolved by step 8.5 on the target
            vals.append(lit(value))
        name = lit(row["name"])
        lines.append(
            f"INSERT INTO deep_agent_templates ({cols})\n"
            f"SELECT {', '.join(vals)}\n"
            f"WHERE NOT EXISTS (SELECT 1 FROM deep_agent_templates WHERE name = {name});"
        )
        lines.append("")

    lines += [
        "COMMIT;",
        "",
        f"-- done: {len(rows)} agent(s) offered; existing names were skipped.",
        "",
    ]

    sql = "\n".join(lines)
    if args.stdout:
        print(sql)
        return 0

    Path(args.out).write_text(sql, encoding="utf-8")
    size_kb = Path(args.out).stat().st_size / 1024
    print(f"wrote {args.out} — {len(rows)} agent(s), {size_kb:.0f} KB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
