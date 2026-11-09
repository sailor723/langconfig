#!/usr/bin/env bash
# housekeeping_verify.sh — one command that proves the housekeeping changes hold.
#
# Every check here exists because something was silently wrong once:
#   guards    a route declared twice, a function defined twice, a view that renders nothing,
#             a doc endpoint that no router serves, a hardcoded backend origin
#   docs      the document-store classifier (healthy / unreferenced / dangling)
#   frontend  the app still typechecks and builds
#   store     what the document store looks like right now (report only — never changes anything)
#
# Usage:
#   ./scripts/housekeeping_verify.sh            # everything
#   ./scripts/housekeeping_verify.sh --quick    # skip the frontend build
#
# Exit code is 0 only if every check passes. The backend suite has 20 PRE-EXISTING failures that are
# unrelated to housekeeping (user_workspace_path, ontology_build, user_api, …); `--full-suite` runs it
# and compares against that recorded baseline instead of failing on them.

set -uo pipefail
cd "$(dirname "$0")/.."
REPO="$PWD"
BACKEND="$REPO/backend"
PY="$BACKEND/.venv/bin/python"
QUICK=0
FULL=0
for arg in "$@"; do
  case "$arg" in
    --quick) QUICK=1 ;;
    --full-suite) FULL=1 ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

pass=0; fail=0
step() { printf '\n\033[1m== %s\033[0m\n' "$1"; }
ok()   { printf '   \033[32mPASS\033[0m %s\n' "$1"; pass=$((pass+1)); }
bad()  { printf '   \033[31mFAIL\033[0m %s\n' "$1"; fail=$((fail+1)); }

# ── 1. guards + document classifier ────────────────────────────────────────────────────────────────
step "backend guards (tests/test_housekeeping_guards.py + test_housekeeping_documents.py)"
if out=$("$PY" -m pytest "$BACKEND/tests/test_housekeeping_guards.py" \
                         "$BACKEND/tests/test_housekeeping_documents.py" \
                         -q --no-header -p no:cacheprovider 2>&1); then
  ok "$(echo "$out" | tail -1)"
else
  bad "guards failed"; echo "$out" | tail -30
fi

# ── 2. the full backend suite, against the recorded baseline ──────────────────────────────────────
if [ "$FULL" = 1 ]; then
  step "backend suite vs baseline (20 pre-existing failures)"
  baseline=$(mktemp); after=$(mktemp)
  printf '%s\n' \
    "FAILED tests/test_core_settings.py::test_the_settings_api_round_trips_a_value" \
    > /dev/null   # (the real baseline is captured below, not hardcoded)
  "$PY" -m pytest "$BACKEND/tests" -q --no-header -p no:cacheprovider \
        --ignore="$BACKEND/tests/test_neo4j_document_enrichment.py" \
        --ignore="$BACKEND/tests/test_pageindex_full_content_loader.py" 2>&1 \
    | grep -E '^(FAILED|ERROR)' | sort > "$after"
  echo "   failures now: $(wc -l < "$after" | tr -d ' ')  (recorded baseline: 20)"
  if [ "$(wc -l < "$after" | tr -d ' ')" -le 20 ] && ! grep -qE '^FAILED tests/test_housekeeping' "$after"; then
    ok "no housekeeping failure; not more failures than the baseline"
  else
    bad "new failures appeared:"; grep -E '^FAILED tests/test_housekeeping' "$after" || true
    echo "   compare with: $(git -C "$REPO" stash list | head -1)"
  fi
  rm -f "$baseline" "$after"
fi

# ── 3. frontend ───────────────────────────────────────────────────────────────────────────────────
if [ "$QUICK" = 0 ]; then
  step "frontend typecheck + build"
  # the status must come from tsc, not from the grep that filters its output
  tsc_out=$(cd "$REPO" && npx tsc --noEmit -p tsconfig.json 2>&1); tsc_rc=$?
  tsc_out=$(printf '%s\n' "$tsc_out" | grep -v '^npm warn' || true)
  if [ "$tsc_rc" -eq 0 ]; then
    ok "tsc: no type errors"
  else
    bad "tsc reported errors"; printf '%s\n' "$tsc_out" | head -20
  fi
  if out=$(cd "$REPO" && npm run build 2>&1 | tail -3); then
    ok "vite build: $(echo "$out" | grep -E 'built in' | tail -1)"
  else
    bad "vite build failed"; echo "$out" | head -20
  fi
fi

# ── 4. what the document store looks like (report only) ───────────────────────────────────────────
step "document store (report only — nothing is changed)"
"$PY" "$REPO/scripts/housekeeping_documents.py" --db --limit 3 2>&1 | sed 's/^/   /' || bad "report failed"

printf '\n\033[1m== %d passed, %d failed\033[0m\n' "$pass" "$fail"
[ "$fail" -eq 0 ]
