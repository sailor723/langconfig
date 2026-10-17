#!/bin/bash
# Build the team-install zip (docs/settings-refactor.md §7.5): source +
# docker-compose + seed assets. Excludes .env, node_modules, .venv, dist,
# data, outputs, git history — the recipient unzips, runs
# `python backend/scripts/setup.py` (which GENERATES the minimal .env), and is
# up (no git needed).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${OUT:-$ROOT/langconfig.zip}"

cd "$ROOT"
rm -f "$OUT"

zip -r "$OUT" \
  .gitignore .python-version \
  AGENTS.md CLAUDE.md CODE_OF_CONDUCT.md CONTRIBUTING.md LICENSE README.md REFACTORING.md \
  env_example \
  docker-compose.yml \
  package.json package-lock.json index.html postcss.config.js \
  tsconfig.json tsconfig.node.json \
  vite.config.ts vite.preview-dev.config.ts vite.preview.config.ts \
  start.sh \
  scripts backend src public docs learning \
  -x '*.pyc' \
  -x '*__pycache__/*' \
  -x '.pytest_cache/*' \
  -x '*.DS_Store' \
  -x '*.db' '*.sqlite*' \
  -x 'backend/.venv/*' \
  -x 'backend/.pytest_cache/*' \
  -x 'backend/.chat_pdf_kv/*' \
  -x 'backend/.workspace_data/*' \
  -x 'backend/data/*' \
  -x 'backend/outputs/*' \
  -x 'backend/storage/*' \
  -x 'backend/backups/*' \
  -x 'backend/_analysis_output/*' \
  -x 'backend/_data_analysis_sandbox/*' \
  -x 'backend/enterprise_data/*' \
  -x 'backend/notebooks/*' \
  -x 'data/*' \
  -x 'storage/*' \
  -x 'dist/*' \
  -x 'default/*' \
  -x 'src-tauri/*' \
  -x 'node_modules/*' \
  -x '.venv' \
  -x '.venv/*' \
  -x 'my-deep-agent-fe' \
  -x 'my-deep-agent-fe/*' \
  -x '.git/*' \
  -x '.env' \
  -x 'langconfig.zip'

# ── Guards ───────────────────────────────────────────────────────────────────
# The include list names paths instead of ".", which is what keeps the root's
# symlinks (`.venv`, `my-deep-agent-fe`) and stray state out of the bundle. Both
# guards below exist because assuming that has already failed once.
#
# 1. No absolute symlinks. An August bundle shipped `my-deep-agent-fe ->
#    /Users/weiping/...`, a dead link on a WSL machine, because this exclusion
#    pattern used to match only the symlink's CONTENTS when the whole root was
#    being zipped. zip stores a symlink as a link plus its target as content.
leaked="$(zipinfo -l "$OUT" | awk '$1 ~ /^l/ {print $NF}' | while read -r entry; do
  target="$(unzip -p "$OUT" "$entry" 2>/dev/null || true)"
  # `${target#/}` strips a leading slash, so this is true only for an absolute
  # target. Deliberately not `case "$target" in /*)`: a `/`-leading pattern inside
  # a command substitution makes bash report a syntax error, which left `leaked`
  # empty and the guard silently passing — a guard that cannot fail is worse than
  # no guard, so this form is used instead.
  if [ "${target#/}" != "$target" ]; then printf '%s -> %s\n' "$entry" "$target"; fi
done)"
if [ -n "$leaked" ]; then
  echo "REFUSING to ship: the bundle contains absolute symlinks:" >&2
  printf '  %s\n' "$leaked" >&2
  rm -f "$OUT"
  exit 1
fi

# 2. The runtime's own imports are present. `backend/tools/native_impl.py` imports
#    learning.phase9.graphindex.index_build inside a try:, so a bundle without
#    learning/ installs cleanly and then fails only when the GraphIndex tool is
#    called — the worst way to find out. learning/ was excluded outright before.
entries="$(unzip -Z1 "$OUT")"
for required in \
  backend/main.py \
  backend/scripts/seeds/in/seed_all.py \
  backend/scripts/seeds/custom_tools_merge.sql \
  package.json \
  learning/phase9/graphindex/index_build.py
do
  # Here-string, not `unzip -Z1 "$OUT" | grep -qx`: grep -q exits on the first
  # match, unzip then dies of SIGPIPE, and under `set -o pipefail` the pipeline
  # reports failure even though the entry was found. That produced a false
  # "missing" for an entry sitting at line 480 of the archive while an early one
  # passed by luck.
  if ! grep -qx "$required" <<< "$entries"; then
    echo "REFUSING to ship: required entry is missing from the bundle: $required" >&2
    rm -f "$OUT"
    exit 1
  fi
done

echo "Built $OUT ($(du -h "$OUT" | cut -f1))"
