# Worked examples

Three complete ontologies, each one teaching a different thing. They are copies: the live versions
are in `retail_graph/` (retail), `retail_graph/tpch/` and `retail_graph/abc/`, and they are the ones
the app serves and the gates run. Read these when you need the pattern; run the originals when you
need proof.

## `retail/` — the full pattern

The reference implementation. One object and one link (`:Customer`, `:Order —customer→ :Customer`),
a defined class compiled from an axiom (`:PremiumCustomer ≡ :Customer ⊓ (tier = 'PREMIUM')`), a
cross-grain ratio (`:revenuePerCustomer`, `:numerator`/`:denominator`), a two-key grouped metric
(`:revenueByProductCity`), a declared action with an audit trail, and a time-windowed metric whose
cutoff lives in the axiom (`:recentOrder`).

```
01-structure.ttl   objects, properties, declared links, :state "action" on action-owned state
02-meaning.ttl     the definitions and the metric meanings
metrics_ext.ttl    the computation overlay (:aggregate/:grain/:universe/:where/:groupBy)
```

Read `02-meaning.ttl` first: every metric there is a sentence a business person could sign.

## `tpch/` — read-only, historical, composite keys

What changes when the data is a benchmark rather than an operation:

- **no actions** (nothing is written to a historical dataset), no lane B (no mapping exists)
- **historical dates**: a `now()`-relative window is meaningless — the guard profile refuses instead
  of narrowing (`default_window_days: 0`), and the pages say so
- **composite keys**: `lineitem` is `(l_orderkey, l_linenumber)`, `partsupp` is
  `(ps_partkey, ps_suppkey)` — the composite link is declared and joined on both columns
- **one declared predicate**: `:LateLine` compares `l_shipdate > l_commitdate`. OWL cannot say that,
  so it is `:physicalPredicate`, and the compiler reports it as declared-by-hand
- **a union of criteria**: `:AtRiskDriver` is `(on_time_rate ≤ 0.93) ∨ (damaged_boxes ≥ 160) ∨
  (overload_trips ≥ 22)` — `owl:unionOf` compiles to `(a OR b OR c)`

`tpch.ttl` is the merged ontology (classes, axioms, metric meanings); `02-relationships.ttl` adds the
declared edges and the column bindings; `metrics_ext.ttl` is the computation overlay.

## `abc/` — operations, unions, and two audited writes

A cold-chain operator: 60 vehicles, 4,050 trips, 51,210 stops over three months, and the failures
planted where the story says they come from.

- **a windowed definition with a snapshot fact**: `:AtRiskDriver` reads `driver_stats` (a materialised
  30-day fact), because "over the last 30 days" has nothing to attach to otherwise
- **definitions as unions**: `:FailedDelivery` is `晚点 OR 倒温 OR 破损 OR 误触警铃`
- **a declared predicate for a column-vs-column comparison**: `:OverloadedTrip` (load vs the capacity
  snapshot frozen at dispatch)
- **two audited actions** (`actions.yml`): `AssignTrip` (who drives this trip — the "relationship
  scheduling" becomes a record) and `JudgeLiability` (liability stays NULL until judged, then audited)
- **a dimension with versions**: `:Route` is versioned (v1 before 并线, v2 after), which makes the
  before/after comparison answerable: 10.22 → 15.68 stops per trip, 2.0 % → 80.2 % overload

## Reading order

1. `retail/02-meaning.ttl` — how a definition and a metric are written
2. `retail/01-structure.ttl` — how objects and links are declared
3. `tpch/02-relationships.ttl` — composite links, and the one declared predicate
4. `abc/01-structure.ttl` + `abc/02-meaning.ttl` — unions, and a windowed definition over a snapshot
5. `abc/actions.yml` — two writes, with preconditions and audit
