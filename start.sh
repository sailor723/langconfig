#!/bin/bash
# Start LangConfig — kills previous processes, then starts PostgreSQL + BE + FE
# Usage:  bash start.sh          # start all (db + backend + frontend)
#         bash start.sh --fe     # frontend only
#         bash start.sh --be     # backend only (db started first)

set -e

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
BE_DIR="$ROOT_DIR/backend"
FE_DIR="$ROOT_DIR"

SELF_PID=$$
BE_PIDFILE="/tmp/langconfig-be.pid"
FE_PIDFILE="/tmp/langconfig-fe.pid"

cleanup() {
    rm -f "$BE_PIDFILE" "$FE_PIDFILE" 2>/dev/null
}
trap cleanup EXIT

kill_old() {
    local name="$1" port="$2" pidfile="$3"
    # Kill by PID file
    if [ -f "$pidfile" ]; then
        old_pid=$(cat "$pidfile")
        if kill -0 "$old_pid" 2>/dev/null && [ "$old_pid" != "$SELF_PID" ]; then
            echo "  Killing previous $name (PID $old_pid)..."
            kill "$old_pid" 2>/dev/null || true
            sleep 1
        fi
    fi
    # Kill by port
    local pids
    pids=$(lsof -ti:"$port" 2>/dev/null || true)
    if [ -n "$pids" ]; then
        for p in $pids; do
            if [ "$p" != "$SELF_PID" ]; then
                echo "  Killing process on port $port (PID $p)..."
                kill -9 "$p" 2>/dev/null || true
            fi
        done
        sleep 1
    fi
}

start_postgres() {
    echo "── PostgreSQL ────────────────────────────"
    # Native Homebrew PostgreSQL 16 on :5432 — Docker is NOT used here.
    PG_READY="$(command -v pg_isready || echo /opt/homebrew/opt/postgresql@16/bin/pg_isready)"
    if "$PG_READY" -h 127.0.0.1 -p 5432 >/dev/null 2>&1; then
        echo "  ✅ PostgreSQL already running on :5432"
        return 0
    fi
    echo "  Starting PostgreSQL via brew services (postgresql@16)..."
    brew services start postgresql@16
    for _ in 1 2 3 4 5; do
        if "$PG_READY" -h 127.0.0.1 -p 5432 >/dev/null 2>&1; then
            echo "  ✅ PostgreSQL ready on :5432"
            return 0
        fi
        sleep 2
    done
    echo "  ⚠️  PostgreSQL not ready — the backend may fail to connect"
}

start_backend() {
    echo "── Backend ──────────────────────────────"
    kill_old "backend" 8765 "$BE_PIDFILE"
    echo "  Starting backend..."
    cd "$BE_DIR"
    SKIP_STARTUP_API_TEST=true .venv/bin/uvicorn main:app --host 0.0.0.0 --port 8765 --reload &
    echo $! > "$BE_PIDFILE"
    echo "  Backend PID: $(cat "$BE_PIDFILE")"
    sleep 3
    # Quick health check
    for i in 1 2 3; do
        if curl -sf http://127.0.0.1:8765/api/chat/health >/dev/null 2>&1; then
            echo "  ✅ Backend healthy on http://localhost:8765"
            break
        fi
        sleep 2
    done
    cd "$ROOT_DIR"
}

start_frontend() {
    echo "── Frontend ─────────────────────────────"
    kill_old "frontend" 1421 "$FE_PIDFILE"
    echo "  Starting frontend..."
    cd "$FE_DIR"
    npm run dev &
    echo $! > "$FE_PIDFILE"
    echo "  Frontend PID: $(cat "$FE_PIDFILE")"
    sleep 4
    if curl -sf http://127.0.0.1:1421/ >/dev/null 2>&1; then
        echo "  ✅ Frontend running on http://localhost:1421"
    else
        echo "  ⏳ Frontend starting (may need a few more seconds)..."
    fi
    cd "$ROOT_DIR"
}

echo ""
echo "╔══════════════════════════════════════════╗"
echo "║        LangConfig — Quick Start          ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# Parse args
if [ "$1" = "--be" ]; then
    start_postgres
    start_backend
elif [ "$1" = "--fe" ]; then
    start_frontend
else
    start_postgres
    start_backend
    start_frontend
fi

echo ""
echo "Done. Use Ctrl+C to stop."
echo ""
echo "  Backend:  http://localhost:8765  (docs: http://localhost:8765/docs)"
echo "  Frontend: http://localhost:1421"
echo ""
