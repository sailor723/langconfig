# Validation report — search panel honesty

Criterion source: `docs/specs/search-panel-honesty.md` (AC1–AC6, **agreed** after
`search-panel-honesty.grill.md` round 1).
Validated: 2026-11-09, against the working tree and the running app on `:8765` (local and the deployment).

**Now: run 3 — PASS 6 · FAIL 0.** The table is always the current run; the per-run delta is at the bottom,
because a validator that shows only its final state cannot show that progress was checked rather than
declared.

| # | Criterion | Verdict | Evidence |
|---|-----------|---------|----------|
| AC1 | `GET /api/workspace/search?q=<term>` returns 200 with matches, `scanned` and `truncated` | **PASS** | `curl "…/api/workspace/search?q=monthly_sales"` → **200**, 1 match `default/analyze_sales_full.py:19` (`kind: file`); `?q=prompt` → 57 `kind: workflow` matches; response carries `scanned={files:3166, workflows:57}`; `?q=tool_call` → 200 matches with `truncated: true` |
| AC2 | empty `q` → 400, over-long `q` → 413 | **PASS** | `?q=` (whitespace) → **400** `q is required`; `?q=` + 201 chars → **413** naming the 200-char cap; both raised before the filesystem is touched (`test_empty_query_is_400`, `test_absurd_query_is_413`) |
| AC3 | one request per search, no per-workflow fan-out | **PASS** | `grep -c 'getWorkflowCode(' src/components/layout2/SearchPanel.tsx` → **0**; the panel makes **one** call — `apiClient.get('/api/workspace/search', { params: { q } })` — behind a 300 ms debounce |
| AC4 | a failed request shows the HTTP status | **PASS** | both `catch` paths now set an error block rendered with `HTTP <status>` + the server's `detail`; a no-response failure reads "the backend did not answer". `grep -c 'No results on error\|Skip workflows'` → **0** |
| AC5 | replace control gone; no "Mock search results" comment | **PASS** | `grep -c replaceText` → **0**; `grep -c 'Mock search results'` → **0** |
| AC6 | docstring matches behaviour | **PASS** | the header names workspace files + workflow definitions ("workspace files" ×3, "search-in-files" → **0**), and states the rule the bug violated: the panel asks once, the server answers |

**PASS 6 · FAIL 0 · PARTIAL 0 · UNVERIFIABLE 0**

## Delta per run

| Run | When | PASS | FAIL | What moved |
|---|---|---|---|---|
| 1 | before any ticket — the baseline | 0 | 6 | nothing implemented; **a validator that passes an unimplemented spec would be broken**, which is why this run exists |
| 2 | after ticket 001 | 2 | 4 | AC1 404 → 200 with matches; AC2 404 → 400/413 |
| 3 | after ticket 002 | **6** | **0** | AC3 fan-out → one request; AC4 silent → visible status; AC5 dead replace control → gone; AC6 docstring → true |

Tickets: `001` (endpoint, 10 tests) and `002` (panel) are done; `003` (jump to the matched line) is still
blocked-by-002 and now unblocked. Its criterion is not in this table yet, so nothing here claims it.

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
