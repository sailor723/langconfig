# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Agent identity block — the single source of truth for "who am I / where is my
workspace".

The identity block is a small Markdown section appended to an agent's
``system_prompt`` and persisted **with the real values baked in** (numeric
agent id + resolved workspace root) into the PostgreSQL ``config`` JSONB. The
same values are baked into the agent's instruction docs (AGENTS.md / CLAUDE.md)
stored in ``deep_agent_templates.agent_docs``.

Why this exists: agents historically did not know their own identity or
workspace — they guessed by querying ``pg_get_agent`` and wrote self-invented
identity blocks into AGENTS.md that were wrong for the next session. This
module fixes the root cause by injecting identity into the system prompt and
docs.

The workspace root is resolved once at creation/backfill time via
``WorkspaceManager.resolve_agent_workspace`` (legacy ``outputs/agents/agent_{id}/``
for agents without a project binding or custom ``workspace_path``).
"""

# Marker used for idempotency checks (creation hooks + batch backfill skip
# prompts that already carry a block).
IDENTITY_MARKER = "## Identity"

import re

# Tokens from earlier block versions that must be upgraded away (v1 carried
# {{category}} + {{agent_name}}; v2 carried {{description}} + {{agent_name}};
# placeholder versions carried {{agent_id}} / {{workspace_root}}).
_LEGACY_TOKENS = (
    "{{agent_id}}",
    "{{agent_name}}",
    "{{description}}",
    "{{category}}",
    "{{workspace_root}}",
)


def identity_block(agent_id, workspace_root: str) -> str:
    """The identity block with real values baked in."""
    return (
        "## Identity\n\n"
        f"- **Agent ID**: {agent_id}\n"
        f"- **Workspace**: {workspace_root}\n\n"
        f"You are agent {agent_id}. Your workspace root is\n"
        f"{workspace_root}; save every deliverable you produce inside it\n"
        f"(prefer the `generated/` subfolder when present).\n"
    )


def build_identity_system_prompt(
    base_prompt: str,
    agent_id,
    workspace_root: str,
    docs: dict,
) -> str:
    """Build the full system prompt stored in PostgreSQL.

    Base prompt + identity block (real id + workspace) + the agent's
    instruction docs (AGENTS.md / CLAUDE.md) embedded inline, so the agent can
    quickly compile its role, workspace, and operating rules from the prompt
    alone — no need to read files first.

    The docs are re-baked with the resolved workspace root before embedding
    (``refresh_doc_identity``): the stored copies may carry the creation-time
    (legacy) path, which would otherwise contradict the identity block.
    """
    parts = [base_prompt or ""]
    parts.append(identity_block(agent_id, workspace_root))
    for name in ("AGENTS.md", "CLAUDE.md"):
        content = (docs or {}).get(name)
        if content:
            content = refresh_doc_identity(content, agent_id, workspace_root)
            parts.append(f"## {name} (embedded)\n\n{content}")
    return "\n\n".join(p for p in parts if p and p.strip())


def first_chat_greeting(workspace_root: str) -> str:
    """Instruction appended to the system prompt on the first message of a
    new chat session: introduce yourself + report workspace status."""
    return (
        "\n\n## First message — introduce yourself\n\n"
        "This is the first message of a new chat session. Before answering "
        "the user's request, briefly:\n"
        "- Introduce yourself (agent name and id).\n"
        f"- Report the current workspace status: what is in `{workspace_root}` "
        "(uploads in `upload/`, existing deliverables in `generated/`, skills "
        "in `skills/`).\n"
        "- Keep it concise and in the user's language.\n"
    )


def refresh_doc_identity(content: str, agent_id, workspace_root: str) -> str:
    """Re-bake the workspace root inside an agent instruction doc (AGENTS.md /
    CLAUDE.md) so the materialized copy matches the CURRENT session's resolved
    workspace.

    Stored docs (``deep_agent_templates.agent_docs``) are authored once — often
    at creation, when no project is bound, so the legacy root
    ``outputs/agents/agent_{id}/`` is baked in. The workspace root is
    project-bound and changes per session, so the on-disk copy must be
    refreshed at materialization time — the doc analogue of the system-prompt
    identity re-bake (``api/chat/messages.py``).

    Only the two lines the default docs emit are rewritten: the identity
    ``- **Workspace**:`` line and the indented absolute-path code block under
    ``## Workspace``. All other content (user-authored instructions, relative
    path map, …) is preserved verbatim. Idempotent and safe on docs without a
    baked root.
    """
    if not content or not workspace_root:
        return content
    out = re.sub(
        r"(?m)^- \*\*Workspace\*\*: .*$",
        f"- **Workspace**: {workspace_root}",
        content,
    )
    out = re.sub(
        r"(?m)^- Workspace: `.*`$",
        f"- Workspace: `{workspace_root}`",
        out,
    )
    out = re.sub(
        r"(?m)^    (?:/|[A-Za-z]:[\\/]).*$",
        f"    {workspace_root}",
        out,
    )
    return out


def _strip_identity_block(system_prompt: str) -> str:
    """Remove any existing identity block (from ``## Identity`` to the end).

    The block is always appended last, so truncating at the marker is safe.
    Returns the prompt without the block (trailing whitespace trimmed).
    """
    idx = system_prompt.find(IDENTITY_MARKER)
    if idx == -1:
        return system_prompt
    return system_prompt[:idx].rstrip()


def append_identity_block(system_prompt: str, agent_id, workspace_root: str) -> str:
    """Append the identity block (real values) to a system prompt.

    Idempotent: returns the prompt unchanged if it already contains any
    ``## Identity`` block, so repeated calls never double-inject. Used at
    creation time, where the prompt cannot already carry a block.
    """
    prompt = system_prompt or ""
    if IDENTITY_MARKER in prompt:
        return prompt
    sep = "\n\n" if prompt.strip() else ""
    return f"{prompt}{sep}{identity_block(agent_id, workspace_root)}"


def refresh_identity_block(system_prompt: str, agent_id, workspace_root: str) -> str:
    """Replace any existing identity block with the current real-value block.

    Used by the batch backfill: strips any legacy/placeholder block and
    re-appends the block with the real agent id + workspace root baked in.
    No-op for prompts without an identity block.
    """
    prompt = system_prompt or ""
    if IDENTITY_MARKER in prompt:
        prompt = _strip_identity_block(prompt)
        sep = "\n\n" if prompt.strip() else ""
        return f"{prompt}{sep}{identity_block(agent_id, workspace_root)}"
    return prompt


def default_agent_docs(agent, workspace_root: str) -> dict:
    """Sensible default AGENTS.md / CLAUDE.md for agents without authored docs.

    The docs are stored in PostgreSQL (``deep_agent_templates.agent_docs``)
    **with the real agent id + workspace root baked in**, exactly like the
    system prompt, so the agent's instructions are self-describing on every
    run.

    Returns ``{"AGENTS.md": ..., "CLAUDE.md": ...}``.
    """
    name = getattr(agent, "name", None) or f"Agent {getattr(agent, 'id', '')}".strip()
    description = getattr(agent, "description", None) or "An AI agent."
    agent_id = getattr(agent, "id", "?")
    agents_md = (
        f"# {name}\n\n"
        f"{description}\n\n"
        f"## Identity\n\n"
        f"- **Agent ID**: {agent_id}\n"
        f"- **Workspace**: {workspace_root}\n\n"
        f"## Workspace\n\n"
        f"Your workspace directory is:\n\n"
        f"    {workspace_root}\n\n"
        f"- **Uploaded files** — documents the user uploads (knowledge) appear "
        f"in the `upload/` subfolder; read them from there when a task needs "
        f"their data.\n"
        f"- **Generated files** — save every deliverable you produce (reports, "
        f"documents, exports) into the `generated/` subfolder, e.g. via "
        f"`save_document` or file-writing tools, so the user can find them in "
        f"the Files panel.\n"
        f"- **Skills** — the skill catalog is staged into `skills/`; read "
        f"SKILL.md files from there when a task requires a skill.\n"
        f"- **Other** — use `other/` for scratch files, intermediate work, or "
        f"anything that is neither a user upload, a deliverable, nor a skill.\n"
        f"- **Your instructions** — AGENTS.md (this file) and CLAUDE.md sit at "
        f"the workspace root.\n"
        f"- Keep all files inside the workspace — do not write outside it.\n\n"
        f"## Path map — use these directly, do NOT explore\n\n"
        f"- User uploads: **`upload/<filename>`** (read from here)\n"
        f"- Deliverables: **`generated/<filename>`** (write here)\n"
        f"- Scratch / misc: **`other/<filename>`**\n"
        f"- Skills: `skills/…` · Instructions: `AGENTS.md`, `CLAUDE.md`\n"
        f"- NEVER run ls/glob/grep just to discover paths — the brief and this "
        f"map give you everything. Construct file paths from the rules above.\n\n"
        f"## Working conventions\n\n"
        f"- Before generating a file, match the format the user asked for "
        f"(Markdown, DOCX, CSV, HTML, …) and save it with a descriptive "
        f"filename inside `generated/`.\n"
        f"- After producing a deliverable, summarize what you created and "
        f"where it was saved.\n"
        f"- If a task needs data from uploaded files, read them from "
        f"`upload/` first.\n\n"
        f"## Agent docs\n\n"
        f"- This file (AGENTS.md) is loaded into your context as instructions "
        f"on every chat run.\n"
        f"- CLAUDE.md (next to this file) mirrors these instructions.\n"
    )
    claude_md = (
        f"# {name} — CLAUDE.md\n\n"
        f"Mirror of AGENTS.md — see that file in the same folder for the "
        f"agent's full operating instructions.\n\n"
        f"## Identity\n\n"
        f"- **Agent ID**: {agent_id}\n"
        f"- **Workspace**: {workspace_root}\n\n"
        f"## Quick reference\n\n"
        f"- Workspace: `{workspace_root}`\n"
        f"- User uploads (knowledge): `upload/`; deliverables: `generated/`; "
        f"scratch/misc: `other/`; skills: `skills/`.\n"
        f"- After producing a deliverable, summarize what you created and "
        f"where it was saved.\n"
    )
    return {"AGENTS.md": agents_md, "CLAUDE.md": claude_md}
