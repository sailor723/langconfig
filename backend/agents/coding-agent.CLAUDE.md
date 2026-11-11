# Coding Agent（编码智能体） — CLAUDE.md

Mirror of AGENTS.md — see that file in the same folder for the agent's full operating instructions.

## Identity

- **Agent ID**: 372
- **Workspace**: /Users/weiping/dev/Learn/langchain-ai/langconfig/backend/outputs/users/1/langconfig-test/agents/agent_372

## Quick reference

- Workspace: `/Users/weiping/dev/Learn/langchain-ai/langconfig/backend/outputs/users/1/langconfig-test/agents/agent_372` — private to one account (`…/users/<user id>/…`); never read or write another `users/<id>/` tree.
- Your user is the account in the system prompt's **Who you are working for** block. Introduce yourself with it, and say you cannot see another account's files when asked (`whoami` is the server's account, not theirs).
- User uploads (knowledge): `upload/`; deliverables: `generated/`; scratch/misc: `other/`.
- Skills live at `/skills/<source>/<skill-id>/SKILL.md` (from the catalogue in your prompt — not in this workspace).
- **File tools** (`read_file` / `write_file` / `edit_file` / `grep` / `glob`) are rooted at the
  workspace and cannot reach outside it. **`bash` is the host shell** — it can, and that is how
  you read, edit and test the repository the user points you at. The limit is the *account*
  (`…/users/<id>/…`), never the repository: `git status` before an edit, `git diff` after.
- After producing a deliverable, summarize what you created and where it was saved.
- **Never restart the stack from inside a turn.** You run *inside* the backend on `:8765`, and
  `./start.sh` (or `pkill -f main.py`, `kill $(lsof -ti:8765)`) kills that listener — i.e. the
  process hosting your own turn. The turn dies mid-tool, the user sees a spinner then
  "Load failed", and LangGraph re-runs the unfinished tool call on the next message, so every
  new message kills the backend again. Ask the user to run the restart in their terminal and
  give them the exact command; if an `:8765` call comes back empty or `000`, stop and report.

