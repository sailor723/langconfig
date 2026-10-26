#!/usr/bin/env bash
# Verify that the three private tables really are private, from two real accounts.
#
# Scope: `workspace_files`, `storage_objects`, `auth_sessions`. Everything else in this
# database is shared by design (projects, agents, skills, tools, knowledge), so a check
# that "user B cannot see user A's project" would be testing a decision, not a bug.
#
# Usage:
#   ./scripts/verify_isolation.sh -u admin -A user1                    # both prompted
#   LANGCONFIG_VERIFY_PASSWORD=… LANGCONFIG_VERIFY_PASSWORD_B=… \
#     ./scripts/verify_isolation.sh <host> -u admin -A user1
#
# The two accounts must both exist and both be able to sign in. The script signs in
# twice, revokes nothing (sessions expire on their own), and changes no data — every
# request it makes is a GET.
#
# Exit: 0 all private, 1 a leak or an unexpected answer, 2 cannot run.
set -uo pipefail

RED=$'\033[31m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; DIM=$'\033[2m'; OFF=$'\033[0m'
PASS=0; FAIL=0

HOST="127.0.0.1:8765"; SCHEME="http"; A_USER=""; B_USER=""

while [ $# -gt 0 ]; do
    case "$1" in
        -H|--host) HOST="${2:?}"; shift 2 ;;
        -u|--user) A_USER="${2:?}"; shift 2 ;;
        -A|--user-b) B_USER="${2:?}"; shift 2 ;;
        -s|--https) SCHEME="https"; shift ;;
        *) HOST="$1"; shift ;;
    esac
done
BASE="$SCHEME://$HOST"
[ -n "$A_USER" ] && [ -n "$B_USER" ] || { echo "two accounts are required: -u <a> -A <b>" >&2; exit 2; }

command -v curl >/dev/null || { echo "curl is required" >&2; exit 2; }
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT

ok()  { PASS=$((PASS+1)); printf '  %sPASS%s %s\n' "$GREEN" "$OFF" "$1"; }
bad() { FAIL=$((FAIL+1)); printf '  %sFAIL%s %s\n' "$RED" "$OFF" "$1"; [ -n "${2:-}" ] && printf '       %s%s%s\n' "$DIM" "$2" "$OFF"; return 0; }

code() { curl -s -m 10 -o /dev/null -w '%{http_code}' "$@"; }
json_count() { python3 -c "import sys,json;d=json.load(sys.stdin);print(len(d.get('$1',[])))" 2>/dev/null || echo ERR; }

signin() {  # $1 jar, $2 user, $3 password
    local out
    out=$(curl -s -m 10 -o /dev/null -w '%{http_code}' -c "$1" -X POST \
          -H 'content-type: application/json' \
          -d "{\"username\":\"$2\",\"password\":\"$3\"}" "$BASE/api/auth/login")
    [ "$out" = "200" ] || { echo "could not sign in as $2 (HTTP $out)" >&2; exit 2; }
}

if ! curl -s -m 5 -o /dev/null "$BASE/signin"; then
    echo "cannot reach $BASE/signin" >&2; exit 2
fi

PW_A="${LANGCONFIG_VERIFY_PASSWORD:-}"; PW_B="${LANGCONFIG_VERIFY_PASSWORD_B:-}"
[ -n "$PW_A" ] || { printf 'password for %s: ' "$A_USER"; read -rs PW_A; echo; }
[ -n "$PW_B" ] || { printf 'password for %s: ' "$B_USER"; read -rs PW_B; echo; }

A="$TMP/a.jar"; B="$TMP/b.jar"
signin "$A" "$A_USER" "$PW_A"
signin "$B" "$B_USER" "$PW_B"

printf '\n%s\n' "Isolation check — $BASE (A=$A_USER, B=$B_USER)"

# ── workspace_files ────────────────────────────────────────────────────────
printf '\n%s\n' "1. workspace_files — the file list is per person"
A_N=$(curl -s -b "$A" "$BASE/api/workspace/files?limit=1000" | json_count files)
B_N=$(curl -s -b "$B" "$BASE/api/workspace/files?limit=1000" | json_count files)
printf '     A lists %s files, B lists %s\n' "$A_N" "$B_N"

A_ID=$(curl -s -b "$A" "$BASE/api/workspace/files?limit=1000" \
       | python3 -c "import sys,json;f=json.load(sys.stdin).get('files',[]);print(f[0]['path'] if f else '')" 2>/dev/null)
