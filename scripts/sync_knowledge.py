#!/usr/bin/env python
"""Copy knowledge bases from this install to another one (e.g. the training ECS).

Knowledge is a FOLDER TREE, not a database row: a base is `data/knowledge/<name>/`
plus its catalog `data/knowledge/.kvmeta/<name>.json`. Copying one therefore has
three failure modes this script exists to avoid:

1. **Overwriting someone else's base.** The target may already hold a curated
   version (`eyewear_industry` exists on both machines here). A missing base is
   copied; an existing one is left alone unless `--overwrite` says otherwise.
2. **Records that list but cannot be read.** `storage_path` in the catalog is an
   ABSOLUTE path (`/Users/…/backend/data/knowledge/<name>/<hash>_file.md`), so a
   catalog copied verbatim points at the sender's disk: the target lists the
   documents and answers `{"detail":"File not found on disk"}` for every one of
   them. The copy rewrites that prefix to the destination tree.
3. **Sync noise.** Test bases (a 110 MB `langconfig-test`) are excluded by
   default; `--exclude` adds more.

    python scripts/sync_knowledge.py --remote root@8.216.101.189 --dry-run
    python scripts/sync_knowledge.py --remote root@8.216.101.189 \\
        --key ~/Downloads/jp_spot.pem --dest /root/langconfig/backend/data/knowledge
    python scripts/sync_knowledge.py --remote root@8.216.101.189 \\
        --exclude langconfig-test --exclude project-6
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LOCAL_ROOT = REPO / "backend" / "data" / "knowledge"
#: Bases that are never worth shipping: platform tests and per-project scratch
#: that would only inflate the target.
DEFAULT_EXCLUDES = ("langconfig-test",)


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


def ssh(host: str, key: str | None, command: str) -> str:
    cmd = ["ssh", "-o", "ConnectTimeout=20"]
    if key:
        cmd += ["-i", str(Path(key).expanduser())]
    cmd += [host, command]
    done = run(cmd)
    if done.returncode != 0:
        raise SystemExit(f"ssh failed ({done.returncode}): {done.stderr.strip()[:400]}")
    return done.stdout


def remote_bases(host: str, key: str | None, dest: str) -> dict[str, tuple[int, int]]:
    """`{name: (file_count, size_kb)}` for the bases already on the target."""
    out = ssh(
        host, key,
        f"cd {dest} && for d in */; do n=${{d%/}}; [ \"$n\" = .kvmeta ] && continue; "
        f"printf '%s|%s|%s\\n' \"$n\" \"$(find \"$n\" -type f ! -name kb.json | wc -l)\" "
        f"\"$(du -sk \"$n\" | cut -f1)\"; done",
    )
    bases: dict[str, tuple[int, int]] = {}
    for line in out.splitlines():
        parts = line.strip().split("|")
        if len(parts) == 3 and parts[0]:
            bases[parts[0]] = (int(parts[1]), int(parts[2]))
    return bases


def local_bases() -> dict[str, tuple[int, int]]:
    bases: dict[str, tuple[int, int]] = {}
    for d in sorted(LOCAL_ROOT.iterdir()):
        if not d.is_dir() or d.name.startswith("."):
            continue
        files = [f for f in d.rglob("*") if f.is_file() and f.name != "kb.json"]
        size_kb = sum(f.stat().st_size for f in files) // 1024
        bases[d.name] = (len(files), size_kb)
    return bases


def copy_base(name: str, host: str, key: str | None, dest: str) -> None:
    src = LOCAL_ROOT / name
    rsync = ["rsync", "-rt", "-e", f"ssh -o ConnectTimeout=20" + (f" -i {Path(key).expanduser()}" if key else "")]
    done = run([*rsync, str(src), f"{host}:{dest}/"])
    if done.returncode != 0:
        raise SystemExit(f"rsync {name} failed: {done.stderr.strip()[:400]}")
    catalog = LOCAL_ROOT / ".kvmeta" / f"{name}.json"
    if catalog.exists():
        done = run([*rsync, str(catalog), f"{host}:{dest}/.kvmeta/"])
        if done.returncode != 0:
            raise SystemExit(f"rsync catalog {name} failed: {done.stderr.strip()[:400]}")


def rewrite_paths(name: str, host: str, key: str | None, dest: str) -> int:
    """Point the copied catalog's absolute `storage_path` at the target tree."""
    old = str(LOCAL_ROOT)
    new = dest.rstrip("/")
    if old == new:
        return 0
    script = (
        "import json, sys\n"
        "from pathlib import Path\n"
        f"p = Path(r'{new}/.kvmeta/{name}.json')\n"
        "if not p.exists():\n"
        "    print(0); sys.exit()\n"
        "t = p.read_text(encoding='utf-8')\n"
        f"n = t.count(r'{old}')\n"
        f"p.write_text(t.replace(r'{old}', r'{new}'), encoding='utf-8')\n"
        "print(n)\n"
    )
    out = ssh(host, key, f"python3 - <<'PY'\n{script}PY")
    return int((out.strip().splitlines() or ["0"])[-1] or 0)


