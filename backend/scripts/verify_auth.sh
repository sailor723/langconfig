#!/usr/bin/env bash
# Verify the sign-in / sign-out stack on a running LangConfig instance.
#
# Why a script: the browser flow is the part that broke, and the failure ("page
# keeps refreshing") looked like a frontend bug while it was a proxy + cookie +
# redirect interaction. A curl walk-through of the same sequence catches every
# layer except the browser's own scrollbar, runs in a second, and can be pointed at
# each host after a deploy.
#
# Usage:
#   ./scripts/verify_auth.sh                                  # this machine (127.0.0.1:8765)
#   ./scripts/verify_auth.sh 192.168.3.23:8765                # another host
#   ./scripts/verify_auth.sh -H 192.168.3.23:8765 -u admin    # with an account
#
# The account defaults to $LANGCONFIG_VERIFY_USER, else you are prompted. The
# password is never taken from argv (it would land in the shell history and in
# `ps`); use the prompt or LANGCONFIG_VERIFY_PASSWORD.
#
# Exit codes: 0 all checks passed, 1 a check failed, 2 cannot run (no curl, no
# account, host unreachable).
set -uo pipefail

RED=$'\033[31m'; GREEN=$'\033[32m'; YELLOW=$'\033[33m'; DIM=$'\033[2m'; OFF=$'\033[0m'
PASS=0; FAIL=0; SKIP=0

HOST="127.0.0.1:8765"
SCHEME="http"
USER_NAME="${LANGCONFIG_VERIFY_USER:-}"
PASSWORD_SET="${LANGCONFIG_VERIFY_PASSWORD:+1}"

usage() { sed -n '2,22p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }

while [ $# -gt 0 ]; do
    case "$1" in
        -H|--host) HOST="${2:?host required}"; shift 2 ;;
        -u|--user) USER_NAME="${2:?user required}"; shift 2 ;;
        -s|--https) SCHEME="https"; shift ;;
        -h|--help) usage 0 ;;
        *) HOST="$1"; shift ;;
    esac
done
BASE="$SCHEME://$HOST"

# Loopback (and only loopback) resolves to the install's owner with no credential at
# all — that is what keeps local development password-free. So a handful of checks
# have a different correct answer when this script runs ON the server.
case "${HOST%%:*}" in
    127.0.0.1|localhost|::1|"[::1]") LOOPBACK=1 ;;
    *) LOOPBACK=0 ;;
esac

command -v curl >/dev/null 2>&1 || { echo "curl is required" >&2; exit 2; }

TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
JAR="$TMP/cookies.txt"

ok()   { PASS=$((PASS+1)); printf '  %sPASS%s %s\n' "$GREEN" "$OFF" "$1"; }
bad()  { FAIL=$((FAIL+1)); printf '  %sFAIL%s %s\n' "$RED" "$OFF" "$1"; [ -n "${2:-}" ] && printf '       %s%s%s\n' "$DIM" "$2" "$OFF"; return 0; }
note() { SKIP=$((SKIP+1)); printf '  %sSKIP%s %s\n' "$YELLOW" "$OFF" "$1"; }
head_() { printf '\n%s\n' "$1"; }

# code URL [curl args…] -> prints the status code
code() { local url="$1"; shift; curl -s -o /dev/null -m 10 -w '%{http_code}' "$@" "$url"; }
body() { local url="$1"; shift; curl -s -m 10 "$@" "$url"; }
header() { local url="$1" name="$2"; shift 2; curl -s -m 10 -D - -o /dev/null "$@" "$url" \
             | tr -d '\r' | awk -v n="$(echo "$name" | tr 'A-Z' 'a-z')" 'BEGIN{IGNORECASE=1} tolower($0) ~ "^"n":" {sub(/^[^:]*:[ ]*/,""); print}' | head -1; }

head_ "LangConfig auth verification — $BASE"
[ "$LOOPBACK" = "1" ] && printf '  %s(on the host itself: loopback resolves to the owner, so a few checks expect 200)%s\n' "$DIM" "$OFF"

# ── reachability ─────────────────────────────────────────────────────────────
if ! curl -s -m 5 -o /dev/null "$BASE/signin"; then
    printf '  %sFAIL%s cannot reach %s/signin\n' "$RED" "$OFF" "$BASE"
    echo "       Is the backend running? bash start.sh" >&2
    exit 2
fi

# ── 1. unauthenticated API is refused, without a Basic challenge ────────────
head_ "1. Unauthenticated access"

