#!/bin/bash
# Knowledge base doctor — one command, so nobody has to know where the scripts live.
#
#   bash doctor.sh          read-only report: storage mode, document paths, project folders
#   bash doctor.sh --fix    adopt project folders that have no database row (writes rows only)
#
# The case this is for: a legacy data/documents folder was copied into a fresh install, the files
# and their .kvmeta records arrived intact, and the Knowledge panel shows nothing — because the
# panel lists projects from the database and no row exists for those ids. The documents are not
# lost, they are unreachable.
#
# Nothing here touches, moves or deletes a document. --fix inserts the missing `projects` rows and
# nothing else; it is idempotent, and re-running it reports "no orphan folders".
set -uo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
BE="$ROOT/backend"
PY="$BE/.venv/bin/python"

if [ ! -x "$PY" ]; then
    echo "✗ no virtualenv at backend/.venv"
    echo "  create it first:  cd backend && uv sync"
    exit 1
fi

cd "$BE" || exit 1

echo "── 1. where this install keeps things ──────────────────────────────"
"$PY" scripts/audit_local_data.py || exit 1

echo
echo "── 2. do the recorded document paths still resolve? ────────────────"
"$PY" - <<'EOF' || exit 1
import glob, json, os
try:
    from services.file_storage import file_storage
    root = file_storage.base_dir
except Exception:
    root = "data/documents"
recs = [v["storage_path"] for f in glob.glob(os.path.join(str(root), ".kvmeta", "*.json"))
        for v in json.load(open(f)).values() if v.get("storage_path")]
missing = [p for p in recs if not os.path.exists(p)]
print(f"   {len(recs)} record(s), {len(missing)} DANGLING")
for p in missing[:5]:
    print(f"     missing: {p}")
if missing:
    print("   ^ the files are not where the records say. That is what a knowledge base copied")
    print("     between machines looks like: its registered paths still name the old machine.")
    print("     Fix it with, then re-run this script:")
    print("         .venv/bin/python scripts/relocate_knowledge_paths.py          # report")
    print("         .venv/bin/python scripts/relocate_knowledge_paths.py --apply  # write")
EOF

echo
echo "── 3. project folders with no project row ──────────────────────────"
if [ "${1:-}" = "--fix" ]; then
    "$PY" scripts/adopt_orphan_projects.py --apply "${@:2}"
else
    "$PY" scripts/adopt_orphan_projects.py
    echo
    echo "   Re-run with --fix to adopt them:  bash doctor.sh --fix"
fi

echo
echo "── next: refresh the browser ───────────────────────────────────────"
echo "   Knowledge panel → the project appears → open a document."
echo "   A document opening is the real test: listing reads the index, opening reads the file."