def verify(host: str, key: str | None, dest: str, names: list[str]) -> int:
    """Fail loudly if a copied base arrived with a different file count."""
    bad = 0
    remote = remote_bases(host, key, dest)
    local = local_bases()
    for name in names:
        want = local[name][0]
        got = remote.get(name, (0, 0))[0]
        if want != got:
            bad += 1
            print(f"  ✗ {name}: local {want} files, remote {got}")
    return bad


def main() -> int:
    ap = argparse.ArgumentParser(description="Copy missing knowledge bases to another install.")
    ap.add_argument("--remote", required=True, help="ssh host, e.g. root@8.216.101.189")
    ap.add_argument("--key", default=None, help="ssh private key")
    ap.add_argument("--dest", default="/root/langconfig/backend/data/knowledge",
                    help="knowledge root ON the target (absolute)")
    ap.add_argument("--exclude", action="append", default=[],
                    help=f"base name to skip (default: {', '.join(DEFAULT_EXCLUDES)})")
    ap.add_argument("--overwrite", action="store_true",
                    help="re-copy bases that already exist on the target (default: leave them)")
    ap.add_argument("--dry-run", action="store_true", help="report, copy nothing")
    args = ap.parse_args()

    excludes = {*DEFAULT_EXCLUDES, *args.exclude}
    local = local_bases()
    if not local:
        return print(f"no knowledge bases under {LOCAL_ROOT}") or 1
    remote = remote_bases(args.remote, args.key, args.dest)

    planned: list[str] = []
    print(f"{'base':34} {'files':>6} {'size':>8}  action")
    for name, (files, size_kb) in local.items():
        if name in excludes:
            action = "excluded"
        elif name in remote and not args.overwrite:
            action = "already there — left alone"
        else:
            action = "copy"
            planned.append(name)
        print(f"{name:34} {files:6} {size_kb / 1024:7.1f}M  {action}")

    if not planned:
        print("\nnothing to copy.")
        return 0
    if args.dry_run:
        print(f"\nwould copy {len(planned)} base(s): {', '.join(planned)}")
        return 0

    total_kb = sum(local[n][1] for n in planned)
    print(f"\ncopying {len(planned)} base(s), {total_kb / 1024:.1f} MB …")
    ssh(args.remote, args.key, f"mkdir -p {args.dest}/.kvmeta")
    for name in planned:
        copy_base(name, args.remote, args.key, args.dest)
        changed = rewrite_paths(name, args.remote, args.key, args.dest)
        print(f"  ✓ {name}" + (f" (rewrote {changed} storage_path values)" if changed else ""))

    print("\nverifying file counts …")
    bad = verify(args.remote, args.key, args.dest, planned)
    if bad:
        print(f"{bad} base(s) did not match — check $DEST/{planned[0]} and the rsync output above")
        return 1
    print(f"all {len(planned)} base(s) match; target is ready (reload the Knowledge activity).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
