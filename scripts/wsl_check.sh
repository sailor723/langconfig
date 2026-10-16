#!/usr/bin/env bash
# LangConfig — WSL2 / native-Ubuntu PostgreSQL + seeding checker.
#
# READ-ONLY: inspects only, never writes to the database or .env.
#
# Usage (from the repo root, after copying the repo to WSL):
#     bash scripts/wsl_check.sh              # auto-detects repo root
#     bash scripts/wsl_check.sh /path/to/repo
#
# Exit code 0 = every CRITICAL check passed.
#
# Expected values below are the baseline from the working macOS reference
# install (Postgres 16.14, 48 tables, alembic 029_add_tool_definition).

set -u

ROOT="${1:-$PWD}"
if [ ! -f "$ROOT/.env" ] && [ -f "$ROOT/../.env" ]; then
  ROOT="$(cd "$ROOT/.." && pwd)"
fi
ROOT="$(cd "$ROOT" 2>/dev/null && pwd || echo "$ROOT")"

FAIL=0
WARN=0

ok()   { printf '  \033[32mOK\033[0m   %s\n' "$1"; }
bad()  { printf '  \033[31mFAIL\033[0m %s\n' "$1"; FAIL=$((FAIL+1)); }
warn() { printf '  \033[33mWARN\033[0m %s\n' "$1"; WARN=$((WARN+1)); }
info() { printf '       %s\n' "$1"; }
head_() { printf '\n\033[1m%s\033[0m\n' "$1"; }

# ---------------------------------------------------------------- 1. platform
head_ "[1/8] Platform"
if [ -f /proc/version ]; then
  info "$(cat /proc/version)"
  case "$(cat /proc/version)" in
    *icrosoft*|*WSL*) ok "running under WSL" ;;
    *)                warn "Linux, but not detected as WSL" ;;
  esac
else
  warn "no /proc/version — this does not look like Linux/WSL"
fi
if [ -r /etc/os-release ]; then
  . /etc/os-release
  info "distro: ${PRETTY_NAME:-unknown}"
fi

# --------------------------------------------------------------- 2. packages
head_ "[2/8] PostgreSQL packages"
if command -v psql >/dev/null 2>&1; then
  ok "psql present — $(psql --version)"
else
  bad "psql not found — sudo apt install -y postgresql-16 postgresql-16-pgvector"
fi

# start.sh needs one of these to find what is LISTENING on :1421/:8765 before it restarts a server.
# Not installed on a default WSL2 Ubuntu, and its absence is silent at the moment it matters: the
# port stays busy, Vite refuses to fall back to another port (strictPort: true), and the only clue
# is "Port 1421 is already in use". WARN rather than FAIL — a first run works without it.
if command -v lsof >/dev/null 2>&1; then
  ok "lsof present — start.sh can stop a previous server still holding :1421 or :8765"
elif command -v ss >/dev/null 2>&1; then
  warn "lsof missing; start.sh falls back to ss (works, but cannot name other users' processes)"
  info "recommended: sudo apt install -y lsof"
else
  warn "no lsof and no ss — start.sh cannot tell whether a port is free, so a re-run can fail"
  info "with: Port 1421 is already in use     fix: sudo apt install -y lsof"
fi

if command -v dpkg >/dev/null 2>&1; then
  if dpkg -l 2>/dev/null | grep -q '^ii  *postgresql-16 '; then
    ok "postgresql-16 server package installed"
  else
    bad "postgresql-16 server package missing (apt install postgresql-16)"
  fi
  if dpkg -l 2>/dev/null | grep -q '^ii  *postgresql-16-pgvector'; then
    ok "postgresql-16-pgvector installed"
  else
    bad "postgresql-16-pgvector missing — REQUIRED for embeddings (RAG breaks without it)"
  fi
else
  warn "dpkg unavailable — skipping package checks"
fi

# ---------------------------------------------------------------- 3. service
head_ "[3/8] Service + port 5432"
if command -v pg_isready >/dev/null 2>&1; then
  if pg_isready -h localhost -p 5432 >/dev/null 2>&1; then
    ok "pg_isready: accepting connections on localhost:5432"
  else
    bad "PostgreSQL not accepting connections on :5432 — sudo service postgresql start"
  fi
fi
LISTEN="$( (ss -ltn 2>/dev/null || netstat -ltn 2>/dev/null) | grep -E '[.:]5432\b' | head -3 )"
if [ -n "$LISTEN" ]; then
  ok "something is listening on 5432"
  printf '%s\n' "$LISTEN" | while read -r l; do info "$l"; done
else
  bad "nothing listening on 5432"
