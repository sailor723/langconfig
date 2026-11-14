#!/usr/bin/env python3
"""Fork every ontology builder into v2 and v3: a version line, not a rewrite of history.

`v1` is the ontology that is installed and serving. The next two generations are built beside it, from
the SAME datasource and starting from a COPY of v1's declarations — so a reviewer can diff what changed
(`delta.json` has a baseline to compare against), and the installed v1 keeps serving while they work.

What a fork is, concretely:

  1. **a new key** — `meeting_v1` → `meeting_v2` / `meeting_v3`. A key that already ends in `_v<N>` is
     continued when those numbers are free; otherwise (`new_coldchain_v6`, whose stem already owns v3–v7)
     the fork is named `<key>_v2` / `<key>_v3` so no two builders can mean different things by one name.
  2. **a copy of the installed profile** — every declaration file, with the ontology namespace REWRITTEN
     to the new key's IRI. A copy that kept v1's namespace would make two ontologies claim the same
     individuals, which is the one thing an ABox must never do.
  3. **its own agent row, gates declaration, Settings item and .env variable** — through
     `add_ontology_builder.py`, so the fork inherits every idempotent step instead of re-implementing them.
  4. **NOT installed** — `gates.json` gets `pending_install`, so the app does not offer a page for an
     ontology nobody has applied, and `scripts/ontology_gates.py` reports it NOT RUN by name.

Usage:
    cd backend && .venv/bin/python scripts/seeds/in/fork_ontology_builders.py            # dry run
    cd backend && .venv/bin/python scripts/seeds/in/fork_ontology_builders.py --apply

Exit: 0 ok, 1 a fork failed, 2 bad arguments / no builders found.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import shutil
import subprocess
import sys

BACKEND = pathlib.Path(__file__).resolve().parents[3]  # scripts/seeds/in → backend
REPO = BACKEND.parent
PROFILES = BACKEND / "features" / "ontology" / "profiles"
ADD = BACKEND / "scripts" / "seeds" / "in" / "add_ontology_builder.py"
TEXT_SUFFIXES = {".ttl", ".json", ".html", ".sql", ".md", ".yml", ".yaml", ".txt"}


def _builders() -> list[dict]:
    """Every builder agent, read from the platform's own rows (not from a list in this file)."""
    import os

    os.chdir(BACKEND)          # config.py loads ../.env relative to the working directory
    sys.path.insert(0, str(BACKEND))
    from db.database import SessionLocal
    from models.deep_agent import DeepAgentTemplate

    db = SessionLocal()
    try:
        rows = (db.query(DeepAgentTemplate)
                  .filter(DeepAgentTemplate.name.like("Ontology Builder (%"))
                  .order_by(DeepAgentTemplate.id).all())
        out = []
        for row in rows:
            cfg = row.config or {}
            params = (cfg.get("skill_params") or {}).get("build-ontology-from-db") or {}
            key = str(params.get("ontology_key") or "").strip()
            ds = str(cfg.get("datasource") or params.get("datasource") or "").strip()
            if key and ds:
                out.append({"id": row.id, "name": row.name, "key": key, "datasource": ds})
        return out
    finally:
        db.close()


def _settings_for(key: str) -> pathlib.Path | None:
    directory = PROFILES / key
    if not directory.is_dir():
        return None
    hits = sorted(directory.glob("*_settings.json")) or sorted(directory.glob("settings.json"))
    return hits[0] if hits else None


def _versions(key: str) -> tuple[str, str]:
    """(v2_key, v3_key) — continue the number when it is free, else append the generation."""
    m = re.fullmatch(r"(.+)_v(\d+)", key)
    if m:
        stem = m.group(1)
        candidate2, candidate3 = f"{stem}_v2", f"{stem}_v3"
        taken = {p.name for p in PROFILES.iterdir() if p.is_dir()}
        if candidate2 not in taken and candidate3 not in taken:
            return candidate2, candidate3
    return f"{key}_v2", f"{key}_v3"


def _namespace_of(settings: dict) -> str:
    return (settings.get("ns") or "").rstrip("#")


