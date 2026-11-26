# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Workspace-scoped FilesystemBackend.

The deepagents ``FilesystemBackend`` in ``virtual_mode`` treats EVERY incoming
path as a virtual path under the workspace root. When an agent passes an
absolute path it learned from its identity block (e.g.
``/Users/.../outputs/agents/agent_186/generated/report.md``), the SDK resolves
it as ``<workspace>/Users/.../generated/report.md`` — creating a nested
``Users/...`` directory tree inside the workspace.

This subclass re-bases any absolute path that lies *inside* the workspace root
back to a virtual relative path, so ``write_file``/``read_file``/``ls`` with
the absolute workspace path behave identically to the relative form.
"""

from pathlib import Path

from deepagents.backends.filesystem import FilesystemBackend
from deepagents.backends.local_shell import LocalShellBackend


class WorkspaceFilesystemBackend(FilesystemBackend):
    """FilesystemBackend that accepts absolute paths under the workspace root.

    Absolute paths are normalized to virtual paths relative to the backend's
    ``root_dir`` (the agent workspace) before the SDK resolves them, so the
    agent can use either the absolute workspace path or the relative form.
    Paths outside the workspace root are rejected (security: the agent must
    stay inside its workspace).
    """

    def _resolve_path(self, key: str) -> Path:
        # "/" is the SDK's virtual root (== the workspace root) — pass through
        # untouched so ls("/")/read("/…") keep working as before.
        if not key or key == "/":
            return super()._resolve_path(key)
        # Re-base absolute paths that fall inside the workspace root so an
        # agent that passes its real absolute workspace path (from the
        # identity block) writes into the workspace instead of a nested
        # <workspace>/Users/... tree.
        if Path(key).is_absolute():
            resolved_key = Path(key).resolve()
            try:
                rel = resolved_key.relative_to(self.cwd)
            except ValueError:
                # Not a real path under the workspace. Two cases:
                #  1. SDK virtual path ("/generated", "/skills/...") — the SDK
                #     resolves these UNDER the workspace root (virtual_mode),
                #     so pass through unchanged.
                #  2. A real absolute path elsewhere — virtual_mode still maps
                #     it under the workspace and blocks traversal ("..", "~"),
                #     so it cannot escape; pass through and let the SDK fail
                #     gracefully if the target doesn't exist.
                return super()._resolve_path(key)
            # Virtual absolute path: "/generated/report.md" (the SDK prepends
            # "/" itself when the key does not start with one). The workspace
            # root itself maps to the virtual root "/".
            key = "/" + rel.as_posix() if rel.as_posix() != "." else "/"
        return super()._resolve_path(key)


class WorkspaceShellBackend(LocalShellBackend):
    """LocalShellBackend whose file tools accept the REAL absolute workspace path.

    The sandbox backend has the same defect the filesystem one had, and it is worse there because every agent
    that runs scripts uses it: `LocalShellBackend._resolve_path` treats every path as virtual, so an absolute
    path the agent knows from its identity block
    (`/Users/…/agents/agent_352/generated/doc_demo/ANALYSIS.md`) lands at
    `<workspace>/Users/…/agents/agent_352/generated/doc_demo/ANALYSIS.md` — nested, invisible to a later
    `ls generated/`, and reported back as "Updated file …". Measured: a Mock Data Agent wrote its 16 KB
    analysis there, then could not find it, then answered from memory.

    `execute` runs with the workspace as its cwd and real absolute paths mean what they say. Only the file
    tools (`read_file`/`write_file`/`edit_file`/`ls`/`glob`/`grep`) re-base, which is exactly where the
    identity-block path was being mangled — **plus one exception on `execute`**: a command that opens its own
    database connection is refused (see `core.tools.db_guard` and
    `docs/system-architecture/ontology-agent-boundaries.md`). Measured 2026-11-25: agent 393 ran `psql -lqt`
    and `psql -c "SELECT … information_schema …"` from this shell while the prompt said not to; the tools were
    bound, the shell was simply a second unguarded door.
    """

    def execute(self, command: str, *, timeout: int | None = None):  # type: ignore[override]
        """Refuse DB-connection commands; everything else runs exactly as before.

        The refusal is returned as a normal `ExecuteResponse` (non-zero exit) rather than raised, so the model
        sees it as tool output and can switch to `db_query_agent` / `db_describe` in the same turn.
        """
        from core.tools.db_guard import refusal
        from deepagents.backends.protocol import ExecuteResponse

        blocked = refusal(command or "")
        if blocked is not None:
            return ExecuteResponse(output=blocked, exit_code=126, truncated=False)
        result = super().execute(command, timeout=timeout)
        return _cap_output(result, ExecuteResponse)

    def _resolve_path(self, key: str) -> Path:
        if not key or key == "/":
            return super()._resolve_path(key)
        if Path(key).is_absolute():
            try:
                rel = Path(key).resolve().relative_to(self.cwd)
            except ValueError:
                # not inside the workspace: leave the SDK's own checks in charge
                return super()._resolve_path(key)
            key = "/" + rel.as_posix() if rel.as_posix() != "." else "/"
        return super()._resolve_path(key)

#: A shell result longer than this is cut before it enters the model's context.
#:
#: Measured on one ontology build (2026-11-26): 151 `execute` results carried 325,712 characters
#: — 88% of every tool result in the turn — and the five biggest were `cat gate.py` (18,545),
#: `sed 02-meaning.ttl` (12,863), `ls -la` (10,448). Every one of them enters the context and is
#: re-sent on every later model call, so the cost grows with the context, not with the work. The
#: cap keeps the head (where a command's answer usually is) and the tail (where errors print),
#: states the exact truncation, and names the door for the rest: `read_file` with offset/limit.
_EXECUTE_OUTPUT_CAP = 8000
_EXECUTE_OUTPUT_HEAD = 5000


def _cap_output(result, response_cls):
    """Cut an oversized shell result, keeping head and tail and saying what was lost."""
    text = getattr(result, "output", "") or ""
    if len(text) <= _EXECUTE_OUTPUT_CAP:
        return result
    tail_len = _EXECUTE_OUTPUT_CAP - _EXECUTE_OUTPUT_HEAD
    clipped = (
        text[:_EXECUTE_OUTPUT_HEAD]
        + f"\n\n… [{len(text) - _EXECUTE_OUTPUT_CAP:,} characters cut from the middle of "
          f"{len(text):,}] …\n\n"
        + text[-tail_len:]
        + f"\n\n[shell output truncated at {_EXECUTE_OUTPUT_CAP:,} characters — narrow the command "
          f"(grep -c / head -n / a tighter pattern), or read the file with `read_file` "
          f"(offset/limit); do not re-run it verbatim to see the rest]"
    )
    return response_cls(output=clipped, exit_code=getattr(result, "exit_code", 0), truncated=True)

