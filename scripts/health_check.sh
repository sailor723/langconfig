#!/bin/bash
# LangConfig pre-start health check — verifies Postgres + API + seeds before start.sh
# Usage:  bash scripts/health_check.sh            # backend default :8765
#         BACKEND_PORT=8799 bash scripts/health_check.sh   # custom port
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT="${BACKEND_PORT:-8765}"
BASE="http://127.0.0.1:${PORT}"
fail=0

echo "╔══════════════════════════════════════════════════╗"
echo "║   LangConfig Pre-Start Health Check              ║"
echo "╚══════════════════════════════════════════════════╝"
echo "Target backend: ${BASE}"

# 1. PostgreSQL reachable?
echo ""
echo "── [1/4] PostgreSQL ───────────────────────────────"
PG_PORT="$(grep -E '^POSTGRES_PORT=' "$ROOT/.env" 2>/dev/null | head -1 | cut -d= -f2)"
PG_PORT="${PG_PORT:-5432}"
if command -v pg_isready >/dev/null 2>&1; then
    if pg_isready -h 127.0.0.1 -p "$PG_PORT" -q 2>/dev/null; then
        echo "  ✅ PostgreSQL accepting connections on :${PG_PORT}"
    else
        echo "  ❌ PostgreSQL NOT ready on :${PG_PORT} — start it first:"
        echo "     native:  brew services start postgresql@16   (macOS)"
        echo "     docker:  docker compose up -d postgres"
        fail=1
    fi
else
    echo "  ⚠️  pg_isready not found — skipping (will rely on API health)"
fi

# 2. Backend API up?
echo ""
echo "── [2/4] Backend API ──────────────────────────────"
if curl -sf -m 5 "${BASE}/health/" >/dev/null 2>&1 || curl -sf -m 5 "${BASE}/" >/dev/null 2>&1; then
    echo "  ✅ Backend reachable on :${PORT}"
else
    echo "  ❌ Backend NOT reachable on :${PORT}"
    echo "     Start it:  bash start.sh --be   (or: cd backend && uv run python main.py)"
    fail=1
fi

# 3. Detailed health (DB + workers)
echo ""
echo "── [3/4] Detailed health (/health/detailed) ─────"
DETAILED="$(curl -sf -m 8 "${BASE}/health/detailed" 2>/dev/null)" || DETAILED=""
if [ -n "$DETAILED" ]; then
    DB_ST="$(echo "$DETAILED" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('components',{}).get('database',{}).get('status','?'))" 2>/dev/null)"
    OVERALL="$(echo "$DETAILED" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status','?'))" 2>/dev/null)"
    echo "  overall: ${OVERALL:-?} | database: ${DB_ST:-?}"
    if [ "${DB_ST}" != "healthy" ]; then
        echo "  ❌ Database component unhealthy — did you run seed_all.py?"
        fail=1
    fi
else
    echo "  ⚠️  detailed endpoint unreachable (server may still be booting)"
fi

# 4. Seeded data present (agents + models via API)
echo ""
echo "── [4/4] Seeded data ──────────────────────────────"
AGENTS="$(curl -sf -m 8 "${BASE}/api/deepagents/?public_only=false" 2>/dev/null)"
if [ -n "$AGENTS" ]; then
    N="$(echo "$AGENTS" | python3 -c "import sys,json; d=json.load(sys.stdin); print(len(d) if isinstance(d,list) else 0)" 2>/dev/null)"
    echo "  ✅ deep agents in DB: ${N:-?}"
    if [ "${N:-0}" -lt 10 ]; then
        echo "  ❌ Too few agents — run:  cd backend && WORKSPACE_ROOT=... uv run python scripts/seeds/seed_all.py"
        fail=1
    fi
else
    echo "  ❌ Cannot list agents — backend down or not seeded"
    fail=1
fi

echo ""
if [ "$fail" -eq 0 ]; then
    echo "✅ ALL CHECKS PASSED — ready to run:  bash start.sh"
    exit 0
else
    echo "❌ SOME CHECKS FAILED — fix the issues above, then re-run this script."
    exit 1
fi
