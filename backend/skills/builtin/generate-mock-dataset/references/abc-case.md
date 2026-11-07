# The ABC cold-chain dataset — worked example

`retail_graph/abc/gen_abc.py` (SEED 20251106, `--reset`), database `abc_coldchain`, 90 days
(2026-08-08 → 2026-11). Facts below are MEASURED from the dataset, not copied from the brief.

## Schema (11 tables)

| table | rows | grain | notes |
|---|---|---|---|
| `vehicles` | 60 | one truck | `emission` 国四36/国五18/国六6, `age_years` ~9.1, `core_zone_permit` 14/60 |
| `drivers` | 60 | one driver | 1:1 with vehicles; no `loan_*` column (the missing record) |
| `routes` | 90 | one route VERSION | v1 50 + v2 40, `effective_from` 2026-09-22, `planned_stops`, `planned_km`, `zone` |
| `route_stops` | — | planned stop | does NOT join to actual stops (75/51,210) |
| `trips` | 4,050 | one vehicle-day-route | load + capacity SNAPSHOT, `revenue`, `trip_date` |
| `stops` | 51,210 | one store visit | `on_time`, `temp_excursion`, `damaged_boxes`, `alarm_triggered`, `handler_id` (27.8% NULL) |
| `complaints` | 6,876 | one per stop | `kind` constant, `opened_at` constant, `liability` 46.1% NULL, `amount` only when judged |
| `handlers` | 420 | one day-labourer | 3 agencies, `days_worked` avg 6.1, 55.7% ≤ 3 days |
| `driver_stats` | 60 | one driver snapshot | `window_days` constant 30 (a label, not a window) |
| `stores` | 800 | one store | `window_from/to`, `has_alarm` 414/800 |
| `telemetry` | 12,144 | one sample | only ~3 h (06:00–08:45): no temperature trend |

## Planted signals (each is an invariant in `abc_coldchain.dataset.json`)

| claim | measurement |
|---|---|
| 并线 50 → 40 条线路 | `routes`: v1 50 / v2 40 |
| 每条线更满 | `planned_stops` 10.2 → 15.7 |
| 超载变成常态 | trips 超载 2.0% (v1) → **80.2%** (v2) |
| 准时率下滑 | 按站点 95.6% → 91.9% |
| 路权冲突 | 国四 36 台 0 台有路权；覆盖 14/60 = 23.3% |
| 临时工高流动 | 55.7% 的装卸工 ≤ 3 天上岗 |
| 破损随新手上来 | 新手（≤3 天）每站 0.22 箱 vs 老手 0.138 |
| 客诉跟晚点 | 6,876 单，责任 driver 1,673 / labourer 2,036 / **NULL 3,167** |
| 赔付只在已判定一侧 | labourer ¥1,287,671.19 + driver ¥1,064,967.95；未判定组 `amount` 全 NULL |
| 温控只有一段 | 12,144 行全在 2026-11-03 06:00–08:45 |

## What the dataset deliberately does NOT contain

- **排单决策**: no `dispatch_decisions` table in the generator. The plan recorded the OUTCOME (who drove),
  never the decision (who assigned, why, how much loan pressure). Consequence, kept honest: `corr(准时率,
  趟数) ≈ 0` is all that can be measured; the dashboard shows `0 / 4,050` coverage and refuses the intent.
- **运价与合同**: only `revenue`, no unit price → "how much should the brand compensate for 并线" is
  unanswerable; the board says so instead of estimating.
- **结案**: `closed_at` 100% NULL → no case duration, no open-case count.

## Regeneration

```bash
PY=/Users/weiping/dev/Learn/cube/tutorial/.venv/bin/python
$PY retail_graph/abc/gen_abc.py --reset                 # schema + data, deterministic
$PY backend/skills/builtin/generate-mock-dataset/scripts/check_dataset.py \
    --spec retail_graph/abc/abc_coldchain.dataset.json  # 53 checks, 0 failed
```

If a check goes red after a change, the choice is: fix the generator, or change the claim in the spec AND
in the ontology's `:businessDescription` — never leave the two disagreeing.
