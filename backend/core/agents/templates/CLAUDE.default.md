# {{agent_name}} — CLAUDE.md

Mirror of AGENTS.md — see that file in the same folder for the agent's full operating instructions.

## Identity

- **Agent ID**: {{agent_id}}
- **Workspace**: {{workspace_root}}

## Quick reference

- Workspace: `{{workspace_root}}` — private to one account (`…/users/<user id>/…`); never read or write another `users/<id>/` tree.
- Your user is the account in the system prompt's **Who you are working for** block. Introduce yourself with it, and say you cannot see another account's files when asked (`whoami` is the server's account, not theirs).
- User uploads (knowledge): `upload/`; deliverables: `generated/`; scratch/misc: `other/`.
- Skills live at `/skills/<source>/<skill-id>/SKILL.md` (from the catalogue in your prompt — not in this workspace).
- After producing a deliverable, summarize what you created and where it was saved.
