# `check_dashboard.py` — D0–D9 + F1

```bash
PY=/Users/weiping/dev/Learn/cube/tutorial/.venv/bin/python
$PY backend/features/ontology/gates/check_dashboard.py \
    --profile backend/features/ontology/profiles/logistics/logistics_settings.json   # 196 checks
```

Runs the SAME declaration the app serves, through the same runner, so the gate and the page cannot disagree
about what a panel says.

| family | catches | mutation that proves it |
|---|---|---|
| `D0` | a panel naming a metric that does not exist (or a hole that answers) | rename a panel's metric → 5 failures, `D0` names both |
| `D1` | wrong shape: a "series" with no time axis, a matrix with one key, a ranked list with no sizes, a one-row series with no `expect` | — shape rule per kind |
| `D2` | "the 20 worst" rendered from a `DESC`-compiled metric without `client_sort` | drop `client_sort` → fails naming the panel |
| `D3` | a join that fans out, a FILTER applied on one side only, a rate that no longer weights back | delete the grouped-ratio `FILTER (WHERE …)` → 4 D3 failures |
| `D4` | a declared hole that started answering | — a stale hole must fail |
| `D5` | two routes through the same declaration agreeing with each other and neither with the data | same mutation → `overload rate v2` mismatch |
| `D6` | an event marker on a categorical axis, or with no data on one side | move the marker out of range |
| `D7` | a hand-typed number in the assessment; a threshold that declares neither `assumed` nor `confirmed`; a claim judged by an undeclared policy; a verdict that is not the comparison, recomputed | add "（比甲方 95% 低 3 个点）" → fails; remove `assumed` → fails |
| `D8` | a Sankey band that is not a declared group, or a node whose flow does not balance | — conservation is the check |
| `D9` | bubble channels covering different objects | — gaps must be declared AND counted |
| `F1` | a filter that only reached the numerator; a value the declaration does not offer answered as 0; an unreachable dimension answered instead of refused | — see the table in SKILL.md |

## Two rules learned from the gate's own failures

- **read the ORDER BY, not the last token.** `guard` appends `LIMIT 1000` after the `ORDER BY`, so
  `sql.endswith("DESC")` reported every panel as ASC and `D2` passed on nothing.
- **key the comparison, never zip by position.** `overloadRateByRouteVersion` orders by VALUE while
  `tripCountByRouteVersion` orders by COUNT; a positional zip "found" a 45.5% fleet overload rate against
  the real 36.8%.

## The empty-relation rule (shared with `check_ontology_generic` R1)

A definition over an empty table cannot be disproved by counting: `R1` reports it as a named `NOT RUN`
(`dispatch_decisions is empty, so a selective predicate over it cannot be tested`) instead of failing, and
keeps FAILING when the table has rows and the axiom still selects none. A board over an unrecorded process
must be allowed to say "0 rows" — and must be barred from pretending it is complete.
