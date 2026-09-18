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
  scripts backend src public docs \
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
  -x 'learning/*' \
  -x 'default/*' \
  -x 'src-tauri/*' \
  -x 'my-deep-agent-fe/*' \
  -x 'node_modules/*' \
  -x '.venv/*' \
  -x '.git/*' \
  -x '.env' \
  -x 'langconfig.zip'

echo "Built $OUT ($(du -h "$OUT" | cut -f1))"
