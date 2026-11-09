# Validation report — the sidebar's bottom Search row

Scope: `e688d95b` (a permanent search entry at the bottom of the left sidebar; both entries live).
No spec exists for this change, on purpose: the two decisions (put it at the bottom, keep both entries)
were made by the user in one exchange, so a grill round had nothing to settle. What it still owes is
**evidence**, which is what this file and `backend/tests/test_sidebar_search_entry.py` are.
Validated: 2026-11-09, locally (the build under test is `index-B2YU4lvn.js`).

| # | Criterion | Verdict | Evidence |
|---|-----------|---------|----------|
| AC1 | The labels come from i18n, not from the component | **PASS** | `test_labels_come_from_i18n_not_from_the_component`: the row calls `tr('sb_search_entry')` / `tr('sb_search_back')`, and the literal `Search workspace files & workflows` is absent from the component |
| AC2 | Both keys exist in both languages, non-empty and different | **PASS** | `test_both_labels_exist_in_both_languages`: 2 definitions each; en `Search workspace files & workflows` / `Back to the file list`, zh `搜索工作区文件与 workflow` / `返回文件列表` |
| AC3 | The row is the **bottom** entry: after the content area, before the status bar | **PASS** | `test_the_row_is_below_the_content_and_above_the_status_bar` compares the three JSX anchors in file order |
| AC4 | Both doors open the same view | **PASS** | `test_both_doors_open_the_same_view`: the expression `setSidebarView(isSearch ? 'explorer' : 'search')` appears twice — header icon and bottom row |
| AC5 | The row is absent where the sidebar is absent (Settings, Vault) | **PASS** | `test_the_sidebar_still_disappears_in_settings_and_vault` pins the guard, and the row is inside that subtree |
| AC6 | The built app serves it | **PASS** | `npm run build` → `index-B2YU4lvn.js`; `grep -c "Search workspace files & workflows"` in that bundle → 1; the Vite dev server on `:1421` serves the updated module (`sb_search_entry` ×2) |
| AC7 | Clicking the row opens the panel, and while search is open the row reads "Back to the file list" | **PARTIAL** | the user saw the row in the running app (2026-11-09) — **presence confirmed by a human**, the click and the label flip were not. Settles it: click the row, then click it again |
| AC8 | The Chinese labels render | **PARTIAL** | the zh strings exist in the dictionary (AC2), but the running shell was not switched to Chinese here. Settles it: switch the UI language and read the row |

**PASS 6 · PARTIAL 2 · FAIL 0**

## What this report is careful about

The two PARTIALs are exactly the two things I had previously called "verified" on the strength of reading
the code. They are not verified: nothing in this repository can click a button or change the UI language,
so the honest verdict is PARTIAL with the check that would settle it named. Everything in PASS has a
command behind it that you can re-run:

```bash
cd backend && .venv/bin/python -m pytest tests/test_sidebar_search_entry.py -q
```

## Not checked (on purpose)

- Keyboard access (is the bottom row reachable by tab?) and its focus ring — a real question, a different
  ticket.
- Whether the row should be hidden while search is open instead of turning into "Back" — a design choice,
  not a defect; the flip was chosen so the panel cannot trap the reader.
- Whether the row is discoverable enough at 11.5px — that is what the user's eyes decide, and they did.
