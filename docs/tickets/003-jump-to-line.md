# 003 — A match opens the file at its line

Spec: docs/specs/search-panel-honesty.md#AC7      Blocked by: 002 (done)      Size: S      **Status: done (2026-11-09)**

## Delivers

Clicking a search match opens the file (or the workflow) with the cursor on that line, scrolled into
view, and the toolbar says `line N` so the reader can see where they landed. Before this, the panel set
`highlightLine` and **nothing consumed it** — every result opened at the top of the file.

## Acceptance (what a validator will check)

- [x] `FileEditor` consumes `tab.data.highlightLine`: a `useEffect` selects the line's character range,
      focuses the textarea and scrolls it to roughly the middle of the viewport — done
- [x] the line arithmetic is a pure, exported function (`lineSelection`) and its cases pass: line 1/2/3
      select the right text, line 0 and a line past the end return `null` (5 checks, `node`) — done
- [x] the toolbar shows a `line N` chip when the tab was opened from a match — done
- [x] a tab **without** `highlightLine` behaves exactly as before (focus only, no selection) — done
      by construction (`wantedLine === null` branch)
- [x] `npx tsc --noEmit` → exit 0; `npm run build` → ✓ built — done
- [ ] **PARTIAL — the browser check.** That the textarea visually lands on the line after a real click is
      not provable from here (no browser automation in this repo). What settles it: open the sidebar
      search, type a term that appears deep in a file (e.g. `tool_call`), click a row with a high line
      number, and see the `line N` chip plus the caret on that line.

## Not in this ticket

Highlighting **every** match inside the opened file, keyboard navigation between matches, and reopening
the same file at a different line while its tab already exists (the effect re-runs on `wantedLine`, but
the tab id is the path, so a second click reuses the same tab — worth its own ticket if it annoys anyone).

## Notes

`viewType: 'workflow'` renders the same `FileEditor`, so workflow matches get the same behaviour without
a second implementation.
