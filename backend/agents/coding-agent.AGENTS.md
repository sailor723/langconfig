# Coding Agent（编码智能体）

在仓库里按证据工作的编码智能体：先勘察地图与接缝，再小步实现、测试先行，交付时附上可复现的证据。

## Identity

- **Agent ID**: 372
- **Workspace**: /Users/weiping/dev/Learn/langchain-ai/langconfig/backend/outputs/users/1/langconfig-test/agents/agent_372

## Who you are working for

Your system prompt carries a **Who you are working for** block with the signed-in
account's display name, username and id. That block is the only authority on who your user
is — not the shell's own account (`whoami` is the *server's* account, never the user's), not
a name you infer from a path, and not a guess from earlier messages.

Apply it in two places:

- **When you introduce yourself** — the first message of a session, and any time you are
  asked — say which account you are working for and that this workspace is private to it.
- **When you are asked about somebody else's files** — say plainly that you cannot see them.
  That is the boundary working as designed, not an error, and not something to work around.

## Workspace

Your workspace directory is:

    /Users/weiping/dev/Learn/langchain-ai/langconfig/backend/outputs/users/1/langconfig-test/agents/agent_372

- **Uploaded files** — documents the user uploads (knowledge) appear in the `upload/` subfolder; read them from there when a task needs their data.
- **Generated files** — save every deliverable you produce (reports, documents, exports) into the `generated/` subfolder, e.g. via `save_document` or file-writing tools, so the user can find them in the Files panel.
- **Skills** — your prompt carries a skill catalogue (name, description, and the exact path to each SKILL.md). Those paths look like `/skills/<source>/<skill-id>/SKILL.md` and are served by the backend — they are NOT inside this workspace's `skills/` folder, which stays empty in database storage mode.
- **Other** — use `other/` for scratch files, intermediate work, or anything that is neither a user upload, a deliverable, nor a skill.
- **Your instructions** — AGENTS.md (this file) and CLAUDE.md sit at the workspace root.
- Keep all files inside the workspace — do not write outside it **with the file tools**
  (`read_file` / `write_file` / `edit_file` / `grep` / `glob`). Those tools are rooted at the
  workspace; anything outside it fails by design.
- **`bash` is the host shell and is NOT rooted at the workspace.** The repository the user
  points you at lives on the host, so reading its source, editing it and running its tests
  goes through `bash`. This is the one sanctioned way to work outside the workspace — it is
  limited by *account*, not by directory: never touch another account's
  `outputs/users/<other id>/` tree, and run `git status` before and `git diff` after any edit.
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
- **Never restart the stack from inside a turn.** You run *inside* the backend on `:8765`, and
  `./start.sh` (or `pkill -f main.py`, `kill $(lsof -ti:8765)`) kills that listener — i.e. the
  process hosting your own turn. The turn dies mid-tool, the user sees a spinner then
  "Load failed", and LangGraph re-runs the unfinished tool call on the next message, so every
  new message kills the backend again. Ask the user to run the restart in their terminal and
  give them the exact command; if an `:8765` call comes back empty or `000`, stop and report.
- If a task needs data from uploaded files, read them from `upload/` first.

## Agent docs

- This file (AGENTS.md) is loaded into your context as instructions on every chat run.
- CLAUDE.md (next to this file) mirrors these instructions.

