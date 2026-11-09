# Validation report — search panel honesty

Criterion source: `docs/specs/search-panel-honesty.md` (AC1–AC6), written from grill round 1's
**recommended** answers — the round is still open (`search-panel-honesty.grill.md`).
Validated: 2026-11-09, against the working tree at that moment and the running app on `:8765`.

**Run 2** (same day, after ticket 001 landed). Run 1 was the baseline — *nothing implemented, six FAILs* —
which is what makes a later PASS mean something: a validator that passes an unimplemented spec is broken.
The report is rewritten in place so a reader sees one table, and the delta is stated at the bottom.

| # | Criterion | Verdict | Evidence |
|---|-----------|---------|----------|
| AC1 | `GET /api/workspace/search?q=<term>` returns 200 with matches, `scanned` and `truncated` | **PASS** | `curl "…/api/workspace/search?q=monthly_sales"` → **200**, 1 match `default/analyze_sales_full.py:19` (`kind: file`); `?q=prompt` → 57 `kind: workflow` matches; response carries `scanned={files:3166, workflows:57}`; `?q=tool_call` → 200 matches with `truncated: true` |
| AC2 | empty `q` → 400, over-long `q` → 413 | **PASS** | `?q=` (whitespace) → **400** `q is required`; `?q=` + 201 chars → **413** naming the 200-char cap; both raised before the filesystem is touched (`test_empty_query_is_400`, `test_absurd_query_is_413`) |
| AC3 | one request per search, no per-workflow fan-out | **FAIL** | `grep -c 'getWorkflowCode(' src/components/layout2/SearchPanel.tsx` → **1** (the call inside the loop at `:68`); `listWorkflows()` at `:57` |
| AC4 | a failed request shows the HTTP status | **FAIL** | `grep -c 'No results on error\|Skip workflows' …` → **2** (empty `catch` at `:88-90`, `:95-97`); the panel renders an empty list either way |
| AC5 | replace control gone; no "Mock search results" comment | **FAIL** | `grep -c replaceText` → **2** (state at `:39`, input at `:185`, no action); `grep -c 'Mock search results'` → **1** (`:13`) |
| AC6 | docstring matches behaviour | **FAIL** | `:2` still reads *"VS Code-style search-in-files sidebar panel"* while `:57-68` search workflow code via a per-workflow fan-out |

**PASS 2 · FAIL 4 · PARTIAL 0 · UNVERIFIABLE 0**

## Delta since run 1

`AC1` 404 → **200 with matches**; `AC2` 404 → **400 / 413**. Both are ticket 001, which is now done
(`docs/tickets/001-search-endpoint.md`, 10 tests in `backend/tests/test_workspace_search.py`).
AC3–AC6 remain **FAIL** because they are ticket 002 — the panel still calls `getWorkflowCode` per
workflow, still hides failures, still offers a dead replace field. Nothing about 001 pretending to be 002:
that is the point of a verdict per criterion.

## Baseline that makes a later PASS meaningful

- `npx tsc --noEmit` → exit **0** today, so "tsc still exits 0" is a fair regression check, not a
  moving target.
- `./scripts/housekeeping_verify.sh` → 845 guards pass today (recorded in `HOUSEKEEPING.md` §7).

## Open questions

None of the criteria are unverifiable — which is itself the test that the criteria were written
correctly. Every one of them has a command whose output is a verdict.

## Amendments applied to the criteria

- **A1** (spec): "workflow code" became "workflow definition" — code generation per workflow is the cost
  being removed. AC1's evidence therefore cites `kind: "workflow"` matches from definition JSON.
- **A2** (spec): "files" means the account's workspace (`user_base()`), not the application source, so a
  search for a symbol in `src/` correctly returns nothing. AC1's evidence uses a term that exists in the
  workspace.

## Not checked (on purpose)

- Jumping to a matched line (AC of ticket 003) is not in the spec's AC table yet, because D5 is
  provisional until Q5 is answered.
- Notebook/PDF/Office content search: out of scope by the spec.
