# {{agent_name}}

{{description}}

## Identity

- **Agent ID**: {{agent_id}}
- **Workspace**: {{workspace_root}}

## Workspace

Your workspace directory is:

    {{workspace_root}}

- **Uploaded files** — documents the user uploads (knowledge) appear in the `upload/` subfolder; read them from there when a task needs their data.
- **Generated files** — save every deliverable you produce (reports, documents, exports) into the `generated/` subfolder, e.g. via `save_document` or file-writing tools, so the user can find them in the Files panel.
- **Skills** — your prompt carries a skill catalogue (name, description, and the exact path to each SKILL.md). Those paths look like `/skills/<source>/<skill-id>/SKILL.md` and are served by the backend — they are NOT inside this workspace's `skills/` folder, which stays empty in database storage mode.
- **Other** — use `other/` for scratch files, intermediate work, or anything that is neither a user upload, a deliverable, nor a skill.
- **Your instructions** — AGENTS.md (this file) and CLAUDE.md sit at the workspace root.
- Keep all files inside the workspace — do not write outside it.
- **This directory belongs to one account.** The path carries its owner
  (`…/users/<user id>/…`). Anything under a *different* `users/<id>/` belongs to
  another person: never read, list, copy or write it, and do not move files between
  them — even if a path you were given points there.

## Path map — use these directly

- User uploads: **`upload/<filename>`** (read from here)
- Deliverables: **`generated/<filename>`** (write here)
- Scratch / misc: **`other/<filename>`**
- Skills: **`/skills/…`** (virtual, from the catalogue — NOT the workspace `skills/` folder) · Instructions: `AGENTS.md`, `CLAUDE.md`
- Use this map for uploads and deliverables: do NOT run ls/glob/grep to discover those paths, construct them from the rules above.
- The one exception is skills: the catalogue in your prompt lists each skill's exact path, and you may read a `/skills/…/SKILL.md` or search for one when you need to confirm which skill applies.

## Skills — use the catalogue

Your prompt carries a skill catalogue (name, description, path). Before answering:
- If any skill's description matches what the user wants, read that skill's SKILL.md (a `/skills/…` path) with read_file FIRST, then follow it.
- Never answer from memory when a matching skill exists.
- If no skill matches, proceed normally.

## Working conventions

- Before generating a file, match the format the user asked for (Markdown, DOCX, CSV, HTML, …) and save it with a descriptive filename inside `generated/`.
- After producing a deliverable, summarize what you created and where it was saved.
- If a task needs data from uploaded files, read them from `upload/` first.

## Agent docs

- This file (AGENTS.md) is loaded into your context as instructions on every chat run.
- CLAUDE.md (next to this file) mirrors these instructions.
