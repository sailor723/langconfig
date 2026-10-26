#!/usr/bin/env bash
# Verify "multi-user, single tenant": what must be private is private, what must be shared
# is shared. One command, two accounts, exit code you can put in a deploy script.
#
# This is the counterpart to verify_auth.sh (can people get in?) and
# verify_isolation.sh (can they reach each other's files?). It answers the product
# question: one install, several people, each with their own front door and their own
# working set — while projects, agents, tools and knowledge stay shared on purpose.
#
# Usage:
#   ./scripts/verify_tenant.sh <host> -u admin -A user1
#   LANGCONFIG_VERIFY_PASSWORD=… LANGCONFIG_VERIFY_PASSWORD_B=… ./scripts/verify_tenant.sh
#
# Exit: 0 everything checked out, 1 a boundary failed, 2 cannot run.
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
[ -n "$A_USER" ] && [ -n "$B_USER" ] || { echo "two accounts required: -u <a> -A <b>" >&2; exit 2; }
command -v curl >/dev/null || { echo "curl required" >&2; exit 2; }

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
A="$TMP/a.jar"; B="$TMP/b.jar"

ok()   { PASS=$((PASS+1)); printf '  %sPASS%s %s\n' "$GREEN" "$OFF" "$1"; }
bad()  { FAIL=$((FAIL+1)); printf '  %sFAIL%s %s\n' "$RED" "$OFF" "$1"; [ -n "${2:-}" ] && printf '       %s%s%s\n' "$DIM" "$2" "$OFF"; return 0; }
head_() { printf '\n%s\n' "$1"; }
count() { python3 -c "import sys,json;d=json.load(sys.stdin);print(len(d if isinstance(d,list) else d.get('$1',[])))" 2>/dev/null || echo ERR; }
code()  { curl -s -m 10 -o /dev/null -w '%{http_code}' "$@"; }

signin() {
    local jar="$1" user="$2" pw="$3" st
    st=$(curl -s -m 10 -o /dev/null -w '%{http_code}' -c "$jar" -X POST \
         -H 'content-type: application/json' \
         -d "{\"username\":\"$user\",\"password\":\"$pw\"}" "$BASE/api/auth/login")
    [ "$st" = "200" ] || { echo "cannot sign in as $user (HTTP $st)" >&2; exit 2; }
}

curl -s -m 5 -o /dev/null "$BASE/signin" || { echo "cannot reach $BASE" >&2; exit 2; }
PW_A="${LANGCONFIG_VERIFY_PASSWORD:-}"; PW_B="${LANGCONFIG_VERIFY_PASSWORD_B:-}"
[ -n "$PW_A" ] || { printf 'password for %s: ' "$A_USER"; read -rs PW_A; echo; }
[ -n "$PW_B" ] || { printf 'password for %s: ' "$B_USER"; read -rs PW_B; echo; }
signin "$A" "$A_USER" "$PW_A"
signin "$B" "$B_USER" "$PW_B"

printf '\n%s\n' "Multi-user / single tenant — $BASE   (A=$A_USER, B=$B_USER)"

# ── 1. identity ────────────────────────────────────────────────────────────
head_ "1. Each account is itself"
for pair in "$A:$A_USER" "$B:$B_USER"; do
    jar="${pair%%:*}"; user="${pair##*:}"
    got=$(curl -s -b "$jar" "$BASE/api/users/me" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('username'),d.get('via'))" 2>/dev/null)
    case "$got" in
        "$user session") ok "$user resolves to its own account (via session)";;
        "$user loopback") ok "$user resolves to itself (via loopback — same machine)";;
        *) bad "$user resolves to '$got'";;
    esac
done
st=$(code -b "$B" "$BASE/api/users")
[ "$st" = "403" ] && ok "member cannot list accounts (403)" || bad "member listing accounts → $st (expected 403)"

# ── 2. private: files ──────────────────────────────────────────────────────
head_ "2. Private — files"
A_N=$(curl -s -b "$A" "$BASE/api/workspace/files?limit=1000" | count files)
B_N=$(curl -s -b "$B" "$BASE/api/workspace/files?limit=1000" | count files)
printf '     A sees %s file(s), B sees %s\n' "$A_N" "$B_N"
[ "$A_N" != "$B_N" ] && ok "file lists differ per account" || printf '     %sboth empty or identical — check on a populated install%s\n' "$YELLOW" "$OFF"
FIRST=$(curl -s -b "$A" "$BASE/api/workspace/files?limit=1000" | python3 -c "import sys,json;f=json.load(sys.stdin).get('files',[]);print(f[0].get('path','') if f else '')" 2>/dev/null)
if [ -n "$FIRST" ]; then
    st=$(code -b "$B" --get --data-urlencode "file_path=$FIRST" "$BASE/api/workspace/by-path/download")
    [ "$st" = "404" ] && ok "B cannot download A's file ($FIRST)" || bad "B downloading A's file → $st"
