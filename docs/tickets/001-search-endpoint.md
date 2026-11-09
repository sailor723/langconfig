# 001 — A workspace search endpoint

Spec: docs/specs/search-panel-honesty.md#AC1, AC2, AC6      Blocked by: (none — on the frontier)      Size: M

## Delivers

`GET /api/workspace/search?q=<term>` answers with matches (file, line, column, snippet) across workflow
code and workspace text files, in one request, bounded by a scan cap. A caller can search the workspace
like `grep` without knowing which file to open.

## Acceptance (what a validator will check)

- [ ] `curl -s "http://127.0.0.1:8765/api/workspace/search?q=SearchPanel"` → 200 with at least one match whose `file` ends `.tsx` (AC1)
- [ ] `curl -s -o /dev/null -w '%{http_code}' ".../api/workspace/search?q="` → 400 (AC2)
- [ ] a 5 000-character `q` → 413, and the route body shows no file was opened (AC2)
- [ ] the handler stays inside the workspace roots: a crafted `q` cannot make it read `../../.env` (test named `test_search_refuses_paths_outside_the_workspace`)
- [ ] matches are capped (constant named, e.g. `MAX_MATCHES`) and the response says when it truncated

## Not in this ticket

The panel rewrite, the replace-control removal, the error surface — 002.

## Notes

Reuse the path guard already in `api/workspace/files_routes.py` (used by `/by-path`). Text extensions only
(`.py .ts .tsx .js .md .json .sql .yml .yaml .toml .css .html`), skip binaries and anything over the
per-file byte cap.
