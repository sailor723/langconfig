#!/usr/bin/env python
"""Create (or repair) a LangConfig account from the server's shell.

When you need this:

* **First admin, no usable `.env` credential.** The gate refuses everything with
  503 until one account exists, so the way in is a shell on the server. This is
  the command the 503 page tells you to run.
* **Locked out.** A typo in a password, a disabled last admin, a reinstall
  pointing at an old database — an operator with shell access can always fix it.

When you do *not* need it: day-to-day account management. That lives in the app
(Admin -> Users) and needs no shell.

Usage::

    cd backend
    .venv/bin/python scripts/create_user.py alice 'a-long-password' --admin
    .venv/bin/python scripts/create_user.py bob 'another-password' --display-name "Bob"
    .venv/bin/python scripts/create_user.py alice --reset-password 'new-password'
    .venv/bin/python scripts/create_user.py --list

Notes:
  * Passwords are read from the command line, so they land in your shell history.
    Prefer the interactive prompt (omit the password) on a shared machine.
  * The password policy is the app's (minimum 8 characters) — not bypassed here,
    because a shell shortcut that creates a weak account is a back door nobody
    audits.
"""

import argparse
import getpass
import sys
from pathlib import Path

# Run from anywhere: this script lives in backend/scripts/.
BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))

from db.database import SessionLocal  # noqa: E402
from models.user import UserRole  # noqa: E402
from services import user_service  # noqa: E402
from services.user_service import UserError  # noqa: E402


def _fail(message: str, code: int = 1) -> "NoReturn":  # type: ignore[valid-type]
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(code)


def _read_password(args, verb: str) -> str:
    if args.password:
        return args.password
    first = getpass.getpass(f"{verb} password: ")
    second = getpass.getpass("repeat password: ")
    if first != second:
        _fail("the two passwords do not match")
    return first


def _show(users) -> None:
    if not users:
        print("no accounts exist yet")
        return
    print(f"{'id':>4}  {'username':<32} {'role':<7} {'active':<7} last login")
    for user in users:
        last = user.last_login_at.strftime("%Y-%m-%d %H:%M") if user.last_login_at else "never"
        print(
            f"{user.id:>4}  {user.username:<32} {user.role.value:<7} "
            f"{str(bool(user.is_active)):<7} {last}"
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create, reset or inspect LangConfig accounts.",
        epilog="Run from backend/: .venv/bin/python scripts/create_user.py --help",
    )
    parser.add_argument("username", nargs="?", help="account name (2-64 chars)")
    parser.add_argument("password", nargs="?", help="password (min 8); omit to be prompted")
    parser.add_argument("--admin", action="store_true", help="create as an administrator")
    parser.add_argument("--display-name", default=None, help="name shown in the UI")
    parser.add_argument(
        "--nickname",
        default=None,
        help="extra login alias (2-32 chars); the account can sign in with it too",
    )
    parser.add_argument(
        "--set-nickname",
        default=None,
        help="change or clear ('' ) the nickname of an existing account",
    )
    parser.add_argument(
        "--reset-password",
        metavar="NEW_PASSWORD",
        default=None,
        help="change an existing account's password instead of creating one",
    )
    parser.add_argument("--enable", action="store_true", help="re-enable a disabled account")
    parser.add_argument("--list", action="store_true", help="list accounts and exit")
    args = parser.parse_args()

    db = SessionLocal()
    try:
        if args.list:
            _show(user_service.list_users(db))
            return 0

        if not args.username:
            parser.error("a username is required (or use --list)")

        existing = user_service.get_by_username(db, args.username)

        # ── reset an existing account ───────────────────────────────────────
        if args.reset_password is not None or args.enable or args.set_nickname is not None:
            if existing is None:
                _fail(f"no account named {args.username!r} — drop --reset-password to create it")

            if args.reset_password is not None:
                try:
                    user_service.set_password(db, existing, args.reset_password)
                except UserError as exc:
                    _fail(str(exc))
                print(f"password reset for {existing.username!r}")

            if args.set_nickname is not None:
                try:
                    user_service.update_user(db, existing, nickname=args.set_nickname)
                except UserError as exc:
                    _fail(str(exc))
                print(
                    f"nickname for {existing.username!r}: "
                    f"{existing.nickname or '(cleared)'}"
                )

            if args.enable and not existing.is_active:
                user_service.update_user(db, existing, is_active=True)
                print(f"account {existing.username!r} is active again")
            elif args.enable:
                print(f"account {existing.username!r} was already active")
            return 0

        # ── create ──────────────────────────────────────────────────────────
        if existing is not None:
            _fail(
                f"account {existing.username!r} already exists — use "
                f"--reset-password to change its password"
            )

        password = _read_password(args, "new")
        role = UserRole.ADMIN if args.admin else UserRole.MEMBER
        try:
            user = user_service.create_user(
                db,
                args.username,
                password,
                display_name=args.display_name,
                nickname=args.nickname,
                role=role,
            )
        except UserError as exc:
            _fail(str(exc))

        alias = f" — signs in as {user.username!r} or {user.nickname!r}" if user.nickname else ""
        print(f"created {user.username!r} ({user.role.value}){alias}")
        if user.role == UserRole.ADMIN and user_service.count_active_admins(db) == 1:
            print("  this is the first administrator: LAN access now works, and")
            print("  further accounts can be created in the app (Admin -> Users).")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
