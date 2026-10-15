"""Bring knowledge into knowledge bases. One tool, two verbs, catalog-aware.

    cd backend

    # a teammate's legacy tree -> one knowledge base per folder
    .venv/bin/python scripts/kv_migrate.py ingest --from data/documents/project_1 \\
        --loose-name EBL_misc                       # dry run
    .venv/bin/python scripts/kv_migrate.py ingest --from data/documents/project_1 \\
        --loose-name EBL_misc --apply

    # re-categorise loose files into a real knowledge base, creating it if needed
    .venv/bin/python scripts/kv_migrate.py recategorize --from EBL_misc \\
        --path "3d136714_EBL OS Introduction.pdf" --to EBL_OS_docs --apply

Why this replaces the old scripts
---------------------------------
Those scripts are gone (removed 2026-10-15). They *moved* folders around inside the tree and had to
journal every move so it could be reversed. Every bug in them came from that: journals
overwriting each other inside one second, an inverse hierarchy shift that wrote `industry=None`,
a manifest carried back into the parent folder.

`ingest` **copies**. The source is never touched, so there is nothing to reverse — undo is
"delete the target knowledge base". And it is idempotent, so re-running is safe, which is why a
collision merges instead of being refused.

Both verbs go through one implementation in `services/kv_ingest.py`, which is also the code path an
online folder upload uses. The two cannot drift apart, because there is only one.

What it will not do
-------------------
- **It will not name loose files for you.** Files sitting directly under a legacy project have no
  folder to inherit a name from. Inventing one is how `(ungrouped)` happened — a bucket whose
  documented fate was documents the user cannot filter and the agent cannot route. Pass
  `--loose-name`, or they are listed and left alone.
- **It will not guess that two names are the same.** `business-model` and `business_model` are
  provably one knowledge base and merge. `semiconduct_industry` and `semiconductor_industry` are
  one edit apart, and merging those is a guess — they are reported instead.
- **It will not rename an existing knowledge base.**
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)                     # the knowledge root resolves against the CWD

from services.kb_discovery import legacy_root                      # noqa: E402
from services.kv_ingest import (                                   # noqa: E402
    IngestReport, NamingPolicy, adopt_existing_migrations, ingest_directory, near_misses,
    recategorize,
)


def _resolve_source(value: str) -> Path:
    """A path, or the name of a folder under the legacy root.

    `--from project_1` is what a teammate will type; `--from data/documents/project_1` is what a
    script will pass. Both mean the same directory.
    """
    given = Path(value).expanduser()
    if given.is_dir():
        return given.resolve()
    under_legacy = Path(legacy_root()) / value
    if under_legacy.is_dir():
        return under_legacy.resolve()
    raise SystemExit(f"not a directory: {value}")


def _naming(value: str) -> NamingPolicy:
    return NamingPolicy.CANONICAL if value == "canonical" else NamingPolicy.PRESERVE


def _print(reports: list[IngestReport], apply: bool) -> int:
    refused = 0
    for report in reports:
        for line in report.lines():
            print(line)
        refused += len(report.refused)
        print()
    written = sum(len(r.written) for r in reports)
    dupes = sum(len(r.duplicates) for r in reports)
    print(f"  {written} file(s) would be written, {dupes} skipped as duplicates, "
          f"{refused} refused")
    if not apply:
        print("DRY RUN — nothing was changed. Pass --apply to do it.")
    elif refused:
        print("Some files were refused; re-run the dry run to see them listed.")
    return 0 if (not apply or not refused) else 1


def cmd_ingest(args: argparse.Namespace) -> int:
    source = _resolve_source(args.source)
    naming = _naming(args.naming)

    # A new knowledge base whose name is one edit from an existing one is the duplication this is
    # meant to prevent, so say so before creating anything.
    if args.knowledge:
        for miss in near_misses(args.knowledge):
            print(f"  ! {args.knowledge!r} is close to the existing {miss!r} — "
                  f"if that is the same thing, pass --knowledge {miss}")

    print(f"  source  : {source}")
    print(f"  naming  : {naming.value}"
          + ("  (folder names folded to snake_case)" if naming is NamingPolicy.CANONICAL else
             "  (a folder keeps its own name — folder name is knowledge name)"))
    print()

    reports = ingest_directory(
        source,
        knowledge=args.knowledge,
        loose_name=args.loose_name,
        apply=args.apply,
        naming=naming,
        strip_prefix=args.strip_prefix,
    )
    return _print(reports, args.apply)


def cmd_recategorize(args: argparse.Namespace) -> int:
    naming = _naming(args.naming)
    if args.to is None:
        raise SystemExit("--to is required: name the knowledge base to move into")

    for miss in near_misses(args.to):
        print(f"  ! {args.to!r} is close to the existing {miss!r} — "
              f"if that is the same thing, pass --to {miss}")

    report = recategorize(
        args.source, args.to,
        paths=args.path or None,
        apply=args.apply,
        naming=naming,
    )
    return _print([report], args.apply)


def cmd_adopt(args: argparse.Namespace) -> int:
    """One-time: record provenance for folders migrated before provenance existed.

    Needed once per machine that migrated with an older version. Without it those folders carry no
    record, so the panel offers them again forever. After this, the cheap fingerprint check takes
    over and no repeat run is needed.
    """
    rows = adopt_existing_migrations(apply=args.apply)
    if not rows:
        print("  nothing to adopt — no legacy folder has content sitting in a knowledge base")
        return 0
    adopted = 0
    for r in rows:
        if r["adopted"]:
            adopted += 1
            status = "recorded" if args.apply else "would record"
        else:
            status = (f"skipped — {r['missing']} of {r['distinct']} contents are not in "
                      f"{r['knowledge']}")
        print(f"  {r['project']}/{r['folder']}  ->  {r['knowledge']}"
              f"   {r['already_present']}/{r['distinct']} contents already there   {status}")
    print(f"\n  {adopted} folder(s) {'recorded' if args.apply else 'would be recorded'}")
    if not args.apply:
        print("DRY RUN — nothing was changed. Pass --apply to do it.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="verb", required=True)

    ing = sub.add_parser("ingest", help="copy a directory into knowledge bases")
    ing.add_argument("--from", dest="source", required=True, metavar="DIR",
                     help="source directory (a path, or a folder under the legacy root)")
    ing.add_argument("--knowledge", default=None,
                     help="put everything into this ONE knowledge base (its subfolders become "
                          "folders inside it); omit to make one knowledge base per subfolder")
    ing.add_argument("--loose-name", default=None, metavar="NAME",
                     help="knowledge base for files sitting directly under the source")
    ing.add_argument("--naming", default="preserve", choices=("preserve", "canonical"),
                     help="preserve: a folder keeps its own name (default). "
                          "canonical: fold new names to snake_case")
    ing.add_argument("--strip-prefix", type=int, default=1, metavar="N",
                     help="strip up to N leading 8-hex prefixes from names (default 1)")
    ing.add_argument("--apply", action="store_true")
    ing.set_defaults(func=cmd_ingest)

    rec = sub.add_parser("recategorize", help="move documents between knowledge bases")
    rec.add_argument("--from", dest="source", required=True, metavar="KB",
                     help="the knowledge base documents are moving out of")
    rec.add_argument("--to", required=True, metavar="NAME",
                     help="the knowledge base to move into; created if it does not exist")
    rec.add_argument("--path", action="append", metavar="REL",
                     help="a document inside --from to move (repeatable); omit to move all")
    rec.add_argument("--naming", default="preserve", choices=("preserve", "canonical"))
    rec.add_argument("--apply", action="store_true")
    rec.set_defaults(func=cmd_recategorize)

    ad = sub.add_parser("adopt", help="record provenance for folders migrated by an older version")
    ad.add_argument("--apply", action="store_true")
    ad.set_defaults(func=cmd_adopt)

    args = ap.parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
