# Validation report — search panel honesty

Criterion source: `docs/specs/search-panel-honesty.md` (AC1–AC6), written from grill round 1's
**recommended** answers — the round is still open (`search-panel-honesty.grill.md`).
Validated: 2026-11-09, against the working tree at that moment and the running app on `:8765`.

This is the **baseline run**: nothing has been implemented yet, so every criterion that requires the new
behaviour must FAIL. That is the point of running it first — a validator that passes an unimplemented
spec is broken.

| # | Criterion | Verdict | Evidence |
|---|-----------|---------|----------|
| AC1 | `GET /api/workspace/search?q=<term>` returns 200 with matches | **FAIL** | `curl -s -o /dev/null -w '%{http_code}' "…/api/workspace/search?q=SearchPanel"` → **404**: the route does not exist |
| AC2 | empty `q` → 400, over-long `q` → 413 | **FAIL** | same route: `q=` → **404**, so no validation can happen |
| AC3 | one request per search, no per-workflow fan-out | **FAIL** | `grep -c 'getWorkflowCode(' src/components/layout2/SearchPanel.tsx` → **1** (the call inside the loop at `:68`); `listWorkflows()` at `:57` |
| AC4 | a failed request shows the HTTP status | **FAIL** | `grep -c 'No results on error\|Skip workflows' …` → **2** (empty `catch` at `:88-90`, `:95-97`); the panel renders an empty list either way |
| AC5 | replace control gone; no "Mock search results" comment | **FAIL** | `grep -c replaceText` → **2** (state at `:39`, input at `:185`, no action); `grep -c 'Mock search results'` → **1** (`:13`) |
| AC6 | docstring matches behaviour | **FAIL** | `:2` still reads *"VS Code-style search-in-files sidebar panel"* while `:57-68` search workflow code via a per-workflow fan-out |

**PASS 0 · FAIL 6 · PARTIAL 0 · UNVERIFIABLE 0**

## Baseline that makes a later PASS meaningful

- `npx tsc --noEmit` → exit **0** today, so "tsc still exits 0" is a fair regression check, not a
  moving target.
- `./scripts/housekeeping_verify.sh` → 845 guards pass today (recorded in `HOUSEKEEPING.md` §7).

## Open questions

None of the criteria are unverifiable — which is itself the test that the criteria were written
correctly. Every one of them has a command whose output is a verdict.

## Not checked (on purpose)

- Jumping to a matched line (AC of ticket 003) is not in the spec's AC table yet, because D5 is
  provisional until Q5 is answered.
- Notebook/PDF/Office content search: out of scope by the spec.
