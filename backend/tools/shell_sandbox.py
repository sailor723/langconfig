# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Confine the agent's shell to one account's tree.

Why this is separate from the other tools: `ls`, `read_file`, `glob` take a *path*, so
one check on that path bounds them completely. `bash` takes a *program* — `cat
/anywhere` reaches whatever the OS lets it reach, and no amount of path validation
inside the tool changes that. The only place to bound it is the OS.

Two mechanisms, both "hide the other trees, then hand back the caller's own":

* **macOS** — `sandbox-exec` with a generated profile: read everything, then *deny* the
  sibling `users/<id>/` trees and allow the caller's back; deny all writes except the
  caller's tree plus the temp directories a shell legitimately needs.
* **Linux** — `bubblewrap` (`bwrap`): `--tmpfs <install>/users` hides every account
  tree, then `--bind <own> <own>` puts the caller's own back.

Both are probed once at startup with a real command, because a sandbox that silently
does nothing is worse than none: the probe result is logged, and when it fails the tool
falls back to the plain shell **and says so in the result** … no, in the log only, since
the model would otherwise report the warning to the user as if it were a finding. The
honest place for it is the boot log and the docs.

Verified state (2026-10-26): this development Mac runs the app under a nested sandbox,
where `sandbox_apply` itself is refused — so the shell path here reports
``unavailable (sandbox_apply: Operation not permitted)`` and falls back. It is expected
to be available on a bare host (Aliyun ECS) and on Linux with ``bwrap`` installed. That
caveat is written down rather than discovered by whoever relies on it.
"""

from __future__ import annotations

import logging
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

#: Directories a shell needs to read and where temporary files may go.
_READ_ALWAYS = ("/usr", "/bin", "/sbin", "/System", "/Library", "/opt", "/etc", "/dev")
_TEMP_DIRS = ("/tmp", "/private/tmp", "/var/folders", "/var/tmp")

_probe_cache: Optional[dict] = None


def _macos_profile(own_root: Path, install_root: Path) -> str:
    """SBPL: read widely, hide the other account trees, write only in one's own."""
    lines = [
        "(version 1)",
        "(deny default)",
        "(allow process*)",
        "(allow network*)",
        "(allow ipc-posix*)",
        "(allow sysctl-read)",
        "(allow signal)",
        "(allow mach-lookup)",
        "(allow file-read*)",
        # Hide every account tree, then give the caller's own back. Order matters:
        # in SBPL the last matching rule wins.
        f'(deny file-read* (subpath "{install_root / "users"}"))',
        f'(allow file-read* (subpath "{own_root}"))',
        # No writes anywhere, except the caller's tree and temp space.
        "(deny file-write*)",
        f'(allow file-write* (subpath "{own_root}"))',
    ]
    lines += [f'(allow file-write* (subpath "{d}"))' for d in _TEMP_DIRS]
    return "\n".join(lines)


def _linux_bwrap_args(own_root: Path, install_root: Path) -> list:
    """bwrap: same idea with mounts — hide `users/`, bind the caller's own back."""
    return [
        "--dev-bind", "/", "/",
        "--tmpfs", str(install_root / "users"),
        "--bind", str(own_root), str(own_root),
        "--chdir", str(own_root),
    ]


def available() -> dict:
    """Probe the mechanism once and remember the verdict.

    Returns ``{"kind": "macos"|"bwrap"|None, "reason": "..."}``. The probe runs a real
    command, because both mechanisms can be present and still refuse (a nested sandbox,
    a container without user namespaces).
    """
    global _probe_cache
    if _probe_cache is not None:
        return _probe_cache

    verdict = {"kind": None, "reason": "no sandbox mechanism on this platform"}

    if sys.platform == "darwin" and shutil.which("sandbox-exec"):
        profile = "(version 1)(deny default)(allow process*)(allow file-write*)"
        try:
            proc = subprocess.run(
                ["/usr/bin/sandbox-exec", "-p", profile, "/bin/echo", "ok"],
                capture_output=True, text=True, timeout=10,
            )
            if proc.returncode == 0 and "ok" in (proc.stdout or ""):
                verdict = {"kind": "macos", "reason": "sandbox-exec verified"}
            else:
                verdict = {
                    "kind": None,
                    "reason": (proc.stderr or proc.stdout or "sandbox-exec refused").strip()[:200],
                }
        except Exception as exc:  # noqa: BLE001
            verdict = {"kind": None, "reason": f"sandbox-exec probe failed: {exc}"}

    elif sys.platform.startswith("linux") and shutil.which("bwrap"):
        try:
            proc = subprocess.run(
                ["bwrap", "--dev-bind", "/", "/", "--tmpfs", "/tmp", "/bin/echo", "ok"],
                capture_output=True, text=True, timeout=10,
            )
            if proc.returncode == 0 and "ok" in (proc.stdout or ""):
                verdict = {"kind": "bwrap", "reason": "bwrap verified"}
            else:
                verdict = {"kind": None, "reason": (proc.stderr or "bwrap refused").strip()[:200]}
        except Exception as exc:  # noqa: BLE001
            verdict = {"kind": None, "reason": f"bwrap probe failed: {exc}"}

    _probe_cache = verdict
    if verdict["kind"]:
        logger.info("Shell sandbox active: %s (%s)", verdict["kind"], verdict["reason"])
    else:
        logger.warning(
            "Shell sandbox UNAVAILABLE (%s) — `bash` will run unsandboxed: absolute paths "
            "outside the workspace are reachable from a shell. File tools remain scoped.",
            verdict["reason"],
        )
    return verdict


def describe() -> str:
    verdict = available()
    return f"{verdict['kind'] or 'none'} ({verdict['reason']})"


def wrap(command: str, own_root: Path | str, install_root: Path | str) -> Optional[str]:
    """A shell command that runs ``command`` confined to ``own_root``.

    Returns None when no mechanism is available, so the caller runs the plain command
    rather than pretending.
    """
    verdict = available()
    own = Path(own_root).resolve()
    install = Path(install_root).resolve()

    if verdict["kind"] == "macos":
        profile = _macos_profile(own, install)
        return f"/usr/bin/sandbox-exec -p {shlex.quote(profile)} /bin/bash -c {shlex.quote(command)}"
    if verdict["kind"] == "bwrap":
        args = " ".join(shlex.quote(a) for a in _linux_bwrap_args(own, install))
        return f"bwrap {args} /bin/bash -c {shlex.quote(command)}"
    return None


def reset_probe() -> None:
    """Test hook: forget the cached verdict."""
    global _probe_cache
    _probe_cache = None
