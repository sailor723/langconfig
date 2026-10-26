# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Sign out — and the truth about what that can and cannot do.

HTTP Basic authentication has no session and no logout message: the browser keeps
the credential in its own authentication cache and attaches it to every request
for that realm until the browser is closed. So a naive "Sign out" button that only
cleared client state would be a lie — the very next request would be authenticated
again.

What this does instead: signing out sets a session cookie
(``langconfig_signed_out``) that the LAN gate honours *before* it looks at the
credential, and answers the signed-out browser with **401 and no
``WWW-Authenticate`` header**. That last part is the trick — a 401 without a
challenge tells the browser "this is not a credential problem, do not ask", so it
neither re-prompts nor silently retries with the credential it still holds. The
result is a real sign-out for this browser session: the app is unreachable until
someone presses *Sign in*.

``GET /api/auth/sign-in`` deletes the marker and redirects back into the app; the
browser then replays its remembered credential, so signing back in needs no typing.
If that is not who you are, close the browser (or use a private window) — the only
step that also clears the browser's own credential cache.

Both routes are reachable while signed out by design: the gate exempts
``/api/auth/`` unconditionally. Neither reveals anything about any account.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from middleware.lan_guard import SIGNOUT_COOKIE, lan_access_enabled

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/auth", tags=["auth"])

#: The "Sign in" link lands here after signing out.
DEFAULT_NEXT = "/"


def _safe_next(raw: Optional[str]) -> str:
    """Only ever redirect to a path on this origin.

    An unvalidated ``next`` is an open redirect: a link like
    ``/api/auth/sign-in?next=https://evil`` would hand a freshly authenticated
    browser to someone else's page.
    """
    if not raw:
        return DEFAULT_NEXT
    value = raw.strip()
    if not value.startswith("/") or value.startswith("//") or "\\" in value:
        return DEFAULT_NEXT
    return value


def _page(title: str, body: str, action_href: str, action_label: str, note: str) -> str:
    """A tiny self-contained page.

    Deliberately not the SPA: this page has to render while the app itself refuses
    to load, so it cannot depend on the bundle.
    """
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title} — LangConfig</title>
<style>
  html, body {{ height: 100%; margin: 0; }}
  body {{
    background: #1e1e1e; color: #d4d4d4;
    font: 14px/1.6 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    display: flex; align-items: center; justify-content: center; padding: 24px;
  }}
  main {{ max-width: 460px; text-align: center; }}
  h1 {{ font-size: 20px; font-weight: 600; margin: 0 0 8px; color: #f5f5f5; }}
  p {{ margin: 0 0 18px; color: #a3a3a3; }}
  a.button {{
    display: inline-block; padding: 9px 22px; border-radius: 18px;
    background: #0e639c; color: #fff; text-decoration: none; font-weight: 500;
  }}
  a.button:hover {{ background: #1177bb; }}
  .note {{ margin-top: 26px; font-size: 12px; color: #7a7a7a; line-height: 1.55; }}
</style>
</head>
<body>
<main>
  <h1>{title}</h1>
  <p>{body}</p>
  <a class="button" href="{action_href}">{action_label}</a>
  <div class="note">{note}</div>
</main>
</body>
</html>"""


@router.get("/sign-out")
def sign_out(request: Request, next: Optional[str] = None):
    """End this browser session's access to the app."""
    target = _safe_next(next or request.query_params.get("next"))

    if not lan_access_enabled():
        # No gate means no sign-in was required, so there is nothing to end. Say so
        # rather than pretending and bouncing the user back in.
        return HTMLResponse(
            _page(
                "LAN access is off",
                "This install does not ask anyone to sign in, so there is no "
                "session to end.",
                target,
                "Back to the app",
                "Start the backend with LANGCONFIG_LAN_ACCESS=on to require "
                "accounts.",
            )
        )

    logger.info("Signed out of the browser session")
    response = HTMLResponse(
        _page(
            "Signed out",
            "This browser no longer has access to LangConfig.",
            f"/api/auth/sign-in?next={target}",
            "Sign in",
            "This browser remembers your login, so <em>Sign in</em> returns you to "
            "the same account without typing. To sign in as someone else, close the "
            "browser or use a private window — that is the only step which also "
            "clears the browser's own saved credential.",
        )
    )
    # Session cookie (no Max-Age): the marker lives exactly as long as the browser
    # session, which is the same lifetime as the credential it is suppressing.
    response.set_cookie(
        SIGNOUT_COOKIE,
        "1",
        path="/",
        httponly=True,
        samesite="lax",
    )
    return response


@router.get("/sign-in")
def sign_in(request: Request, next: Optional[str] = None):
    """Drop the signed-out marker and go back into the app."""
    target = _safe_next(next or request.query_params.get("next"))
    response = RedirectResponse(target, status_code=303)
    response.delete_cookie(SIGNOUT_COOKIE, path="/")
    return response