fi
if (ss -ltn 2>/dev/null || true) | grep -qE '[.:]5433\b'; then
  warn "port 5433 also in use — looks like a docker Postgres is still running; make sure .env matches the one you intend"
fi

# ------------------------------------------------------------------- 4. .env
head_ "[4/8] .env"
ENV_FILE="$ROOT/.env"
if [ ! -f "$ENV_FILE" ]; then
  bad ".env missing at $ENV_FILE — cp env_example .env  (do this BEFORE starting/seeding)"
  PGHOST=localhost; PGPORT=5432; PGDATABASE=langconfig; PGUSER=langconfig; PGPASSWORD=""
else
  ok ".env found: $ENV_FILE"
  get() { grep -E "^$1=" "$ENV_FILE" 2>/dev/null | head -1 | cut -d= -f2- | tr -d '"'"'"'\r'; }
  PGHOST="$(get POSTGRES_HOST)";     PGHOST="${PGHOST:-localhost}"
  PGPORT="$(get POSTGRES_PORT)";     PGPORT="${PGPORT:-5432}"
  PGDATABASE="$(get POSTGRES_DB)";   PGDATABASE="${PGDATABASE:-langconfig}"
  PGUSER="$(get POSTGRES_USER)";     PGUSER="${PGUSER:-langconfig}"
  PGPASSWORD="$(get POSTGRES_PASSWORD)"
  info "POSTGRES_HOST=$PGHOST  POSTGRES_PORT=$PGPORT  POSTGRES_DB=$PGDATABASE  POSTGRES_USER=$PGUSER"
  [ "$PGPORT" = "5432" ] && ok "POSTGRES_PORT=5432 (correct for native WSL)" \
                         || warn "POSTGRES_PORT=$PGPORT — native Postgres listens on 5432; 5433 is the docker default"
  [ "$PGDATABASE" = "langconfig" ] && ok "POSTGRES_DB=langconfig" || warn "POSTGRES_DB=$PGDATABASE (expected langconfig)"
  [ "$PGUSER" = "langconfig" ] && ok "POSTGRES_USER=langconfig" || warn "POSTGRES_USER=$PGUSER (expected langconfig)"
  [ -n "$PGPASSWORD" ] && ok "POSTGRES_PASSWORD is set" || bad "POSTGRES_PASSWORD empty in .env"
  if grep -qE '^[A-Z_]*WORKSPACE_ROOT=.*(/Users/|/Volumes/)' "$ENV_FILE"; then
    bad "WORKSPACE_ROOT/PATH in .env contains a macOS path (/Users/...) — use \$HOME/... on WSL"
  fi
fi
export PGPASSWORD

PSQL="psql -h $PGHOST -p $PGPORT -U $PGUSER -d $PGDATABASE -tA -X -q"
run() { $PSQL -c "$1" 2>&1; }

# ------------------------------------------------------------- 5. connectivity
head_ "[5/8] Connectivity + role"
ONE="$(run 'SELECT 1' | tr -d '[:space:]')"
if [ "$ONE" = "1" ]; then
  ok "connected as '$PGUSER' to '$PGDATABASE' on $PGHOST:$PGPORT"
else
  bad "cannot connect as '$PGUSER' to '$PGDATABASE' — not seeded yet, or wrong role/password"
  info "$(run 'SELECT 1' | head -2)"
fi

SUDO=""
if sudo -n true >/dev/null 2>&1; then
  SUDO="sudo -n"
elif [ -t 0 ]; then
  SUDO="sudo"   # will prompt for your password
fi
if [ -n "$SUDO" ]; then
  ROLEDEF="$($SUDO -u postgres psql -tA -X -q -c "SELECT rolcreatedb||'|'||rolsuper FROM pg_roles WHERE rolname='$PGUSER'" 2>/dev/null)"
  if [ -n "$ROLEDEF" ]; then
    ok "role '$PGUSER' exists (CREATEDB=${ROLEDEF%%|*}, SUPERUSER=${ROLEDEF##*|})"
    [ "${ROLEDEF%%|*}" = "t" ] || bad "role lacks CREATEDB — seed step 1/10 needs it"
    [ "${ROLEDEF##*|}" = "t" ] || bad "role lacks SUPERUSER — CREATE EXTENSION vector needs it"
  else
    warn "could not read role attributes (needs: sudo -u postgres psql)"
  fi
  DBS="$($SUDO -u postgres psql -tA -X -q -c "SELECT datname FROM pg_database WHERE datistemplate=false ORDER BY datname" 2>/dev/null | tr '\n' ' ')"
  [ -n "$DBS" ] && info "databases: $DBS"
  case "$DBS" in *langconfig*) ok "database 'langconfig' exists" ;; *) bad "database 'langconfig' missing" ;; esac
  case "$DBS" in *chinook*) ok "sample database 'chinook' exists (seed step 10)" ;; *) warn "no 'chinook' database — seed step 10 is best-effort" ;; esac
  case "$DBS" in *langconfig_test*) ok "test database 'langconfig_test' exists" ;; *) info "no 'langconfig_test' (optional, needed only for pytest)" ;; esac