STATUS=$(code "$BASE/api/users/me")
if [ "$LOOPBACK" = "1" ]; then
    # Loopback is the owner: refusing here would break local development.
    [ "$STATUS" = "200" ] && ok "GET /api/users/me from loopback → 200 (this machine is the owner)" \
                          || bad "GET /api/users/me from loopback → $STATUS (expected 200: loopback is exempt)"
else
    [ "$STATUS" = "401" ] && ok "GET /api/users/me without credentials → 401" \
                          || bad "GET /api/users/me without credentials → $STATUS (expected 401)"
fi

CHALLENGE=$(header "$BASE/api/users/me" www-authenticate)
[ -z "$CHALLENGE" ] && ok "no WWW-Authenticate (the browser must not pop its own dialog)" \
                    || bad "unexpected Basic challenge: $CHALLENGE"

STATUS=$(code "$BASE/" -H 'accept: text/html')
LOCATION=$(header "$BASE/" location -H 'accept: text/html')
if [ "$LOOPBACK" = "1" ]; then
    [ "$STATUS" = "200" ] && ok "browser navigation to / from loopback → 200 (the app, no sign-in)" \
                          || bad "browser navigation to / from loopback → $STATUS (expected 200)"
elif [ "$STATUS" = "303" ] && [[ "$LOCATION" == /signin* ]]; then
    ok "browser navigation to / → 303 $LOCATION"
else
    bad "browser navigation to / → $STATUS (location: ${LOCATION:-none}); expected 303 /signin"
fi

PAGE=$(body "$BASE/signin")
if [[ "$PAGE" == *'name="password"'* && "$PAGE" == *'name="username"'* ]]; then
    ok "GET /signin renders the sign-in form"
else
    bad "GET /signin did not render a form (got ${#PAGE} bytes)"
fi
[[ "$PAGE" == *'id="root"'* ]] && bad "the sign-in page booted the SPA — /signin is not proxied to the backend"

# ── 2. sign in ──────────────────────────────────────────────────────────────
head_ "2. Sign in"

if [ -z "$USER_NAME" ]; then
    printf '  account to test with: '; read -r USER_NAME || true
fi
if [ -z "$USER_NAME" ]; then
    note "no account given — skipping the authenticated checks (-u <name>)"
