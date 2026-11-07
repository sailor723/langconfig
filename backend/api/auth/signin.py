# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
The sign-in page — a separate UI, deliberately not part of the SPA.

Why it is not an SPA route (the usual choice): the app's own bundle sits behind the
gate, so an unauthenticated browser cannot render a React login screen without also
being served the entire application shell. A self-contained page has no such
dependency — it fills the window even when `dist/` is stale, and it cannot leak a
hundred components' worth of code to whoever can reach the port.

Why a dedicated session rather than the browser's Basic prompt: a form cannot set
Basic credentials, and Basic has no session, so there could be no expiry, no
remember-me, no "sign out this device". The password is verified once here, and the
browser gets an opaque cookie instead (`services/session_service.py`).

Flow:

* ``GET  /signin``            the page (with ``?next=`` kept through the form)
* ``POST /api/auth/login``    verify → create session → set cookie → redirect
* ``POST /api/auth/logout``   revoke the session → clear cookie → redirect to /signin
* ``GET  /api/auth/logout``   the same thing for a plain link
* ``GET  /api/auth/session``  who am I on this cookie (used by the shell)

Every failure answers with the page and a message, because a raw JSON 401 in front of
a human is a dead end.
"""

from __future__ import annotations

import html
import logging
import os
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from db.database import SessionLocal
from middleware.lan_guard import SIGNOUT_COOKIE
from services import session_service, user_service
from services.user_service import UserError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["auth"])

#: Cookie name. HttpOnly so no script can read it; SameSite=Lax so a cross-site
#: POST does not carry it (the CSRF mitigation for cookie auth on one origin).
SESSION_COOKIE = "langconfig_session"

SIGNIN_PATH = "/signin"

#: Failed sign-ins allowed per client address before a cool-off. scrypt plus the
#: verifier's negative cache already make guessing slow; this stops a script from
#: spending the server's CPU in a loop.
MAX_FAILURES = 10
FAILURE_WINDOW_SECONDS = 300

_failures: dict[str, list[float]] = {}


def _session_days() -> int:
    try:
        return max(1, int(os.getenv("LANGCONFIG_SESSION_DAYS", "7")))
    except ValueError:
        return 7


def _cookie_secure() -> bool:
    """TLS termination in front of the app is the only case where Secure is right.

    Plain-HTTP LAN installs would silently drop a Secure cookie, which reads as
    "the login page keeps coming back".
    """
    return os.getenv("LANGCONFIG_COOKIE_SECURE", "").strip().lower() in {"1", "true", "on", "yes"}


def _safe_next(raw: Optional[str]) -> str:
    """Only ever return to a path on this origin (an open redirect is a phishing gift)."""
    if not raw:
        return "/"
    value = raw.strip()
    if not value.startswith("/") or value.startswith("//") or "\\" in value:
        return "/"
    if value.startswith(SIGNIN_PATH):
        return "/"
    return value


# ── brute-force guard ───────────────────────────────────────────────────────

def _client_key(request: Request) -> str:
    client = getattr(request, "client", None)
    return client.host if client else "unknown"


def _too_many_failures(key: str) -> bool:
    import time

    now = time.monotonic()
    recent = [t for t in _failures.get(key, []) if now - t < FAILURE_WINDOW_SECONDS]
    _failures[key] = recent
    return len(recent) >= MAX_FAILURES


def _record_failure(key: str) -> None:
    import time

    _failures.setdefault(key, []).append(time.monotonic())


def _clear_failures(key: str) -> None:
    _failures.pop(key, None)


def reset_failure_state() -> None:
    """Test helper: the limiter is process state, so tests must be able to clear it."""
    _failures.clear()


# ── the page ────────────────────────────────────────────────────────────────

_STYLE = """
  *, *::before, *::after { box-sizing: border-box; }
  html, body { height: 100%; margin: 0; }
  body {
    background: #1a1a1a;
    color: #d4d4d4;
    font: 14px/1.6 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", sans-serif;
    display: flex; align-items: center; justify-content: center; padding: 24px;
  }
  .card {
    width: 100%; max-width: 380px;
    background: #252526; border: 1px solid #3c3c3c; border-radius: 12px;
    padding: 30px 28px 24px; box-shadow: 0 18px 48px rgba(0,0,0,0.45);
  }
  .mark {
    width: 40px; height: 40px; border-radius: 10px; background: #0e639c;
    display: flex; align-items: center; justify-content: center;
    font-weight: 700; font-size: 17px; color: #fff; margin-bottom: 16px;
  }
  h1 { font-size: 19px; font-weight: 600; color: #f5f5f5; margin: 0 0 6px; }
  .sub { color: #9a9a9a; font-size: 13px; margin: 0 0 22px; }
  label { display: block; font-size: 12px; font-weight: 600; color: #cfcfcf; margin-bottom: 6px; }
  input {
    width: 100%; height: 36px; padding: 0 11px; margin-bottom: 16px;
    background: #1e1e1e; color: #f0f0f0; border: 1px solid #3c3c3c; border-radius: 6px;
    font-size: 14px; outline: none;
  }
  input:focus { border-color: #0e639c; box-shadow: 0 0 0 2px rgba(14,99,156,0.35); }
  /* Password row: the reveal button sits inside the field, so the layout does not
     shift and nobody has to hunt for a separate control. */
  .pw { position: relative; }
  .pw input { padding-right: 42px; }
  .pw .toggle {
    position: absolute; right: 6px; top: 50%; transform: translateY(-50%);
    width: 30px; height: 28px; margin: 0; padding: 0; border: none; border-radius: 6px;
    display: flex; align-items: center; justify-content: center;
    background: transparent; color: #8a8a8a; cursor: pointer;
  }
  .pw .toggle:hover { color: #f0f0f0; background: rgba(255,255,255,0.08); }
  .pw .toggle:focus-visible { outline: 2px solid #0e639c; outline-offset: 1px; }
  .pw .toggle svg { width: 16px; height: 16px; fill: currentColor; }
  .pw .toggle .eye-off { display: none; }
  .pw .toggle[aria-pressed="true"] .eye { display: none; }
  .pw .toggle[aria-pressed="true"] .eye-off { display: block; }
  button {
    width: 100%; height: 36px; border: none; border-radius: 18px; cursor: pointer;
    background: #0e639c; color: #fff; font-size: 13px; font-weight: 600;
    margin-top: 4px;
  }
  button:hover { background: #1177bb; }
  button:disabled { opacity: 0.6; cursor: default; }
  .error {
    background: rgba(248,113,113,0.12); border: 1px solid rgba(248,113,113,0.5);
    color: #f87171; border-radius: 6px; padding: 8px 10px; font-size: 12.5px;
    margin-bottom: 16px;
  }
  .note { margin-top: 20px; font-size: 11.5px; color: #7a7a7a; line-height: 1.55; }
  .note strong { color: #9a9a9a; font-weight: 600; }
"""


#: The password eye toggle. Kept OUT of the f-string below so its braces stay
#: literal, and inline because this page runs no other script (no bundler, no CSP).
_PW_TOGGLE_SCRIPT = """  <script>
    /* Show/hide the password. Nothing else on this page runs a script, so this
       stays inline and tiny: toggling `type` keeps the value and the caret. */
    (function () {
      var btn = document.getElementById('pw-toggle');
      var field = document.getElementById('password');
      if (!btn || !field) return;
      function apply(show) {
        field.type = show ? 'text' : 'password';
        btn.setAttribute('aria-pressed', show ? 'true' : 'false');
        var label = show ? 'Hide password' : 'Show password';
        btn.setAttribute('aria-label', label);
        btn.setAttribute('title', label);
      }
      btn.addEventListener('click', function () {
        apply(field.type === 'password');
        field.focus();                 /* keep typing where you were */
      });
      /* Hold-to-peek would be nicer but a plain toggle is what people expect. */
      apply(false);
    })();
  </script>"""


def render_page(
    *,
    error: Optional[str] = None,
    next: str = "/",
    username: str = "",
    notice: Optional[str] = None,
) -> str:
    """The sign-in document. Every dynamic value is escaped."""
    error_html = f'<div class="error">{html.escape(error)}</div>' if error else ""
    notice_html = f'<div class="note">{notice}</div>' if notice else ""
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex">
<title>Sign in — LangConfig</title>
<style>{_STYLE}</style>
</head>
<body>
  <main class="card">
    <div class="mark">LC</div>
    <h1>Sign in to LangConfig</h1>
    <p class="sub">Use the account your administrator created for you.</p>
    {error_html}
    <form method="post" action="/api/auth/login" autocomplete="on">
      <input type="hidden" name="next" value="{html.escape(next)}">
      <label for="username">Username or nickname</label>
      <input id="username" name="username" value="{html.escape(username)}"
             autocapitalize="none" autocorrect="off" spellcheck="false"
             autocomplete="username" required autofocus
             aria-describedby="username-hint">
      <p class="sub" id="username-hint" style="margin:-6px 0 10px">
        Either works — a nickname is just an easier alias for the same account.
      </p>
      <label for="password">Password</label>
      <div class="pw">
        <input id="password" name="password" type="password"
               autocomplete="current-password" required>
        <!-- Reveal the typed password. Kept as a real button (not a hover trick):
             a mistyped password on a projector is the whole reason this exists,
             and the field must stay reachable from the keyboard. -->
        <button type="button" class="toggle" id="pw-toggle"
                aria-pressed="false" aria-label="Show password" title="Show password">
          <svg class="eye" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5C5.6 5 1.7 11.1 1.5 11.4a1 1 0 0 0 0 .9C1.7 12.9 5.6 19 12 19s10.3-6.1 10.5-6.4a1 1 0 0 0 0-.9C22.3 11.1 18.4 5 12 5zm0 12a5 5 0 1 1 0-10 5 5 0 0 1 0 10zm0-8a3 3 0 1 0 0 6 3 3 0 0 0 0-6z"/></svg>
          <svg class="eye-off" viewBox="0 0 24 24" aria-hidden="true"><path d="M12 5c-1.5 0-2.9.3-4.2.8l1.6 1.6c.8-.3 1.7-.4 2.6-.4a5 5 0 0 1 5 5c0 .4 0 .7-.1 1l3 3c1.6-1.6 2.7-3.2 2.8-3.4a1 1 0 0 0 0-.9C22.3 11.1 18.4 5 12 5zM2.7 3.3 1.3 4.7l2.6 2.6C2.4 8.8 1.8 10.4 1.5 11.4a1 1 0 0 0 0 .9C1.7 12.9 5.6 19 12 19c1.8 0 3.4-.5 4.8-1.2l3.5 3.5 1.4-1.4-19-16.6zM12 17a5 5 0 0 1-5-5c0-.8.2-1.6.5-2.2l1.6 1.6A3 3 0 0 0 12 15c.4 0 .8-.1 1.1-.2l1.6 1.6c-.8.4-1.7.6-2.7.6z"/></svg>
        </button>
      </div>
      <button type="submit">Sign in</button>
    </form>
    {notice_html}
    <div class="note">
      <strong>Accounts are separate; the data is not.</strong> Everyone signed in to
      this install shares its projects, files, chats, knowledge and API keys.
      Lost your password? An administrator can set a new one — there is no email reset.
    </div>
  </main>
{_PW_TOGGLE_SCRIPT}
</body>
</html>"""


def _page(**kwargs) -> HTMLResponse:
    # no-store: a cached login page is confusing after a password change, and the
    # page carries no reusable state anyway.
    return HTMLResponse(render_page(**kwargs), headers={"cache-control": "no-store"})


# ── helpers ─────────────────────────────────────────────────────────────────

async def _read_form(request: Request) -> dict:
    """Accept both an HTML form post and a JSON body from an API client."""
    content_type = (request.headers.get("content-type") or "").lower()
    if content_type.startswith("application/json"):
        try:
            data = await request.json()
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}
    try:
        form = await request.form()
    except Exception:
        return {}
    return {k: str(v) for k, v in form.items()}


def _wants_html(request: Request) -> bool:
    return "text/html" in (request.headers.get("accept") or "").lower()


def _set_cookie(response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=int(_session_days() * 24 * 3600),
        path="/",
        httponly=True,
        samesite="lax",
        secure=_cookie_secure(),
    )


def _clear_cookie(response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")


# ── routes ──────────────────────────────────────────────────────────────────

@router.get(SIGNIN_PATH, response_class=HTMLResponse)
def signin_page(request: Request, next: Optional[str] = None):
    """The page itself. Reachable without a session (see PUBLIC_PREFIXES in the gate)."""
    target = _safe_next(next or request.query_params.get("next"))

    # A browser that signed out is shown the page even if a session cookie is still
    # around. Redirecting it back into the app would make the gate refuse it (the
    # marker outranks the session), which redirects here again — a reload loop that
    # only ever stops when the cookie expires.
    signed_out = request.cookies.get(SIGNOUT_COOKIE) is not None

    db = SessionLocal()
    try:
        # Already signed in? Do not make the person sign in twice.
        if not signed_out and session_service.resolve(
            db, request.cookies.get(SESSION_COOKIE)
        ) is not None:
            return RedirectResponse(target, status_code=303)
        exists = user_service.count_users(db) > 0
    finally:
        db.close()

    if not exists:
        return _page(
            next=target,
            notice=(
                "<strong>No accounts exist yet.</strong> Create the first administrator "
                "on the server:<br><code>cd backend &amp;&amp; .venv/bin/python "
                "scripts/create_user.py admin '&lt;password&gt;' --admin</code>"
            ),
        )
    return _page(next=target)


@router.post("/api/auth/login")
async def login(request: Request):
    """Verify the password once, then hand the browser an opaque session cookie."""
    payload = await _read_form(request)
    username = (payload.get("username") or "").strip()
    password = payload.get("password") or ""
    target = _safe_next(payload.get("next"))
    wants_html = _wants_html(request)

    key = _client_key(request)
    if _too_many_failures(key):
        message = "Too many failed attempts. Wait a few minutes and try again."
        if wants_html:
            return _page(error=message, next=target, username=username)
        return JSONResponse({"detail": message}, status_code=429)

    db = SessionLocal()
    try:
        try:
            user = user_service.authenticate(db, username, password)
        except UserError:
            user = None

        if user is None:
            _record_failure(key)
            logger.warning("Failed sign-in for %r from %s", username, key)
            message = "Incorrect username/nickname or password."
            if wants_html:
                return _page(error=message, next=target, username=username)
            return JSONResponse({"detail": message}, status_code=401)

        _clear_failures(key)
        token, session = session_service.create_session(db, user, request=request)
        identity = session_service.to_context(session, user)
    finally:
        db.close()

    if wants_html:
        response = RedirectResponse(target, status_code=303)
    else:
        response = JSONResponse({"status": "ok", "user": identity.to_public()})
    _set_cookie(response, token)
    # A fresh sign-in outranks any earlier sign-out marker left in this browser.
    response.delete_cookie(SIGNOUT_COOKIE, path="/")
    return response


@router.api_route("/api/auth/logout", methods=["GET", "POST"])
def logout(request: Request):
    """End this browser's session and send it back to the sign-in page."""
    token = request.cookies.get(SESSION_COOKIE)
    db = SessionLocal()
    try:
        session_service.revoke(db, token)
    finally:
        db.close()

    response: RedirectResponse = RedirectResponse(SIGNIN_PATH, status_code=303)
    _clear_cookie(response)
    # Keep the Basic-auth sign-out marker too: a browser that signed in through the
    # prompt (an older bookmark, a script that cached credentials) has no session
    # cookie to revoke, and the marker is what suppresses those cached credentials.
    response.set_cookie(
        SIGNOUT_COOKIE, "1", path="/", httponly=True, samesite="lax"
    )
    return response


@router.get("/api/auth/session")
def current_session(request: Request):
    """Who this cookie belongs to. 401 when there is no valid session."""
    token = request.cookies.get(SESSION_COOKIE)
    db = SessionLocal()
    try:
        session = session_service.resolve(db, token)
        if session is None or session.user is None:
            return JSONResponse({"detail": "Not signed in."}, status_code=401)
        identity = session_service.to_context(session, session.user)
        return {
            "user": identity.to_public(),
            "session": session.to_public(),
            "expires_in_seconds": int(
                (session.expires_at - session_service._utc_now()).total_seconds()
            ),
        }
    finally:
        db.close()


@router.get("/api/auth/sessions")
def my_sessions(request: Request):
    """Every browser signed in as this account — the list "sign out others" needs."""
    token = request.cookies.get(SESSION_COOKIE)
    db = SessionLocal()
    try:
        session = session_service.resolve(db, token)
        if session is None or session.user is None:
            return JSONResponse({"detail": "Not signed in."}, status_code=401)
        rows = session_service.list_for_user(db, session.user_id)
        return {
            "current_id": session.id,
            "sessions": [{**row.to_public(), "current": row.id == session.id} for row in rows],
        }
    finally:
        db.close()


# ── legacy aliases ──────────────────────────────────────────────────────────
# The user popover and the docs shipped `/api/auth/sign-out` first, when a marker
# cookie was the whole mechanism. Those URLs keep working: sign-out is now a real
# session revoke plus the marker (which still covers browsers holding Basic
# credentials), and sign-in is the panel.

@router.get("/api/auth/sign-out")
def legacy_sign_out(request: Request):
    """Deprecated alias for ``/api/auth/logout``."""
    return logout(request)


@router.get("/api/auth/sign-in")
def legacy_sign_in(request: Request, next: Optional[str] = None):
    """Deprecated alias: the sign-in UI is the page at ``/signin``."""
    target = _safe_next(next or request.query_params.get("next"))
    response = RedirectResponse(f"{SIGNIN_PATH}?next={target}", status_code=303)
    response.delete_cookie(SIGNOUT_COOKIE, path="/")
    return response


@router.post("/api/auth/sessions/{session_id}/revoke")
def revoke_one(session_id: int, request: Request):
    """Sign out one of my other browsers (or this one)."""
    from models.auth_session import AuthSession

    token = request.cookies.get(SESSION_COOKIE)
    db = SessionLocal()
    try:
        session = session_service.resolve(db, token)
        if session is None:
            return JSONResponse({"detail": "Not signed in."}, status_code=401)
        row = (
            db.query(AuthSession)
            .filter(AuthSession.id == session_id, AuthSession.user_id == session.user_id)
            .first()
        )
        if row is None:
            return JSONResponse({"detail": f"Session {session_id} not found"}, status_code=404)
        db.delete(row)
        db.commit()
        response = {"status": "ok", "revoked": session_id, "was_current": row.id == session.id}
        result = JSONResponse(response)
        if row.id == session.id:
            _clear_cookie(result)
        return result
    finally:
        db.close()
