# Search panel: make it do what it says

Status: **agreed** (2026-11-09 — the five recommendations were accepted).
Decisions from: [`search-panel-honesty.grill.md`](search-panel-honesty.grill.md) round 1. Author: agent.

## Problem

`SearchPanel` is mounted in the left sidebar (`src/components/layout2/LeftSidebar.tsx:232`) and its own
docstring calls it a **"VS Code-style search-in-files sidebar panel"**
(`src/components/layout2/SearchPanel.tsx:2`). Three things it does not do:

1. **It searches workflows, not files.** `handleSearch` calls `apiClient.listWorkflows()`
   (`SearchPanel.tsx:57`) and then `apiClient.getWorkflowCode(wfId)` **once per workflow**
   (`:68`) — an N+1 fan-out over the network — and greps those strings in the browser.
2. **It has no server-side search.** `GET /api/workspace/search` and `GET /api/files?q=` both answer
   **404** (checked against the running app, 2026-11-09). The files API offers a list
   (`/api/workspace/files`) and single-file content (`/api/workspace/by-path/content`), not a search.
3. **It hides its failures.** A workflow that cannot be read is skipped with an empty `catch`
   (`:88-90`) and a failed request leaves the list empty with no message (`:95-97`). A reader cannot
   tell "no matches" from "the backend is down".
4. A **replace** field exists and does nothing: `replaceText` (`:39`) is only ever read by the input
   (`:185`) — there is no replace action at all, and a stale comment still says
   `// ── Mock search results for demo` (`:13`).

## Decisions

| # | Decision | Why | Source |
|---|---|---|---|
| D1 | Keep the panel; fix the behaviour instead of removing it | a sidebar search is used; removing it loses a feature people reach for | grill Q1 → recommended (a) |
| D2 | Search **workspace text files + workflow definitions**, server-side, in **one** request | the N+1 fan-out is the actual cost, and "search-in-files" is the promise in the docstring | grill Q2 → answered (b) + amendment A1 |
| D3 | Drop the replace field entirely | it never worked; a control that does nothing is worse than an absent one | grill Q3 → recommended (a) |
| D4 | Show a one-line error with the HTTP status instead of an empty list | "no matches" and "backend down" must not look the same | grill Q4 → recommended (a) |
| D5 | Clicking a match opens the file and jumps to the line if the viewer can; otherwise opens it | jumping is the reason to search rather than browse | grill Q5 → recommended (a) |

## Scope

**In:** one server endpoint that searches (workflow code + workspace text files), the panel switched to
it, the replace control removed, an error surface, the docstring/comment corrected, and a test for the
endpoint.

**Out (deliberately):** regex search, case-sensitivity toggle, whole-word, multi-file replace,
search-in-PDF/Office contents (binary text extraction is a different feature), search over the ontology
TTL (the ontology workbench has its own query surface), result ranking, and search history.

## Acceptance criteria

| # | Criterion | How it will be checked |
|---|---|---|
| AC1 | `GET /api/workspace/search?q=<term>` returns `{matches: [...]}` with file, line, column, snippet and `kind`, plus `scanned` counts and a `truncated` flag | `curl` against the running app: a term present in this account's workspace returns 200 with matches (`kind:"file"` or `kind:"workflow"`); the response carries `scanned.files`/`scanned.workflows` |
| AC2 | The endpoint refuses an empty `q` with 400 and an over-long `q` with 413, without scanning | `curl` with `q=` → 400; with a 5 000-char query → 413 |
| AC3 | A search does **one** HTTP request, not one per workflow | grep `SearchPanel.tsx` for `getWorkflowCode(` → 0 hits; the panel calls the search endpoint once per query |
| AC4 | A failed request shows the HTTP status in the panel | a test or a temporary forced 500 shows the message, not an empty list |
| AC5 | The replace control is gone and no comment still says "Mock search results" | `grep -c "replaceText" src/components/layout2/SearchPanel.tsx` → 0; `grep -c "Mock search results" → 0` |
| AC6 | Component docstring matches behaviour | `grep -n "search-in-files" src/components/layout2/SearchPanel.tsx` shows the file+workflow wording, not a claim of file contents only |

## Risks and reversibility

The endpoint reads files: it must stay inside the workspace roots (the same guard `files_routes.py` uses
for `/by-path`), cap the bytes it scans, and cap returned matches. Reversibility is cheap — the panel is
one component and the endpoint is one route; reverting is a `git revert` with no data migration.

## Amendments

**A1 — 2026-11-09, found while implementing ticket 001.** D2 says "workflow code"; the honest source is
the workflow **definition** (`blueprint` + `configuration`), because `GET /api/workflows/{id}/code` runs
the LangGraph code generator — calling it once per workflow per keystroke is precisely the N+1 cost this
ticket exists to remove. The endpoint therefore scans the definition JSON, tagged `kind: "workflow"`, and
says so here rather than silently searching something narrower than the spec promised.

**A2 — 2026-11-09.** "Files" means the **account's workspace** (`user_base()`), not the application's own
source tree. A search for a symbol in `src/` therefore finds nothing, by design: the panel searches the
files the user can open, and the app's source is not one of them.

## What would change this spec

- If a search endpoint already exists somewhere (it does not today: the three candidates 404), AC1
  becomes "call it".
- If the file viewer cannot jump to a line, D5's second half becomes the whole of D5.
- If the panel is not actually mounted on the deployment (it is, `LeftSidebar.tsx:232`), D1 would be
  reconsidered as "remove".
