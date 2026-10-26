# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Password hashing — stdlib ``hashlib.scrypt``, no third-party dependency.

Why scrypt and not argon2/bcrypt: neither is installed here, and adding a compiled
dependency to authenticate a handful of LAN users is a poor trade. scrypt ships
with CPython, is memory-hard, and its parameters are stored *in the hash string*,
so they can be raised later without invalidating existing passwords
(:func:`needs_rehash`).

Cost on the reference machine: ~25 ms per hash at n=16384, r=8, p=1. That is
deliberately slow — which is why the LAN gate caches successful authentications
for a short TTL instead of re-verifying on every request
(``core/security/lan_auth.py``).

Format::

    scrypt$<n>$<r>$<p>$<base64 salt>$<base64 derived key>

This is a **different key** from ``API_KEY_ENCRYPTION_KEY``: that one encrypts
provider credentials at rest, this one authenticates people. Do not reuse it.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import secrets

SCHEME = "scrypt"

# Floor for new hashes. Raising these is safe: verification uses the values stored
# in the hash string, not these constants.
N = 2 ** 14      # CPU/memory cost (~16 MiB at r=8)
R = 8
P = 1
SALT_BYTES = 16
KEY_BYTES = 32

MIN_PASSWORD_LENGTH = 8      # the policy chosen for scope A
MAX_PASSWORD_LENGTH = 1024   # refuse absurd inputs before spending CPU on them


def hash_password(password: str) -> str:
    """Hash a password for storage. Refuses empty or too-short input.

    An empty password is refused rather than hashed: a row holding a hash of ""
    would authenticate against a blank field, and nothing would say so.
    """
    if not password:
        raise ValueError("password must not be empty")
    if len(password) < MIN_PASSWORD_LENGTH:
        raise ValueError(f"password must be at least {MIN_PASSWORD_LENGTH} characters")
    if len(password) > MAX_PASSWORD_LENGTH:
        raise ValueError(f"password too long (max {MAX_PASSWORD_LENGTH})")

    salt = secrets.token_bytes(SALT_BYTES)
    derived = hashlib.scrypt(
        password.encode("utf-8"), salt=salt, n=N, r=R, p=P, dklen=KEY_BYTES
    )
    return "$".join(
        (
            SCHEME,
            str(N),
            str(R),
            str(P),
            base64.b64encode(salt).decode("ascii"),
            base64.b64encode(derived).decode("ascii"),
        )
    )


def verify_password(password: str, encoded: str) -> bool:
    """Constant-time check of a password against a stored hash.

    Returns False for any malformed hash rather than raising: a corrupt row must
    read as "wrong password", never as an exception that leaks or bypasses the
    check.
    """
    if not password or not encoded:
        return False
    try:
        scheme, n_s, r_s, p_s, salt_b64, key_b64 = encoded.split("$")
    except ValueError:
        return False
    if scheme != SCHEME:
        return False

    try:
        salt = base64.b64decode(salt_b64, validate=True)
        expected = base64.b64decode(key_b64, validate=True)
        n, r, p = int(n_s), int(r_s), int(p_s)
    except (binascii.Error, ValueError):
        return False

    # Bound the work a hostile row can demand: a tampered hash must not turn one
    # login attempt into a memory bomb.
    if not (2 ** 12 <= n <= 2 ** 18) or not (1 <= r <= 64) or not (1 <= p <= 16):
        return False
    if not expected:
        return False

    try:
        derived = hashlib.scrypt(
            password.encode("utf-8"), salt=salt, n=n, r=r, p=p, dklen=len(expected)
        )
    except (ValueError, MemoryError):
        return False
    return hmac.compare_digest(derived, expected)


def needs_rehash(encoded: str) -> bool:
    """True when a stored hash used weaker parameters than the current constants.

    Called after a successful verify, so parameters can be raised over time
    without forcing everyone to reset.
    """
    try:
        scheme, n_s, r_s, p_s, _salt, _key = encoded.split("$")
    except ValueError:
        return True
    if scheme != SCHEME:
        return True
    try:
        return (int(n_s), int(r_s), int(p_s)) < (N, R, P)
    except ValueError:
        return True
