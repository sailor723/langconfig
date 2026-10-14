#!/bin/bash
# Start LangConfig — kills previous processes, then starts PostgreSQL + BE + FE
#
# Usage:  ./start.sh            # everything: PostgreSQL + backend (:8765) + frontend (:1421)
#         ./start.sh --be       # backend only (PostgreSQL started first)
#         ./start.sh --fe       # frontend only
#
# One command starts both halves — that is the default (no argument).
#
# Options (env vars):
#   UVICORN_WORKERS=1   uvicorn worker processes (default 1 — see the note in
#                       start_backend: the Graph activity's threads/checkpointers
#                       are in-process, so >1 breaks HITL resume)

set -e

ROOT_DIR="$(cd "$(dirname "$0")" && pwd)"
BE_DIR="$ROOT_DIR/backend"
FE_DIR="$ROOT_DIR"

SELF_PID=$$
# PID files persist across runs (NOT deleted on exit) so a re-run can stop the
# previous uvicorn/vite instance, and so you can stop manually:
#   kill $(cat /tmp/langconfig-be.pid) $(cat /tmp/langconfig-fe.pid)
BE_PIDFILE="/tmp/langconfig-be.pid"
FE_PIDFILE="/tmp/langconfig-fe.pid"

kill_old() {
    local name="$1" port="$2" pidfile="$3"

    # 1) Stop via PID file first. SIGTERM lets the uvicorn reloader shut down
    #    its worker cleanly (SIGKILL is only the last resort).
    if [ -f "$pidfile" ]; then
        old_pid=$(cat "$pidfile")
        if kill -0 "$old_pid" 2>/dev/null && [ "$old_pid" != "$SELF_PID" ]; then
            echo "  Stopping previous $name (PID $old_pid)..."
            kill "$old_pid" 2>/dev/null || true
            for _ in 1 2 3 4 5; do
                kill -0 "$old_pid" 2>/dev/null || break
                sleep 1
            done
            kill -9 "$old_pid" 2>/dev/null || true
        fi
    fi

    # 2) Kill anything still LISTENING on the port. Restrict to LISTEN state —
    #    `lsof -i:PORT` alone also matches outbound sockets, e.g. the Vite dev
    #    server's ws-proxy connections to the backend on 8765, which would
    #    wrongly take down the frontend too.
    local pids
    pids=$(lsof -ti:"$port" -sTCP:LISTEN 2>/dev/null || true)
    if [ -n "$pids" ]; then
        for p in $pids; do
            if [ "$p" != "$SELF_PID" ]; then
                echo "  Stopping process on port $port (PID $p)..."
                kill -9 "$p" 2>/dev/null || true
            fi
        done
    fi

    # 3) Wait until the port is actually free so the new server can bind.
    for _ in 1 2 3 4 5; do
        lsof -ti:"$port" -sTCP:LISTEN >/dev/null 2>&1 || return 0
        sleep 1
    done
    echo "  ⚠️  Port $port is still busy after 5s"
    return 1
}

start_postgres() {
    echo "── PostgreSQL ────────────────────────────"
    # The DB mode is driven by POSTGRES_PORT in the root .env:
    #   5432 = native Homebrew postgresql@16,  5433 = Docker (pgvector/pgvector:pg16)
    PG_PORT="$(grep -E '^POSTGRES_PORT=' "$ROOT_DIR/.env" 2>/dev/null | head -1 | cut -d= -f2)"
    PG_PORT="${PG_PORT:-5432}"

    if [ "$PG_PORT" = "5433" ]; then
        # Docker mode: keep the langconfig-postgres container running
        if docker ps --format '{{.Names}} {{.Ports}}' 2>/dev/null | grep -q "langconfig-postgres.*5433"; then
            echo "  ✅ Docker PostgreSQL already running on :5433"
            return 0
        fi
        echo "  Starting Docker PostgreSQL (pgvector/pgvector:pg16)..."
        (cd "$ROOT_DIR" && docker compose up -d postgres)
        for _ in 1 2 3 4 5; do
            if [ "$(docker inspect langconfig-postgres --format '{{.State.Health.Status}}' 2>/dev/null)" = "healthy" ]; then
                echo "  ✅ Docker PostgreSQL healthy on :5433"
                return 0
            fi
            sleep 2
        done
        echo "  ⚠️  Docker PostgreSQL not healthy — the backend may fail to connect"
        return 0
    fi

    # Native mode (default): PostgreSQL 16 on :5432.
    # Resolve pg_isready across platforms: Linux/WSL2 packages put it in PATH,
    # Homebrew keeps it inside the keg.
    PG_READY="$(command -v pg_isready 2>/dev/null || true)"
    if [ -z "$PG_READY" ]; then
        for candidate in /usr/lib/postgresql/16/bin/pg_isready \
                         /opt/homebrew/opt/postgresql@16/bin/pg_isready \
                         /usr/local/opt/postgresql@16/bin/pg_isready; do
            if [ -x "$candidate" ]; then
                PG_READY="$candidate"
                break
            fi
        done
    fi
    if [ -n "$PG_READY" ] && "$PG_READY" -h 127.0.0.1 -p 5432 >/dev/null 2>&1; then
        echo "  ✅ PostgreSQL already running on :5432"
        return 0
    fi

    # Start it the way this OS does. Each attempt is `|| true` so a missing
    # service manager (or a sudo password prompt) can never abort the script
    # via `set -e` — the readiness loop below reports the real outcome.
    case "$(uname -s)" in
        Linux)
            # WSL2 / Ubuntu: a system service, not Homebrew.
            echo "  Starting PostgreSQL via service (postgresql)..."
            sudo service postgresql start >/dev/null 2>&1 \
                || sudo systemctl start postgresql >/dev/null 2>&1 \
                || true
            ;;
        *)
            echo "  Starting PostgreSQL via brew services (postgresql@16)..."
            brew services start postgresql@16 >/dev/null 2>&1 || true
            ;;
    esac

    for _ in 1 2 3 4 5; do
        if [ -n "$PG_READY" ] && "$PG_READY" -h 127.0.0.1 -p 5432 >/dev/null 2>&1; then
            echo "  ✅ PostgreSQL ready on :5432"
            return 0
        fi
        sleep 2
    done
    echo "  ⚠️  PostgreSQL not ready on :5432 — start it manually, then re-run:"
    case "$(uname -s)" in
        Linux) echo "        sudo service postgresql start   (or: sudo systemctl start postgresql)" ;;
        *)     echo "        brew services start postgresql@16" ;;
    esac
}

