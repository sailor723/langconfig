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
