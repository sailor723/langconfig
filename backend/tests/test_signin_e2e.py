"""End-to-end sign-in flow in a real browser.

Why this exists: the sign-out reload loop that a user hit ("page keeps refreshing")
was invisible to every unit test in the suite — the gate, the session service and the
endpoints were each correct, and the loop lived in the *interaction* between the
sign-in page, the 401 handler and the browser's navigation behaviour. Only a browser
can catch that class of bug.

Opt-in by design:

    LANGCONFIG_E2E_BASE=http://192.168.3.23:8765 \\
    LANGCONFIG_E2E_USER=admin \\
    LANGCONFIG_E2E_PASSWORD='…' \\
    .venv/bin/python -m pytest tests/test_signin_e2e.py -m e2e -q

Skipped (not failed) when any of those are missing, when the instance is
unreachable, or when no Playwright browser is installed — a suite that fails on a
laptop with no browser installed teaches people to ignore red.

The account used must already exist. Each test gets a fresh browser context, so the
cookie jar is empty at the start and a test can never inherit a previous sign-in.
Signing in here creates a session and the tests revoke it on the way out; sessions
belonging to real browsers are untouched.
"""

from __future__ import annotations

import os
import urllib.error
import urllib.request

import pytest

pytestmark = pytest.mark.e2e

BASE = os.getenv("LANGCONFIG_E2E_BASE", "").rstrip("/")
USER = os.getenv("LANGCONFIG_E2E_USER", "")
PASSWORD = os.getenv("LANGCONFIG_E2E_PASSWORD", "")

#: How long a page may keep navigating before we call it a loop. The real loop
#: produced dozens of navigations per second; three is generous for a legitimate
#: boot (SPA start → redirect → settle).
MAX_NAVIGATIONS_PER_LOAD = 3


def _skip_reasons() -> list[str]:
    reasons = []
    if not BASE:
        reasons.append("LANGCONFIG_E2E_BASE is not set")
    if not USER or not PASSWORD:
        reasons.append("LANGCONFIG_E2E_USER / LANGCONFIG_E2E_PASSWORD are not set")
    return reasons


@pytest.fixture(scope="module", autouse=True)
def _require_target():
    reasons = _skip_reasons()
    if reasons:
        pytest.skip("e2e needs a live instance: " + "; ".join(reasons))
    try:
        with urllib.request.urlopen(f"{BASE}/signin", timeout=5) as response:
            if response.status != 200:
                pytest.skip(f"{BASE}/signin answered {response.status}")
    except (urllib.error.URLError, OSError) as exc:
        pytest.skip(f"{BASE} is not reachable: {exc}")


