"""Regenerate — or verify — every seed asset that has to be exported out of the DB.

Agents and tools live in Postgres, not in git. The `.sql` files under this
directory are photographs of them, so they only stay current if someone runs the
exporters after creating or editing an agent or a tool. Nothing warned you when
they fell behind, and a stale photograph fails silently: the teammate's
`seed_all.py` simply adds nothing new.

    cd backend
    .venv/bin/python scripts/seeds/out/export_baseline.py           # photograph now
    .venv/bin/python scripts/seeds/out/export_baseline.py --check    # am I due? (exit 1 if so)

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

for _p in Path(__file__).resolve().parents:
    if (_p / "_seedpaths.py").exists():
        sys.path.insert(0, str(_p))
        break
from _seedpaths import (  # noqa: E402
    AGENTS_DUMP, AGENTS_MERGE, BACKEND, IN_DIR, OUT_DIR, SEEDS,
    SETTINGS_SEED, TOOLS_DUMP, TOOLS_MERGE,
)

import _secretscan  # noqa: E402  (sibling module in out/)

# leg -> (exporter script, committed artefact, table, key column)
# leg -> (exporter, committed artefact, count SQL)
# The count SQL is what the DB side is measured with, so a leg can count a subset:
# the settings snapshot deliberately covers only the TEAM namespaces, not
# general/onboarding, and counting the whole table would report false drift.
EXPORTED = {
    "agents": ("export_agents_merge.py", AGENTS_MERGE,
               "SELECT count(*) FROM deep_agent_templates"),
    "tools": ("export_tools_merge.py", TOOLS_MERGE,
              "SELECT count(*) FROM custom_tools"),
    "settings": ("export_settings.py", SETTINGS_SEED,
                 "SELECT count(*) FROM settings_documents WHERE ns IN "
                 "('agents','models','rag','runtime','storage','workspace')"),
}

PASS, STALE = "FRESH", "STALE"


def db_counts() -> dict[str, int]:
    from sqlalchemy import text
    from db.database import SessionLocal

    out: dict[str, int] = {}
    with SessionLocal() as db:
        for leg, (_script, _artefact, count_sql) in EXPORTED.items():
            out[leg] = db.execute(text(count_sql)).scalar()
    return out


def snapshot_rows(path: Path) -> int:
    """Rows a committed snapshot offers.

    SQL snapshots carry one guarded INSERT per row; the settings snapshot is JSON
    with one top-level key per namespace.
    """
    if not path.exists():
        return 0
    raw = path.read_bytes()
    if path.suffix == ".json":
        import json as _json
        try:
            return len([k for k in _json.loads(raw) if not k.startswith("__")])
        except Exception:
            return 0
    if b"FROM stdin" in raw:
        # pg_dump data-only format: tab-separated rows between "COPY ... FROM
        # stdin" and the closing "\." marker.
        rows, in_copy = 0, False
        for line in raw.decode("utf-8", "replace").splitlines():
            if "FROM stdin" in line:
                in_copy = True
                continue
            if in_copy:
                if line.strip() == "\\.":
                    in_copy = False
                elif line[:1].isdigit():
                    rows += 1
        return rows
    return raw.count(b"WHERE NOT EXISTS")


def regenerate(script: str, target: Path) -> bool:
    """Run an exporter into `target`; True when it wrote something."""
    p = subprocess.run(
        [sys.executable, str(OUT_DIR / script), "--out", str(target)],
        cwd=str(BACKEND), capture_output=True, text=True,
    )
    if p.returncode != 0:
        detail = (p.stderr or p.stdout or "").strip().splitlines()
        print(f"    !! {script} failed: {detail[-1] if detail else 'no output'}")
        return False
    return target.exists()


def skills_status() -> dict:
    """Skills do not export — the SKILL.md files ARE the artefact.

    Two ways that still fails silently, so both are reported: a skill that lives
    only in the database (no file, so seed_all.py has nothing to sync), and a file
    that exists but was never committed (so a teammate's clone has neither).
    """
    import subprocess as _sp
    from sqlalchemy import text as _text
    from db.database import SessionLocal as _SessionLocal
    from core.skills.sync import (
        scan_builtin_skills, fs_to_db_dict, PERSONAL_SKILLS_ROOT,
    )

    with _SessionLocal() as db:
        db_ids = {r[0] for r in db.execute(_text("SELECT skill_id FROM skills"))}

    root = Path(PERSONAL_SKILLS_ROOT).parent
    disk_ids: set[str] = set()
    for md in (list(scan_builtin_skills())
               + list(PERSONAL_SKILLS_ROOT.rglob("SKILL.md"))
               + sorted(root.glob("*/SKILL.md"))):
        try:
            disk_ids.add(fs_to_db_dict(md)["skill_id"])
        except Exception:
            continue

    uncommitted = []
    try:
        out = _sp.run(["git", "-C", str(BACKEND.parent), "status", "--porcelain", "--", "backend/skills"],
                      capture_output=True, text=True, timeout=20).stdout
        uncommitted = [l[3:].strip() for l in out.splitlines() if l[3:].strip().endswith("SKILL.md")]
    except Exception:
        pass

    return {"db": len(db_ids), "disk": len(disk_ids),
            "db_only": sorted(db_ids - disk_ids),
            "disk_only": sorted(disk_ids - db_ids),
            "uncommitted": uncommitted}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true",
                    help="report staleness instead of rewriting (exit 1 when stale)")
    args = ap.parse_args()

    live = db_counts()
    stale: list[str] = []
    errors: list[str] = []

    print(f"{'leg':8} {'rows in DB':>10} {'in snapshot':>12}  status")
    for leg, (script, artefact, _count_sql) in EXPORTED.items():
        committed = artefact
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
            fresh = Path(tmp) / artefact.name
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

    # Skills: no exporter, because the SKILL.md files are the artefact — but
    # checked anyway, since a database-only or uncommitted skill reaches nobody.
    sk = skills_status()
    problems = []
    if sk["db_only"]:
        problems.append(f"{len(sk['db_only'])} in the DB with no file: {', '.join(sk['db_only'][:3])}")
    if sk.get("disk_only"):
        # A committed SKILL.md with no DB row still reaches a teammate (step 9
        # syncs FS -> DB on their install), but the database you are looking at
        # does not offer it. Reported, not fatal.
        problems.append(f"{len(sk['disk_only'])} on disk with no DB row: {', '.join(sk['disk_only'][:3])}")
    if sk["uncommitted"]:
        problems.append(f"{len(sk['uncommitted'])} file(s) not committed")
    if problems:
        print(f"{'skills':8} {sk['db']:>10} {sk['disk']:>15}  {STALE}: {'; '.join(problems)}")
        stale.append("skills")
    else:
        print(f"{'skills':8} {sk['db']:>10} {sk['disk']:>15}  "
              f"{PASS} — files are the artefact, all committed")

    # The remaining legs have no exporter at all.
    print(f"{'models':8} {'—':>10} {'—':>15}  hand-maintained CSV + upsert_model preset (no export)")

    # The explicit-id dumps are legacy: seed_all.py restores them (for the ids)
    # and then applies the merge, so they are not a baseline on their own. They
    # still drift, and until now nothing said so — this is the third leg the
    # module docstring promises to report.
    for label, dump, merge in (("agents", AGENTS_DUMP, AGENTS_MERGE),
                               ("tools", TOOLS_DUMP, TOOLS_MERGE)):
        if not dump.exists():
            continue
        print(f"{label + '*':8} {snapshot_rows(dump):>10} {snapshot_rows(merge):>12}  "
              f"legacy dump (not exported); the merge file is the baseline")

    # ── credential sweep over EVERY committed artefact ──────────────────────
    # The exporters gate themselves (settings scrubs from the schema; agents and
    # tools refuse on a credential-shaped string), but this is the one place that
    # sees the whole published set — including the hand-maintained CSV and the
    # legacy dumps — so a leak cannot reach a commit through a path nobody wired.
    leaky: list[str] = []
    for artefact in sorted(IN_DIR.glob("*")):
        if not artefact.is_file():
            continue
        try:
            text = artefact.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        findings = _secretscan.scan(text)
        if findings:
            leaky.append(artefact.name)
            _secretscan.report(findings, source=str(artefact))
    if leaky:
        print(f"\n  !! {len(leaky)} artefact(s) look like they carry a credential: "
              f"{', '.join(leaky)}")
        print("     Fix the source (Settings → API Keys is never exported), or run the "
              "exporter with --redact.")
        stale.append("credentials")
    elif not args.check:
        print(f"{'secrets':8} {'ok':>10} {'—':>15}  no credential-shaped string in any artefact")

    if errors:
        print(f"\nERROR: {', '.join(errors)} — the exporter itself failed; "
              f"nothing was compared")
        return 2
    if args.check and stale:
        print(f"\nSTALE: {', '.join(stale)} — regenerate, then commit the files "
              f"under backend/scripts/seeds/")
        return 1
    if args.check:
        print("\nAll exported legs match the database.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