start_backend() {
    echo "── Backend ──────────────────────────────"
    kill_old "backend" 8765 "$BE_PIDFILE"
    # The root .env is the single source of truth for API keys. Unset provider
    # key vars that may be exported in the shell so a stale value can't
    # silently override .env (pydantic-settings prefers os.environ).
    unset GOOGLE_API_KEY GEMINI_API_KEY OPENAI_API_KEY ANTHROPIC_API_KEY \
          DEEPSEEK_API_KEY MINIMAX_API_KEY AGNES_API_KEY TAVILY_API_KEY \
          SERPER_API_KEY 2>/dev/null || true
    echo "  Starting backend..."
    cd "$BE_DIR"
    # Worker count. DEFAULT IS 1 — deliberately.
    #
    # The Graph activity (code-defined LangGraph assistants) keeps its threads,
    # runs and checkpointers in PROCESS MEMORY. With more than one uvicorn
    # worker those registries are per-process, so a request for a thread can
    # land on a worker that has never seen it ("unknown thread"), and a
    # human-in-the-loop pause and its resume can end up in different processes.
    # Measured with 2 workers: 4 of 6 requests for the same thread failed.
    #
    # 1 worker is enough for concurrency here because the SSE endpoints are
    # async (they await the graph stream rather than blocking the event loop).
    # Raise it only if you accept degraded Graph-activity behaviour:
    #     UVICORN_WORKERS=2 ./start.sh
    #
    # Reload is disabled: uvicorn's --reload and --workers are mutually
    # exclusive, and the reloader has wedged the worker before. Restart via
    # start.sh to pick up code changes (project rule).
    WORKERS="${UVICORN_WORKERS:-1}"
    # `python -m uvicorn`, not `.venv/bin/uvicorn`. A console script carries its
    # interpreter as an absolute path on line 1, so a venv that was copied from
    # another machine, or whose uv-managed Python has since been replaced, fails
    # with "cannot execute: required file not found" — while `.venv/bin/python`
    # itself still works, which makes it look like uvicorn is missing. Going
    # through the module sidesteps the shebang entirely.
    SKIP_STARTUP_API_TEST=true .venv/bin/python -m uvicorn main:app --host 0.0.0.0 --port 8765 --workers "$WORKERS" &
    echo $! > "$BE_PIDFILE"
    echo "  Backend PID: $(cat "$BE_PIDFILE") (workers=$WORKERS)"
    if [ "$WORKERS" != "1" ]; then
        echo "  ⚠️  workers=$WORKERS — the Graph activity keeps threads in memory;"
        echo "      HITL resume and thread lookups can hit the wrong process."
    fi
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
    # FRONTEND=preview serves the built bundle from dist/ instead of running the
    # dev server, which transforms modules on demand — markedly faster to load,
    # and markedly faster still on WSL, where each file read crosses into the
    # Windows filesystem. It needs `npm run build` first (and again after any
    # pull that touches the frontend); without dist/ the preview server starts
    # and immediately exits, which is why the check below reports honestly.
    if [ "${FRONTEND:-dev}" = "preview" ]; then
        if [ ! -d "$FE_DIR/dist" ]; then
            echo "  ✗ FRONTEND=preview needs a build first:  cd $FE_DIR && npm run build"
            return 1
        fi
        echo "  Starting frontend (preview — built bundle from dist/)..."
        cd "$FE_DIR"
        npm run preview &
    else
        echo "  Starting frontend (dev server)..."
        cd "$FE_DIR"
        npm run dev &
    fi
    echo $! > "$FE_PIDFILE"
    echo "  Frontend PID: $(cat "$FE_PIDFILE")"
    sleep 4
    # Vite binds to ::1 (IPv6 loopback) on macOS, so check `localhost`, not 127.0.0.1
    if curl -sf http://localhost:1421/ >/dev/null 2>&1; then
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
