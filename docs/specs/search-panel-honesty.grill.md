# Grill round 1 — search panel (answered, frontier empty)

Scope: the left-sidebar search panel (`src/components/layout2/SearchPanel.tsx`, mounted at
`LeftSidebar.tsx:232`).
Frontier: empty — all five answered 2026-11-09 ("agree your idea" = each recommendation accepted).
Facts established before asking (so none of these are questions): the panel's docstring claims
"search-in-files"; it calls `listWorkflows()` then `getWorkflowCode()` per workflow (N+1); the three
candidate search endpoints 404; the replace field is bound to state and used by nothing; two empty
`catch` blocks swallow failures.

| # | Question | Recommendation | Answer |
|---|---|---|---|
| Q1 | Keep the panel, or remove it and its sidebar entry? | keep — it is used; the bug is the behaviour | **keep** |
| Q2 | What should it search: workflow code only, workflow code + workspace files (server-side, one request), or everything? | workflow code + workspace files, **server-side**, one request | **workflow definitions + workspace text files, server-side, one request** |
| Q3 | The replace field does nothing. Drop it, wire it, or label it "coming"? | drop it | **drop it** |
| Q4 | Show failures, or keep the silent empty list? | show the HTTP status in one line | **show the HTTP status in one line** |
| Q5 | Clicking a match: open the file, or open and jump to the line? | open and jump where the viewer supports it | **open and jump where the viewer supports it** |

When all five are answered, the decisions move into
[`search-panel-honesty.md`](search-panel-honesty.md) with `Status: agreed`, and the tickets stop being
provisional.
