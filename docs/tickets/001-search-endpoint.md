# 001 — A workspace search endpoint

Spec: docs/specs/search-panel-honesty.md#AC1, AC2      Status: **done** (2026-11-09) · 10 tests      Blocked by: (none — on the frontier)      Size: M

## Delivers

`GET /api/workspace/search?q=<term>` answers with matches (file, line, column, snippet) across workflow
code and workspace text files, in one request, bounded by a scan cap. A caller can search the workspace
like `grep` without knowing which file to open.

## Acceptance (what a validator will check)

- [x] `curl -s "http://127.0.0.1:8765/api/workspace/search?q=monthly_sales"` → 200 with at least one match
      whose `kind` is `file` and whose path is inside this account's workspace (AC1) — **done 2026-11-09**
- [x] the response carries `scanned.files`, `scanned.workflows` and `truncated` (AC1) — **done**
- [x] `curl -s -o /dev/null -w '%{http_code}' ".../api/workspace/search?q="` → **400** (AC2) — done
- [x] a 201-character `q` → **413**, raised before any scan (AC2) — done
- [x] the route takes **no path input at all**, so traversal cannot be attempted; pinned by
      `test_a_query_cannot_reach_outside_the_workspace` — done
- [x] `MAX_MATCHES=200` / `MAX_FILES_SCANNED=5_000` / `MAX_FILE_BYTES=256 KiB` are named constants and the
      response says `truncated: true` when they bite — done (`tests/test_workspace_search.py`, 10 passed)

## Not in this ticket

The panel rewrite, the replace-control removal, the error surface — 002.

## Notes

Reuse the path guard already in `api/workspace/files_routes.py` (used by `/by-path`). Text extensions only
(`.py .ts .tsx .js .md .json .sql .yml .yaml .toml .css .html`), skip binaries and anything over the
per-file byte cap.