@pytest.fixture(scope="module")
def chromium():
    """A launched browser, or a skip explaining how to get one."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:  # pragma: no cover - environment dependent
        pytest.skip("playwright is not installed: .venv/bin/python -m pip install playwright")

    with sync_playwright() as driver:
        try:
            browser = driver.chromium.launch()
        except Exception as exc:  # noqa: BLE001 - launch failures are environmental
            pytest.skip(
                "no Playwright browser available "
                f"({str(exc).splitlines()[0][:120]}). Install one with: "
                ".venv/bin/python -m playwright install chromium"
            )
        try:
            yield browser
        finally:
            browser.close()


class Session:
    """A page plus the navigations it performs, so a loop is measurable."""

    def __init__(self, browser):
        self.context = browser.new_context()
        self.page = self.context.new_page()
        self.navigations: list[str] = []
        self.page.on(
            "framenavigated",
            lambda frame: self.navigations.append(frame.url)
            if frame == self.page.main_frame
            else None,
        )

    def watch(self):
        """Start counting from here."""
        self.navigations.clear()
        return self

    def settle(self, ms: int = 2500) -> None:
        self.page.wait_for_timeout(ms)

    def goto(self, path: str = "/") -> "Session":
        self.page.goto(f"{BASE}{path}", wait_until="domcontentloaded")
        return self

    def has_password_field(self) -> bool:
        return self.page.locator('input[name="password"]').count() > 0

    def has_app_shell(self) -> bool:
        # The SPA mounts into #root; the sign-in page never has one. This is the
        # cheapest honest way to tell "the app" from "the sign-in page".
        return self.page.locator("#root").count() > 0

    def sign_in(self, username: str = USER, password: str = PASSWORD) -> "Session":
        self.page.fill('input[name="username"]', username)
        self.page.fill('input[name="password"]', password)
        self.page.click('button[type="submit"]')
        return self

    def close(self) -> None:
        self.context.close()


@pytest.fixture
def session(chromium):
    client = Session(chromium)
    try:
        yield client
    finally:
        client.close()


# ── the page itself ─────────────────────────────────────────────────────────

def test_unauthenticated_visit_lands_on_the_sign_in_page(session):
    session.goto("/").settle()

    assert "/signin" in session.page.url, f"expected the sign-in page, got {session.page.url}"
    assert session.has_password_field(), "the sign-in page must offer a password field"


def test_sign_in_page_is_not_the_spa(session):
    """It is a separate page on purpose: the bundle is behind the gate."""
    session.goto("/signin").settle()

    assert session.has_password_field()
    assert not session.has_app_shell(), "the sign-in page must not boot the whole app"


def test_wrong_password_shows_a_message_on_the_page(session):
    session.goto("/signin").settle()
    session.sign_in(password="definitely-not-the-password").settle()

    message = session.page.locator("body").inner_text()
    assert "Incorrect username or password" in message
    assert session.has_password_field(), "a failed attempt must not navigate away"


# ── the flow, and the loop that was reported ────────────────────────────────

def test_sign_in_reaches_the_app(session):
    session.goto("/").settle()
    assert session.has_password_field()

    session.watch().sign_in()
    session.settle(4000)

    assert session.has_app_shell(), "signing in should load the application"
    assert not session.has_password_field()
    assert len(session.navigations) <= MAX_NAVIGATIONS_PER_LOAD, (
        f"signing in navigated {len(session.navigations)} times: {session.navigations[:6]}"
    )


def test_sign_out_returns_to_the_sign_in_page_without_reloading_forever(session):
    """The reported bug: "I run sign off, but page keep refreshing".

    Sign out, then reload twice. Each load may redirect once (the gate sends a
    browser to /signin); it may not keep going.
    """
    session.goto("/").settle()
    session.sign_in()
    session.settle(4000)
    assert session.has_app_shell()

    session.watch()
    session.page.goto(f"{BASE}/api/auth/logout", wait_until="domcontentloaded")
    session.settle(4000)

    assert "/signin" in session.page.url, session.page.url
    assert session.has_password_field()
    assert len(session.navigations) <= MAX_NAVIGATIONS_PER_LOAD, (
        f"sign out looped: {len(session.navigations)} navigations {session.navigations[:6]}"
    )

    for attempt in range(2):
        session.watch().goto("/").settle(3000)
        assert "/signin" in session.page.url, (
            f"reload {attempt} left the sign-in page: {session.page.url}"
        )
        assert session.has_password_field()
        assert len(session.navigations) <= MAX_NAVIGATIONS_PER_LOAD, (
            f"reload {attempt} looped: {len(session.navigations)} "
            f"navigations {session.navigations[:6]}"
        )
        assert session.page.locator("body").inner_text().strip(), "blank page after reload"


def test_signing_in_again_clears_the_signed_out_state(session):
    """The marker cookie must not outlive the next sign-in, or the app stays refused."""
    session.goto("/").settle()
    session.sign_in()
    session.settle(3000)
    session.page.goto(f"{BASE}/api/auth/logout", wait_until="domcontentloaded")
    session.settle(2000)

    session.watch().sign_in()
    session.settle(4000)

    assert session.has_app_shell(), (
        f"signing in after signing out did not open the app (at {session.page.url})"
    )
    cookies = {c["name"]: c["value"] for c in session.context.cookies()}
    assert "langconfig_signed_out" not in cookies, "the sign-out marker survived a new sign-in"
    assert cookies.get("langconfig_session"), "no session cookie after signing in"


# ── the API surface the browser depends on ──────────────────────────────────

def test_session_cookie_is_accepted_by_the_api_but_not_exposed_to_scripts(session):
    """HttpOnly is the point: a session token must be unusable from page JS."""
    session.goto("/").settle()
    session.sign_in()
    session.settle(3000)

    cookies = {c["name"]: c for c in session.context.cookies()}
    token = cookies.get("langconfig_session")
    assert token, "signing in did not set a session cookie"
    assert token["httpOnly"] is True, "the session cookie must be HttpOnly"
    assert cookies.get("langconfig_signed_out") is None

    visible = session.page.evaluate("() => document.cookie")
    assert "langconfig_session" not in visible, "document.cookie must not see the session"

    me = session.page.evaluate(
        """async () => {
            const r = await fetch('/api/users/me', {headers: {'accept': 'application/json'}});
            return {status: r.status, body: await r.json()};
        }"""
    )
    assert me["status"] == 200, me
    assert me["body"]["username"] == USER
    assert me["body"]["via"] in ("session", "loopback", "lan"), me["body"]
