"""HTTP response helpers shared by API routers.

RFC 5987 download filenames
---------------------------
ASGI servers encode HTTP header values as **latin-1**, so a filename such as
``全球股市研究分析师.py`` raises

    UnicodeEncodeError: ordinal not in range(256)

before the response body is ever sent — the request fails with HTTP 500 even
though the payload was built fine.

``content_disposition()`` avoids that by emitting both forms in one header:

* ``filename="..."``        — ASCII-only fallback for legacy clients
* ``filename*=UTF-8''...``  — percent-encoded UTF-8 name that modern browsers
  and HTTP clients prefer, so the downloaded file keeps its original Chinese /
  Japanese / accented name instead of being renamed.

The ASCII fallback is built from an allowlist, which also strips CR/LF and
quote characters — a header-injection guard, since filenames are often derived
from user-supplied names (agent names, presentation titles, workflow names).
"""

from __future__ import annotations

import os
from urllib.parse import quote

__all__ = ["ascii_filename", "content_disposition"]

# Kept as-is in the ASCII fallback; everything else is dropped.
_SAFE_ASCII = set(" -_.")


def ascii_filename(filename: str, default: str = "download") -> str:
    """Reduce ``filename`` to an ASCII-only, header-safe fallback.

    The extension is preserved (``全球股市研究分析师.py`` -> ``download.py``),
    and a purely non-ASCII stem falls back to ``default`` rather than yielding
    a bare ``.py``.
    """
    stem, suffix = os.path.splitext(filename or "")

    keep = "".join(
        c for c in stem if c.isascii() and (c.isalnum() or c in _SAFE_ASCII)
    ).strip(" .-_")

    if not all(c.isascii() and (c.isalnum() or c == ".") for c in suffix):
        suffix = ""

    if keep:
        return f"{keep}{suffix}"
    return f"{default}{suffix}" if suffix else default


def content_disposition(filename: str, inline: bool = False) -> str:
    """Build a ``Content-Disposition`` header value safe for any filename.

    Args:
        filename: the name the client should see (may contain non-ASCII).
        inline: ``True`` renders in-browser where possible, ``False`` forces a
            download.

    Returns:
        A latin-1-encodable header value carrying both the ASCII fallback and
        the RFC 5987 UTF-8 form.
    """
    disposition = "inline" if inline else "attachment"
    fallback = ascii_filename(filename)
    return (
        f'{disposition}; filename="{fallback}"; '
        f"filename*=UTF-8''{quote(filename or fallback)}"
    )
