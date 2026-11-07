# The ten panel kinds

Pick the smallest kind that shows the finding. Every value comes from a compiled metric; the page only
lays out. Column names below refer to the rows a metric returns: `[key1, key2?, value]`.

| kind | shows | declaration needs | gate |
|---|---|---|---|
| `kpi` | one number | `metric` (no `:groupBy`) | `D1` one row, no keys |
| `slope` | one version axis, absolute + rate together | `metrics[]`, `x: {dimension, order[]}` | `D1` one key, covers `order` |
| `series` | time or ordered axis | `metric` with `:timeBucket` (or 1 key), `render: line\|bar\|strip`, `marks[]` | `D1` axis ascending; one row needs `expect` |
| `ranked` | dots, size = another declared count | `metric`, `size_by`, `sort`, `limit`, optional `client_sort` | `D1` keys sized; `D2` order |
| `matrix` | 2-key heat grid, cell = value + size | `metric`, `rows`, `cols`, `size_by` | `D1` every cell sized |
| `composition` | parts of a whole, NULL group labelled | `metric` (1 key), `null_label` | `D1` labels its NULL group |
| `sankey` | declared flows between declared nodes | `nodes[]`, `links[{from,to,metric,key}]`, `conservation[]` | `D8` conservation per internal node |
| `bubble` | 4 channels on the same objects | `x`, `y`, `size`, `color`, `color_labels` | `D9` same key set, gaps counted |
| `treemap` | 2-key sum as area | `metric` (2 keys), `null_label` | `D1` two keys; NULL cell grey |
| `parallel` | 2+ scalars side by side, **no difference** | `metrics[]` (all scalar) | `D1` one row each |
| `hole` | a declared gap | `missing`, optional `requires`, `measurable_now` | `D4` still refuses |

## When a kind is the honest choice

- **the numbers move together** → `slope`. Four separate panels cannot show that v1→v2 moved volume and rate
  in opposite directions.
- **"per what"** → `ranked` (many keys) or `matrix` (two dimensions). A ranked panel without `size_by` is a
  lie about the denominator: 249.8 boxes/1k stops on a vehicle that ran 300 stops is not the same fact as
  on one that ran 1,000.
- **flow, not total** → `sankey`. Only when every band is a declared group AND the flows balance; a Sankey
  whose bands do not add up looks broken long before anyone works out why.
- **four channels** → `bubble`, and only when all four are declared. A colour inferred in the browser
  ("permit is true because the plate is in some list") is the client doing a join the ontology never made.
- **a difference you cannot declare** → `parallel`. Measured: 收入 − 已判定赔付 needs a cross-grain
  subtraction the compiler does not have, so the board shows both and says why there is no difference bar.

## Two shapes that look fine and are not

- **a one-row "time series"**: `complaintCountByWeek` returns ONE bucket because every complaint carries the
  same timestamp. Declare it (`expect`) — the single bucket IS the finding.
- **a ranked list at the low end**: grouped metrics are compiled `ORDER BY … DESC`. Asking for "the 20
  worst" requires `client_sort: true`, or the board renders the 20 best. `D2` fails it otherwise.

## Chart libraries

Hand-rolled SVG for `slope`/`series`/`ranked`/`matrix`/`composition`/`parallel`; `d3-sankey` and
`d3-hierarchy` for `sankey` and `treemap` (layout only — both take numbers, neither computes one).
