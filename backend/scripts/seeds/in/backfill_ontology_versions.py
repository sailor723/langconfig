#!/usr/bin/env python3
"""One-time backfill: put the ontologies that already exist into the version registry.

`features/ontology/versioning.py` was written after sixteen keys already existed, so the registry
starts empty while the platform already has a history: `new_coldchain_v3…v6` are four successive
builds of the cold-chain ontology, and `sunhing_v1` is the customer build that replaced nothing.
Without this backfill `latest` is blank for every family, and the first `--base` registration would
record v1 over a v4 history.

The table below is the DECISION, not a computation:

* `customer` — a client deliverable; nothing in the repo deletes it (sunhing, new_coldchain).
* `demo`     — a shipped illustration that must keep running (tpch, retail, logistics, clinic, abc,
                the talent ontology behind the hiring feature, and the measured ebl/eff/meeting builds).
* `trial`    — throwaway keys used to test the builder itself (probe_key); safe to delete.
* `tutorial` — teaching material (talent_steps).

Change a row here if it is wrong; re-running is idempotent (a key already in the registry is left
alone and reported).

    python backend/scripts/seeds/in/backfill_ontology_versions.py            # dry run
    python backend/scripts/seeds/in/backfill_ontology_versions.py --apply
"""
from __future__ import annotations

import argparse
import pathlib
import sys

BACKEND = pathlib.Path(__file__).resolve().parents[3]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
from features.ontology import versioning as V  # noqa: E402

PROFILES = BACKEND / "features" / "ontology" / "profiles"

#: key (as built) → (kind, theme). A key that is in `profiles/` but missing here is REPORTED, never
#: guessed: an unclassified ontology is the one thing this backfill will not invent.
KNOWN: dict[str, tuple[str, str]] = {
    "sunhing_v1":        ("customer", "新鸿（Sun Hing）冷鏈"),
    "new_coldchain_v3":  ("customer", "新冷鏈 v3"),
    "new_coldchain_v4":  ("customer", "新冷鏈 v4"),
    "new_coldchain_v5":  ("customer", "新冷鏈 v5"),
    "new_coldchain_v6":  ("customer", "新冷鏈 v6"),
    "tpch":              ("demo", "TPC-H（演示）"),
    "retail":            ("demo", "零售（演示）"),
    "logistics":         ("demo", "物流（演示）"),
    "clinic":            ("demo", "诊所（演示）"),
    "abc":               ("demo", "ABC 样本（演示）"),
    "ebl_ops_v1":        ("demo", "EBL 运营（实测构建）"),
    "eff_ops_v1":        ("demo", "EFF 运营（实测构建）"),
    "meeting_v1":        ("demo", "会议（实测构建）"),
    "talent_v1":         ("demo", "招聘（产品本体）"),
    "talent_steps":      ("tutorial", "招聘五步（教程）"),
    "probe_key":         ("trial", "构建器探针（可删）"),
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="write profiles/_versions.json")
    args = ap.parse_args()

    reg = V.load(PROFILES / V.REGISTRY_NAME)
    present = sorted(p.name for p in PROFILES.iterdir() if p.is_dir() and V.KEY_RE.fullmatch(p.name))
    unknown = [k for k in present if k not in KNOWN]
    missing = [k for k in KNOWN if k not in present]

    print(f"registry: {PROFILES / V.REGISTRY_NAME}")
    print(f"profiles/ holds {len(present)} key(s), the table classifies {len(KNOWN)}")
    if unknown:
        print("\n  NOT CLASSIFIED (add a row, do not let it default):")
        for k in unknown:
            print(f"    {k}")
    if missing:
        print("\n  in the table but no directory (a declared-but-unbuilt key):")
        for k in missing:
            print(f"    {k}  (kind={KNOWN[k][0]})")

    todo = []
    for key in present:
        if key not in KNOWN:
            continue
        kind, theme = KNOWN[key]
        base, version = V.parse_key(key)
        fam = (reg.get("families") or {}).get(base) or {}
        already = next((v for v in fam.get("versions") or [] if str(v.get("key")) == key), None)
        if already is not None:
            print(f"  = {key:<18} already recorded ({already.get('kind')}, v{already.get('version')})")
            continue
        todo.append((key, base, version, kind, theme))

    if not todo:
        print("\nnothing to record.")
        return 0 if not unknown else 1

    print("\nwould record (oldest → newest per family):")
    for key, base, version, kind, theme in sorted(todo, key=lambda t: (t[1], t[2])):
        print(f"  + {key:<18} {base} v{version:<3} kind={kind:<8} {theme}")

    if not args.apply:
        print("\ndry run — nothing written. Re-run with --apply.")
        return 0

    for key, base, version, kind, theme in sorted(todo, key=lambda t: (t[1], t[2])):
        V.record(reg, key=key, kind=kind, theme=theme)
    path = V.save(reg)
    print(f"\nwrote {path.relative_to(BACKEND.parent)}")
    for base in sorted((reg.get("families") or {})):
        fam = reg["families"][base]
        print(f"  {base:<16} latest={fam.get('latest')}  chain={[v['key'] for v in fam['versions']]}")
    return 0 if not unknown else 1


if __name__ == "__main__":
    sys.exit(main())
