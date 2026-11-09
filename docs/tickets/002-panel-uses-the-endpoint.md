# 002 — The panel searches through the endpoint, and says when it fails

Spec: docs/specs/search-panel-honesty.md#AC3, AC4, AC5      Blocked by: 001      Size: S

## Delivers

`SearchPanel` sends one request per query (no per-workflow fan-out), lists the matches the endpoint
returns, shows the HTTP status when the request fails, and no longer offers a replace control that does
nothing.

## Acceptance (what a validator will check)

- [ ] `grep -c "getWorkflowCode(" src/components/layout2/SearchPanel.tsx` → 0 (AC3)
- [ ] `grep -c "replaceText" src/components/layout2/SearchPanel.tsx` → 0 (AC5)
- [ ] `grep -c "Mock search results" src/components/layout2/SearchPanel.tsx` → 0 (AC5)
- [ ] forcing the endpoint to 500 (stop the backend) shows a visible message naming the status, not an empty list (AC4)
- [ ] `npx tsc --noEmit` exits 0; `npm run build` exits 0
- [ ] the docstring names what it searches (workflow code + workspace files) (AC6)

## Not in this ticket

Jumping to the matched line in the viewer — 003. Server-side behaviour — 001.

## Notes

The debounce (300 ms) stays. Keep the group-by-file accordion; it is the one part of the panel that
works well.