fi

# ── 3. private: conversations ──────────────────────────────────────────────
head_ "3. Private — conversations"
A_S=$(curl -s -b "$A" "$BASE/api/chat/sessions?limit=500" | count sessions)
B_S=$(curl -s -b "$B" "$BASE/api/chat/sessions?limit=500" | count sessions)
printf '     A has %s conversation(s), B has %s\n' "$A_S" "$B_S"
[ "$A_S" != "$B_S" ] && ok "conversation lists differ per account" || bad "both accounts list $A_S conversation(s)"
SID=$(curl -s -b "$A" "$BASE/api/chat/sessions?limit=1" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d[0]['session_id'] if d else '')" 2>/dev/null)
if [ -n "$SID" ]; then
    a=$(code -b "$A" "$BASE/api/chat/$SID/history")
    b=$(code -b "$B" "$BASE/api/chat/$SID/history")
    [ "$a" = "200" ] && [ "$b" = "404" ] && ok "A's transcript: A=200, B=404" || bad "A's transcript: A=$a, B=$b (expected 200/404)"
fi

# ── 4. private: personal skills ────────────────────────────────────────────
head_ "4. Private — personal skills (built-ins stay system-wide)"
A_K=$(curl -s -b "$A" "$BASE/api/skills" | count "")
B_K=$(curl -s -b "$B" "$BASE/api/skills" | count "")
A_B=$(curl -s -b "$A" "$BASE/api/skills?source_type=builtin" | count "")
B_B=$(curl -s -b "$B" "$BASE/api/skills?source_type=builtin" | count "")
A_P=$(curl -s -b "$A" "$BASE/api/skills?source_type=personal" | count "")
B_P=$(curl -s -b "$B" "$BASE/api/skills?source_type=personal" | count "")
printf '     A: %s total (%s builtin + %s personal)   B: %s total (%s builtin + %s personal)\n' \
    "$A_K" "$A_B" "$A_P" "$B_K" "$B_B" "$B_P"
[ "$A_B" = "$B_B" ] && ok "built-in skills are shared ($A_B = $B_B)" || bad "built-in counts differ: A=$A_B B=$B_B"
[ "$A_P" != "$B_P" ] && ok "personal skills are per account ($A_P vs $B_P)" || bad "personal skill counts identical: $A_P"

# ── 5. shared by design ────────────────────────────────────────────────────
head_ "5. Shared by design — one tenant"
# The trailing slash matters (`/api/deepagents` is a 404 while `/api/deepagents/` lists),
# and `project_id` is required by the RAG listing — both cost me a "0 = 0" pass that proved
# nothing. Each row now also asserts the count is non-zero, so an empty answer fails loudly
# instead of passing as "identical".
for spec in "api/projects/:" "api/deepagents/:" "api/tools/registry:" \
            "api/rag/documents:?project_id=1" "api/users/roles:__admin_only"; do
    path="${spec%%:*}"; query="${spec#*:}"
    if [ "$query" = "__admin_only" ]; then continue; fi
    a=$(curl -s -b "$A" "$BASE/$path$query" | count "")
    b=$(curl -s -b "$B" "$BASE/$path$query" | count "")
    if [ "$a" = "ERR" ] || [ "$b" = "ERR" ]; then
        bad "${path%/}: one side did not answer with a list"
    elif [ "$a" = "0" ] || [ "$b" = "0" ]; then
        bad "${path%/}: A=$a B=$b — zero proves nothing, check the endpoint"
    elif [ "$a" = "$b" ]; then
        ok "both see the same ${path%/}$query ($a)"
    else
        bad "${path%/}: A=$a B=$b (expected identical — this is shared by design)"
    fi
done

printf '\n%s\n' "──────────────────────────────────────────────"
printf '  passed %s   failed %s\n' "$PASS" "$FAIL"
[ "$FAIL" -gt 0 ] && { printf '  %sA boundary is wrong — see above.%s\n' "$RED" "$OFF"; exit 1; }
printf '  %sMulti-user, one tenant: verified.%s\n' "$GREEN" "$OFF"
