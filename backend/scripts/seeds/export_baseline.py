"""Regenerate — or verify — every seed asset that has to be exported out of the DB.

Agents and tools live in Postgres, not in git. The `.sql` files under this
directory are photographs of them, so they only stay current if someone runs the
exporters after creating or editing an agent or a tool. Nothing warned you when
they fell behind, and a stale photograph fails silently: the teammate's
`seed_all.py` simply adds nothing new.

    cd backend
    .venv/bin/python scripts/seeds/export_baseline.py           # photograph now
    .venv/bin/python scripts/seeds/export_baseline.py --check    # am I due? (exit 1 if so)

`--check` regenerates into a temp file and compares BYTES against the committed
one, which catches an edit to an existing agent (counts alone cannot) because
both exporters are deterministic — no timestamps, rows ordered by name/tool_id.
It also reports the three legs that are NOT exported this way, so the table is
the whole picture rather than the two files that happen to exist.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
SEEDS = BACKEND / "scripts/seeds"
sys.path.insert(0, str(BACKEND))

# leg -> (exporter script, committed artefact, table, key column)
EXPORTED = {
    "agents": ("export_agents_merge.py", "deep_agents_merge.sql", "deep_agent_templates", "name"),
    "tools": ("export_tools_merge.py", "custom_tools_merge.sql", "custom_tools", "tool_id"),
}

PASS, STALE = "FRESH", "STALE"


def db_counts() -> dict[str, int]:
    from sqlalchemy import text
    from db.database import SessionLocal

    out: dict[str, int] = {}
    with SessionLocal() as db:
        for leg, (_script, _artefact, table, _key) in EXPORTED.items():
            out[leg] = db.execute(text(f"SELECT count(*) FROM {table}")).scalar()
    return out


def snapshot_rows(path: Path) -> int:
    """Rows a committed snapshot offers (one guarded INSERT per row)."""
    return path.read_bytes().count(b"WHERE NOT EXISTS") if path.exists() else 0


def regenerate(script: str, target: Path) -> bool:
    """Run an exporter into `target`; True when it wrote something."""
    p = subprocess.run(
        [sys.executable, str(SEEDS / script), "--out", str(target)],
        cwd=str(BACKEND), capture_output=True, text=True,
    )
    if p.returncode != 0:
        detail = (p.stderr or p.stdout or "").strip().splitlines()
        print(f"    !! {script} failed: {detail[-1] if detail else 'no output'}")
        return False
    return target.exists()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true",
                    help="report staleness instead of rewriting (exit 1 when stale)")
    args = ap.parse_args()

    live = db_counts()
    stale: list[str] = []
    errors: list[str] = []

    print(f"{'leg':8} {'rows in DB':>10} {'in snapshot':>12}  status")
    for leg, (script, artefact, table, key) in EXPORTED.items():
        committed = SEEDS / artefact
        if not committed.exists():
            print(f"{leg:8} {live[leg]:>10} {'—':>12}  {STALE}: {artefact} missing")
            stale.append(leg)
            continue

        rows = snapshot_rows(committed)

        # A count difference settles it — no need to export to know.
        if live[leg] != rows:
            if args.check:
                print(f"{leg:8} {live[leg]:>10} {rows:>12}  "
                      f"{STALE}: {live[leg] - rows:+d} row(s) vs the snapshot")
                stale.append(leg)
                continue
            # regenerate below

        with tempfile.TemporaryDirectory() as tmp:
            fresh = Path(tmp) / artefact
            if not regenerate(script, fresh):
                # The exporter refuses to write an empty file, so a DB with no
                # rows while the snapshot has some is staleness, not a failure.
                if live[leg] == 0 and rows > 0:
                    print(f"{leg:8} {live[leg]:>10} {rows:>12}  "
                          f"{STALE}: nothing in the database to export")
                    stale.append(leg)
                else:
                    errors.append(leg)
                continue

            if args.check:
                same = fresh.read_bytes() == committed.read_bytes()
                # Counts matching but bytes differing means an existing row was
                # EDITED — the case a count comparison cannot see.
                print(f"{leg:8} {live[leg]:>10} {rows:>12}  "
                      f"{PASS if same else STALE + ': an existing row changed'}")
                if not same:
                    stale.append(leg)
            else:
                committed.write_bytes(fresh.read_bytes())
                print(f"{leg:8} {live[leg]:>10} {rows:>12}  written")

    # The legs with no exporter. Reported so the table reflects the whole
    # baseline, not just the two files that happen to be regenerable.
    print(f"\n{'skills':8} {'—':>10} {'—':>15}  synced from disk by seed_all step 9 (no export)")
    print(f"{'models':8} {'—':>10} {'—':>15}  hand-maintained CSV + upsert_model preset (no export)")
    print(f"{'settings':8} {'—':>10} {'—':>15}  code defaults only; UI edits do NOT travel")

    if errors:
        print(f"\nERROR: {', '.join(errors)} — the exporter itself failed; "
              f"nothing was compared")
        return 2
    if args.check and stale:
        print(f"\nSTALE: {', '.join(stale)} — regenerate, then commit "
              f"backend/scripts/seeds/*.sql")
        return 1
    if args.check:
        print("\nAll exported legs match the database.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