else
    if [ -z "$PASSWORD_SET" ]; then
        printf '  password for %s: ' "$USER_NAME"; read -rs PASSWORD || true; echo
    else
        PASSWORD="$LANGCONFIG_VERIFY_PASSWORD"
    fi

    BAD_STATUS=$(code "$BASE/api/auth/login" -X POST -H 'content-type: application/json' \
        -d "{\"username\":\"$USER_NAME\",\"password\":\"definitely-wrong-$RANDOM\"}")
    [ "$BAD_STATUS" = "401" ] && ok "wrong password → 401" \
                              || bad "wrong password → $BAD_STATUS (expected 401; 429 means the rate limiter tripped, wait 5 min)"

    LOGIN_HEADERS=$(curl -s -m 10 -D - -o /dev/null -c "$JAR" -X POST \
        -H 'content-type: application/json' -H 'accept: text/html' \
        -d "{\"username\":\"$USER_NAME\",\"password\":\"$PASSWORD\"}" "$BASE/api/auth/login" | tr -d '\r')
    LOGIN_STATUS=$(printf '%s' "$LOGIN_HEADERS" | awk 'NR==1{print $2}')
    COOKIE_LINE=$(printf '%s' "$LOGIN_HEADERS" | grep -i '^set-cookie: langconfig_session' | head -1)

    if [ "$LOGIN_STATUS" = "303" ] || [ "$LOGIN_STATUS" = "200" ]; then
        ok "sign in with the right password → $LOGIN_STATUS"
    else
        bad "sign in → ${LOGIN_STATUS:-no response}"
    fi

    if [ -n "$COOKIE_LINE" ]; then
        ok "session cookie set"
        [[ "$COOKIE_LINE" == *[Hh]ttp[Oo]nly* ]] && ok "cookie is HttpOnly (not readable by page scripts)" \
                                                 || bad "session cookie is not HttpOnly"
        case "$COOKIE_LINE" in
            *Max-Age=0*) bad "cookie has Max-Age=0 (it would be deleted immediately)";;
        esac
    else
        bad "no langconfig_session cookie in the sign-in response"
    fi

    # ── 3. the cookie works ─────────────────────────────────────────────────
    head_ "3. Authenticated access"

    STATUS=$(code "$BASE/api/users/me" -b "$JAR")
    [ "$STATUS" = "200" ] && ok "GET /api/users/me with the session cookie → 200" \
                          || bad "GET /api/users/me with the session cookie → $STATUS"

    VIA=$(body "$BASE/api/users/me" -b "$JAR" | tr -d '\n' | sed -n 's/.*"via":"\([a-z]*\)".*/\1/p')
    case "$VIA" in
        session) ok "identity came from the session cookie (via=session)";;
        loopback) ok "identity is this machine's owner (via=loopback — expected on the host itself)";;
        "") bad "the /me response has no 'via' field (old backend build?)";;
        *) bad "unexpected via=$VIA";;
    esac

    WHO=$(body "$BASE/api/auth/session" -b "$JAR" | tr -d '\n' | sed -n 's/.*"username":"\([^"]*\)".*/\1/p')
    [ "$WHO" = "$USER_NAME" ] && ok "/api/auth/session reports the signed-in account" \
                              || bad "/api/auth/session reported '$WHO', expected '$USER_NAME'"

    STATUS=$(code "$BASE/" -b "$JAR" -H 'accept: text/html')
    [ "$STATUS" = "200" ] && ok "the app document loads with the cookie → 200" \
                          || bad "the app document → $STATUS (is dist/ built? npm run build)"
    if [ "$STATUS" = "200" ]; then
        html=$(body "$BASE/" -b "$JAR" -H 'accept: text/html')
        [[ "$html" == *'id="root"'* ]] && ok "the app shell is the SPA (built bundle served)" \
                                       || note "the document is not the SPA shell (JSON fallback?)"
    fi

    COUNT=$(body "$BASE/api/auth/sessions" -b "$JAR" | grep -o '"current":true' | wc -l | tr -d ' ')
    [ "$COUNT" = "1" ] && ok "GET /api/auth/sessions lists this browser as current" \
                       || bad "expected exactly one current session, found $COUNT"

    # ── 4. sign out revokes ────────────────────────────────────────────────
    head_ "4. Sign out"

    OUT_HEADERS=$(curl -s -m 10 -D - -o /dev/null -b "$JAR" -c "$JAR" "$BASE/api/auth/logout" | tr -d '\r')
    OUT_STATUS=$(printf '%s' "$OUT_HEADERS" | awk 'NR==1{print $2}')
    OUT_LOC=$(printf '%s' "$OUT_HEADERS" | grep -i '^location:' | head -1 | sed 's/^[^:]*:[ ]*//')
    if [ "$OUT_STATUS" = "303" ] && [[ "$OUT_LOC" == *signin* ]]; then
        ok "sign out → 303 $OUT_LOC"
    else
        bad "sign out → $OUT_STATUS (location: ${OUT_LOC:-none})"
    fi
    printf '%s' "$OUT_HEADERS" | grep -qi '^set-cookie: langconfig_signed_out' \
        && ok "sign-out marker set (covers a browser holding a cached Basic credential)" \
        || bad "sign-out marker missing"

    STATUS=$(code "$BASE/api/users/me" -b "$JAR")
    [ "$STATUS" = "401" ] && ok "the revoked cookie is refused → 401" \
                          || bad "the cookie still works after sign out → $STATUS"

    STATUS=$(code "$BASE/api/users/me")
    if [ "$LOOPBACK" = "1" ]; then
        ok "no cookie → 200 from loopback (the withdrawal is per browser; the machine stays the owner)"
    else
        [ "$STATUS" = "401" ] && ok "no cookie → 401 (the withdrawal is durable)" \
                              || bad "no cookie → $STATUS"
    fi

    # ── 5. scripts keep working ────────────────────────────────────────────
    head_ "5. Script access (HTTP Basic)"

    if [ -n "${PASSWORD:-}" ]; then
        STATUS=$(code "$BASE/api/users/me" -u "$USER_NAME:$PASSWORD")
        [ "$STATUS" = "200" ] && ok "curl -u $USER_NAME:… → 200 (scripts unaffected by the sign-in page)" \
                              || bad "Basic auth → $STATUS (expected 200)"
    fi
fi

# ── summary ─────────────────────────────────────────────────────────────────
printf '\n%s\n' "──────────────────────────────────────────────"
printf '  passed %s   failed %s   skipped %s\n' "$PASS" "$FAIL" "$SKIP"
if [ "$FAIL" -gt 0 ]; then
    printf '  %sSome checks failed.%s See docs/reference/lan-access.md §7.\n' "$RED" "$OFF"
    exit 1
fi
printf '  %sAll checks passed.%s\n' "$GREEN" "$OFF"
