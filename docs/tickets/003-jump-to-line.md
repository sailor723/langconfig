# 003 — A match opens the file at its line

Spec: docs/specs/search-panel-honesty.md#AC6      Blocked by: 002      Size: S

## Delivers

Clicking a match opens the file in a tab and, when the viewer can place the cursor, jumps to the matched
line; when it cannot, it opens the file and says so in one line rather than silently opening at the top.

## Acceptance (what a validator will check)

- [ ] clicking a match whose `line` is 137 opens a tab whose view type is the file's and, in a viewer that
      accepts a line (the workflow editor or `FileEditor`), the cursor/scroll is at 137
- [ ] for a viewer that does not accept a line (PDF, image), the file opens and a one-line note says the
      line could not be positioned
- [ ] `npx tsc --noEmit` exits 0

## Not in this ticket

Highlighting every match in the opened file, result ranking, keyboard navigation between matches.

## Notes

Check first whether `useLayoutState().openTab` already carries a line/offset field — if it does, this is
a one-line change in the panel; if it does not, adding the field is the whole ticket.