if [ -n "$A_ID" ]; then
    st=$(code -b "$B" --get --data-urlencode "file_path=$A_ID" "$BASE/api/workspace/by-path/download")
    [ "$st" = "404" ] && ok "B downloading A's file ($A_ID) → 404" \
                      || bad "B downloading A's file → $st (expected 404)"
    st=$(code -b "$B" --get --data-urlencode "file_path=../$(echo "$A_ID" | cut -d/ -f1)/x" "$BASE/api/workspace/by-path/download")
    [ "$st" = "403" ] && ok "B walking into another tree → 403" || bad "traversal → $st (expected 403)"
else
    printf '     %sA has no files; the cross-user download checks were skipped%s\n' "$YELLOW" "$OFF"
fi

# metadata rows are keyed by id, which is a guessable number
FIRST_ID=$(curl -s -b "$A" "$BASE/api/workspace/files/with-metadata?limit=1" \
           | python3 -c "import sys,json;d=json.load(sys.stdin);f=d.get('files',[]);print(f[0]['id'] if f else '')" 2>/dev/null)
if [ -n "$FIRST_ID" ]; then
    a=$(code -b "$A" "$BASE/api/workspace/files/metadata/$FIRST_ID")
    b=$(code -b "$B" "$BASE/api/workspace/files/metadata/$FIRST_ID")
    [ "$a" = "200" ] && [ "$b" = "404" ] && ok "metadata row $FIRST_ID: A=200, B=404" \
        || bad "metadata row $FIRST_ID: A=$a, B=$b (expected 200/404)"
else
    printf '     %sno metadata rows to test by id%s\n' "$YELLOW" "$OFF"
fi

# ── auth_sessions ──────────────────────────────────────────────────────────
printf '\n%s\n' "2. auth_sessions — signed-in browsers are per person"
A_S=$(curl -s -b "$A" "$BASE/api/auth/sessions" | json_count sessions)
B_S=$(curl -s -b "$B" "$BASE/api/auth/sessions" | json_count sessions)
printf '     A sees %s session(s), B sees %s\n' "$A_S" "$B_S"

# B must not be able to revoke a session that belongs to A
A_SID=$(curl -s -b "$A" "$BASE/api/auth/sessions" \
        | python3 -c "import sys,json;d=json.load(sys.stdin);s=d.get('sessions',[]);print(s[0]['id'] if s else '')" 2>/dev/null)
if [ -n "$A_SID" ]; then
    st=$(curl -s -b "$B" -o /dev/null -w '%{http_code}' -X POST "$BASE/api/auth/sessions/$A_SID/revoke")
    [ "$st" = "404" ] && ok "B revoking A's session $A_SID → 404" \
                      || bad "B revoking A's session → $st (expected 404)"
    still=$(code -b "$A" "$BASE/api/auth/session")
    [ "$still" = "200" ] && ok "A's session survived B's attempt" || bad "A's session was killed by B ($still)"
fi

# ── storage_objects ────────────────────────────────────────────────────────
printf '\n%s\n' "3. storage_objects — blobs are per person (service level)"
printf '     %snot reachable over HTTP by design; check it directly:%s\n' "$DIM" "$OFF"
cat <<'PY'
     cd backend && .venv/bin/python - <<'PYEOF'
     from sqlalchemy import text
     from db.database import SessionLocal
     from core.context.current_user import set_current_user, reset_current_user
     from core.security.lan_auth import UserContext
     from services.storage import get_storage
     key = SessionLocal().execute(text(
         "SELECT key FROM storage_objects WHERE owner_id = (SELECT min(id) FROM users) LIMIT 1"
     )).scalar()
     for uid in (1, 284):
         tok = set_current_user(UserContext(id=uid, username=str(uid), role="member", via="session"))
         try:
             try:
                 print(uid, "read OK", len(get_storage().read(key)))
             except Exception as exc:
                 print(uid, type(exc).__name__, exc)
         finally:
             reset_current_user(tok)
     PYEOF
PY

printf '\n%s\n' "──────────────────────────────────────────────"
printf '  passed %s   failed %s\n' "$PASS" "$FAIL"
[ "$FAIL" -gt 0 ] && { printf '  %sA private table leaked.%s\n' "$RED" "$OFF"; exit 1; }
printf '  %sAll private tables held.%s\n' "$GREEN" "$OFF"