else
  warn "no passwordless sudo — skipping role/database checks (run manually: sudo -u postgres psql)"
fi

# ---------------------------------------------------------------- 6. schema
head_ "[6/8] Schema + migrations"
TABLES="$(run "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'" | tr -d '[:space:]')"
if [ "$TABLES" = "48" ]; then
  ok "48 tables in public (expected 48)"
elif [ -n "$TABLES" ] && [ "$TABLES" -gt 0 ] 2>/dev/null; then
  warn "table count = $TABLES (expected 48) — fine if a slightly different revision, else re-run seed"
else
  bad "no tables found — run the seed: cd backend && uv run python scripts/seeds/seed_all.py"
fi

REV="$(run 'SELECT version_num FROM alembic_version LIMIT 1' | tr -d '[:space:]')"
case "$REV" in
  029_add_tool_definition) ok "alembic_version = $REV (matches repo head)" ;;
  "")                      bad "alembic_version empty — migrations not stamped (seed step 3)" ;;
  *)                       warn "alembic_version = $REV (repo head is 029_add_tool_definition)" ;;
esac

VEC="$(run "SELECT extversion FROM pg_extension WHERE extname='vector'" | tr -d '[:space:]')"
if [ -n "$VEC" ]; then
  ok "pgvector extension enabled (vector $VEC)"
else
  bad "pgvector extension NOT enabled in '$PGDATABASE' — RAG/embeddings will fail (needs SUPERUSER role)"
fi

# ----------------------------------------------------------------- 7. seeds
head_ "[7/8] Seeded data"
for pair in \
  "settings_documents:7" \
  "models:28" \
  "custom_tools:67" \
  "deep_agent_templates:51" \
  "skills:37"
do
  TBL="${pair%%:*}"; EXP="${pair##*:}"
  N="$(run "SELECT count(*) FROM $TBL" 2>/dev/null | tr -d '[:space:]')"
  if [ -z "$N" ] || ! printf '%s' "$N" | grep -qE '^[0-9]+$'; then
    bad "$TBL: table missing or unreadable — seed incomplete"
  elif [ "$N" = "0" ]; then
    bad "$TBL: 0 rows — seed incomplete"
  elif [ "$N" = "$EXP" ]; then
    ok "$TBL: $N rows (== expected $EXP)"
  else
    warn "$TBL: $N rows (reference install had $EXP — usually fine)"
  fi
done

CH="$(psql -h "$PGHOST" -p "$PGPORT" -U "$PGUSER" -d chinook -tA -X -q -c "SELECT count(*) FROM information_schema.tables WHERE table_schema='public'" 2>/dev/null | tr -d '[:space:]')"
if [ -n "$CH" ] && [ "$CH" -gt 0 ] 2>/dev/null; then
  ok "chinook: $CH tables (Graph Studio sample, expected 11)"
else
  warn "chinook database empty/absent — seed step 10 is best-effort (re-run seed_all.py to retry)"
fi

# ------------------------------------------------------------- 8. app side
head_ "[8/8] Backend readiness (informational)"
if [ -d "$ROOT/backend/.venv" ]; then
  PY="$ROOT/backend/.venv/bin/python"
  if [ -x "$PY" ]; then
    ok "backend venv present — $("$PY" --version 2>&1)"
  else
    warn "backend/.venv exists but no python binary — rm -rf backend/.venv && (cd backend && uv sync)"
  fi
else
  warn "backend/.venv missing — run: cd backend && uv sync  (required BEFORE seeding)"
fi
command -v uv >/dev/null 2>&1 && ok "uv present — $(uv --version 2>&1)" || warn "uv not found — install from https://astral.sh/uv"

# ------------------------------------------------------------------ summary
head_ "SUMMARY"
if [ "$FAIL" -eq 0 ]; then
  printf '  \033[32mALL CRITICAL CHECKS PASSED\033[0m  (%d warning(s))\n' "$WARN"
  info "next: cd backend && uv run python scripts/seeds/seed_all.py   # if counts above were short"
  info "then: bash start.sh --be  &&  bash scripts/health_check.sh"
  exit 0
else
  printf '  \033[31m%d CRITICAL CHECK(S) FAILED\033[0m  (%d warning(s))\n' "$FAIL" "$WARN"
  info "paste this whole output back for diagnosis"
  exit 1
fi
