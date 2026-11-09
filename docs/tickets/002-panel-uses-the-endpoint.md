# 002 — The panel searches through the endpoint, and says when it fails

Spec: docs/specs/search-panel-honesty.md#AC3, AC4, AC5      Blocked by: 001 (done)      Size: S      **Status: done (2026-11-09)**

## Delivers

`SearchPanel` sends one request per query (no per-workflow fan-out), lists the matches the endpoint
returns, shows the HTTP status when the request fails, and no longer offers a replace control that does
nothing.

## Acceptance (what a validator will check)

- [x] `grep -c "getWorkflowCode(" src/components/layout2/SearchPanel.tsx` → **0** (AC3) — done
- [x] `grep -c "replaceText" src/components/layout2/SearchPanel.tsx` → **0** (AC5) — done
- [x] `grep -c "Mock search results" src/components/layout2/SearchPanel.tsx` → **0** (AC5) — done
- [x] a failure renders a block that names `HTTP <status>` and the detail; a network failure says the
      backend did not answer. Verified by reading the two `catch` paths (no empty list anywhere) — done
- [x] `npx tsc --noEmit` → exit **0**; `npm run build` → **✓ built in 6.5s** — done
- [x] the docstring names workspace files + workflow definitions; `grep -c "search-in-files"` → **0** (AC6) — done

## Not in this ticket

Jumping to the matched line in the viewer — 003. Server-side behaviour — 001.

## Notes

The debounce (300 ms) stays. Keep the group-by-file accordion; it is the one part of the panel that
works well.