def _copy_profile(source_key: str, target_key: str, *, apply: bool) -> tuple[bool, str]:
    """Copy the installed declarations and rewrite their namespace to the new key's IRI."""
    src_dir, dst_dir = PROFILES / source_key, PROFILES / target_key
    src_settings_path = _settings_for(source_key)
    if src_settings_path is None:
        return False, f"no installed profile for {source_key}"
    if dst_dir.exists() and any(dst_dir.iterdir()):
        return True, f"{target_key} already has a profile (left untouched)"
    settings = json.loads(src_settings_path.read_text(encoding="utf-8"))
    old_ns = _namespace_of(settings)
    new_ns = f"https://cube.local/ontology/{target_key}"
    if not apply:
        return True, f"would copy {len(list(src_dir.rglob('*')))} path(s) {source_key} → {target_key} (ns {old_ns} → {new_ns})"

    dst_dir.mkdir(parents=True, exist_ok=True)
    copied = 0
    for path in src_dir.rglob("*"):
        rel = path.relative_to(src_dir)
        if any(part in (".staging", ".backup") for part in rel.parts):
            continue
        target = dst_dir / rel
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        if path.suffix.lower() in TEXT_SUFFIXES:
            text = path.read_text(encoding="utf-8", errors="replace")
            text = text.replace(old_ns, new_ns).replace(old_ns + "#", new_ns + "#")
            if rel.name.endswith("_settings.json") or rel.name == "settings.json":
                try:
                    doc = json.loads(text)
                except Exception:                                  # noqa: BLE001
                    doc = None
                if isinstance(doc, dict):
                    doc["ns"] = new_ns
                    doc["title"] = f"{doc.get('title') or target_key}（{target_key}）"
                    text = json.dumps(doc, ensure_ascii=False, indent=1) + "\n"
            target.write_text(text, encoding="utf-8")
        else:
            shutil.copy2(path, target)
        copied += 1
    # the settings FILE name must match the new key, or the app cannot resolve the profile
    for old in list(dst_dir.glob("*_settings.json")) + list(dst_dir.glob("settings.json")):
        want = dst_dir / f"{target_key}_settings.json"
        if old != want:
            old.rename(want)
    return True, f"copied {copied} file(s) into {target_key} (ns {new_ns})"


def _register(key: str, datasource: str, *, families: list[str], apply: bool) -> tuple[bool, str]:
    args = [sys.executable, str(ADD), "--key", key, "--datasource", datasource,
            "--theme", f"{key}（v1 的下一版，从已装声明复制为基线）"]
    for family in families:
        args += ["--family", family]
    if apply:
        args.append("--apply")
    run = subprocess.run(args, capture_output=True, text=True, cwd=str(BACKEND))
    tail = [line for line in (run.stdout or "").splitlines() if line.strip()][-3:]
    return run.returncode == 0, " / ".join(tail)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--only", default="", help="comma-separated builder keys to fork")
    args = ap.parse_args()

    builders = _builders()
    if not builders:
        print("no ontology builders found")
        return 2
    only = {k.strip() for k in args.only.split(",") if k.strip()}
    if only:
        builders = [b for b in builders if b["key"] in only]
    print(f"builders: {len(builders)} · mode={'APPLY' if args.apply else 'DRY RUN'}")

    problems = 0
    for builder in builders:
        key, ds = builder["key"], builder["datasource"]
        settings_path = _settings_for(key)
        families = ["abox"] if settings_path and (settings_path.parent / "abox.ttl").is_file() else []
        v2, v3 = _versions(key)
        print(f"\n== {key} (agent {builder['id']}, datasource {ds}) → {v2} · {v3}"
              + (f" · families+{families}" if families else ""))
        for target in (v2, v3):
            ok, note = _copy_profile(key, target, apply=args.apply)
            print(f"   [copy] {target}: {'OK ' if ok else 'FAIL'} {note}")
            if not ok:
                problems += 1
                continue
            ok, note = _register(target, ds, families=families, apply=args.apply)
            print(f"   [reg ] {target}: {'OK ' if ok else 'FAIL'} {note}")
            if not ok:
                problems += 1

    print(f"\n{'done' if not problems else f'{problems} problem(s)'}"
          + ("" if args.apply else " — re-run with --apply to write"))
    return 0 if not problems else 1


if __name__ == "__main__":
    raise SystemExit(main())
