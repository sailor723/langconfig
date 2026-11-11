# Sun Hing Dashboards — Generation Architecture

How the Sun Hing executive dashboards (the "Analysis" activity, port 1421) are
produced, where every page comes from, and what the determinism guarantees are.

> Scope: the **Sun Hing Vision Group** study case only. The ERP demo dashboards
> (`backend/skills/personal/1/erp-analyst/9_erp_dashboard.py`) and the LLM upload path
> (`backend/services/dashboard_generator.py`) are separate regimes and are
> covered at the end for contrast.

## TL;DR

| Question | Answer |
|---|---|
| Who generates the cockpit + factor dashboards? | **One deterministic script**: `data/analysis_dbs/gen_sunhing_kpi_dashboard.py` (1,816 lines) |
| Does an LLM participate? | **No** — `grep -ci 'openai\|anthropic\|llm\|prompt\|api_key'` = **0**; imports are `json, sqlite3, defaultdict, datetime, pathlib, os` |
| Is it reproducible? | **Yes** — same DB + same code ⇒ byte-identical HTML, except one `Generated: <timestamp>` line |
| Which pages carry the 28 KPIs? | hub (28), data page (28), and the 5 factor sub-dashboards (9 + 4 + 4 + 4 + 7 = 28) |
| How does the UI consume them? | static HTML files in `data/analysis_dbs/*.html`, rendered in an iframe by `src/pages/AnalysisPage.tsx` |

## 1. Producer map (all `sunhing_*.html` in `data/analysis_dbs/`)

| Page | Producer | Notes |
|---|---|---|
| `sunhing_dashboard.html` | **BUILT** (`:973–1576`, write at `:1590`) | executive hub/cockpit; all 28 KPIs |
| `sunhing_dashboard_profit.html` | **BUILT** (`generate_sub_dashboard_html` `:525`) | KPI 01–09 (净利润率) |
| `sunhing_dashboard_turnover.html` | BUILT | KPI 10–13 (资产周转率) |
| `sunhing_dashboard_leverage.html` | BUILT | KPI 14–17 (权益乘数) |
| `sunhing_dashboard_support.html` | BUILT | KPI 18–21 (支撑层) |
| `sunhing_dashboard_risk.html` | BUILT | RS01–RS07 (风险监控) |
| `sunhing_dashboard_data.html` | BUILT (`:1689`) | raw KPI tables (28 × 6 months) |
| `sunhing_gantt.html` | BUILT (`:1637`) | PMO milestones from `raw_pmo` / `dim_pmo_phase` — **no KPIs** |
| `sunhing_erd.html` | **copied pass-through** (`:1621`) | master lives in `_LANGCFG_DIR`; the script only copies it |
| `sunhing_intro.html`, `sunhing_intro_cn.html` | copied (`:1626–1636`) | from `_LANGCFG_DIR`; `⚠ Source not found … skipping` if absent |
| `sunhing_dashboard_employees.html`, `sunhing_dashboard_liability.html` | copied | same loop |
| `sunhing_dashboard_kpi02.html`, `sunhing_dashboard_kpi03.html` | **not from this script** | Jul 19 prototypes, superseded by the profit dashboard (c02/c03) |

Verified coverage (matching every `dim_kpi.kpi_id` against every page):
**28/28 KPIs appear in BUILT pages**, none only in non-generated pages, none missing.
The five factor dashboards partition the 28 exactly: `9 + 4 + 4 + 4 + 7 = 28`.

## 2. Generation pipeline (code sites)

```
sunhing_kpi.db
  ├─ dim_kpi            (28 rows: kpi_id, kpi_name, roe_factor, target, unit, data_source)
  ├─ fact_kpi_monthly   (167 rows = 28 KPIs × 6 months, actual + target)
  ├─ fact_roe_summary   (6 rows: net_profit_margin, asset_turnover, equity_multiplier, roe)
  └─ raw_*              (detail/monthly sources)
            │
            ├─ all_periods          :735    6 periods (2026-09 … 2027-02)
            ├─ ROE trend            :739–747  fact_roe_summary → roeTrend
            ├─ latest KPI rows      :752–772  hub query, ORDER BY CASE roe_factor
            ├─ monthly series       :784–790  all 28 KPIs × 6 months → all_monthly_data
            ├─ HR / liability       :794–818  raw_hr / raw_liability
            └─ enrichment + adjusted ROE :821–972
                        │
      ┌─────────────────┴──────────────────────────────┐
      ▼                                                ▼
  HUB  (all 28)                             5 SUB-DASHBOARDS (filtered)
  • 3 factor cards        FACTOR_META  :59   • SQL: WHERE d.roe_factor = ?   :540–549
  • ROE trend + DuPont factor-score charts   • per KPI: card :562 · status row :580
    (hand-written Plotly in the f-string)      · chart :596 + generate_chart_js :480
  • sections_html          :927              • insights (auto)      :616–640
  • EMBEDDED_DATA (=latestKpis 28 rows,      • page shell + meta    :642–700
    factorCards 3, roeTrend, rawHr,          • write                :1608
    liabilitySummary)      :973–1576
```

**Shared helpers** used by hub and sub-dashboards alike:
`is_lower_better :352` · `calc_score :356` · `is_met :366` · `clean_name :374` ·
`format_value :378` · `format_dupont_value :394` · `status_detail :400` ·
`grade_from_score :413` · `grade_to_multiplier :421` · `render_dashboard_meta :436` ·
`factor_health_class :450` · `nav_links_html :458` · `generate_chart_js :480`.

### Scoring semantics (`:352–432`)

- Normal KPI: `score = actual / target × 100`
- `LOWER_IS_BETTER` KPIs (`:46`: `03, 04, 16, 20, RS01, RS03, RS05, RS06, RS07`): `score = target / actual × 100`
- `target == 0` ⇒ 100 only when `actual == 0`; scores clamped 0–100
- Grade: `A ≥ 90 · B ≥ 80 · C < 80`; `grade_to_multiplier` maps A→0.80, B→1.00, C→1.20 for the weighted ROE model

### Per-KPI visual contract (sub-dashboards)

One SQL row per KPI produces **four** outputs: a KPI card (`ok|warn`, note
`Target … ✅ Met` / `△ gap`), a status table row (✅ Met / ⚠️ Near Miss score ≥ 70 /
⚠️ Far Behind), a Plotly chart (`chart_id = "c" + kpi_id prefix`, e.g. `c01`,
actual line + dashed red target line, colour green when the last point meets
target), and one or more auto-generated insight bullets (已完成 / 接近达标 /
需重点关注). Chart cards are titled with the raw `kpi_id`, which is how KPI→chart
traceability is verified.

> Note: the comment at `:561` says *"Summary cards (top 4 items)"* but the loop
> emits one card per KPI of the factor — 9 for profit, 7 for risk. The comment is
> stale.

## 3. Determinism guarantee (verified)

Two full runs, ~1 minute apart, same DB, same output dir:

- **13 pages produced; 13 byte-identical** modulo one line:
  `Generated: 2026-09-28 21:54 | Source: sunhing_kpi.db | Mode: static-embed`.

Only two nondeterminism sources exist in the file, both `datetime.now()`:
`:533` (sub-dashboards) and `:982` (hub). Every query has an explicit `ORDER BY`
(`:546`, `:767–772`, `:786–789`); there is no `random`, `uuid`, or `time()`.

**Consequences**

- Same DB ⇒ same dashboards. The DB is the *only* meaningful input.
- A page is a **snapshot** of its latest period (currently `2027-02`): series are
  inlined as JSON literals by `generate_chart_js`, so a stale page stays stale
  until the script is re-run.
- Reproducibility makes the output git-friendly: with a fixed timestamp the suite
  would be bit-for-bit diffable (see "Recommended improvements").

## 4. Where it writes vs where it reads

```python
_DASHBOARD_DIR = os.getenv("SUNHING_DASHBOARD_DIR") or \
    ".../agent-workspace/reports/eyewear_industry/新溢眼镜/dashboard"
OUTPUT_DIR    = _DASHBOARD_DIR / "html"        # ← generated pages are written here
DB_PATH       = _DASHBOARD_DIR / "db/sunhing_kpi.db"   # ← its DB
_LANGCFG_DIR  = Path(__file__).parent          # ← ERD/intro/employees/liability masters are copied FROM here
```

So the script **reads its DB and copies masters from LangConfig**, but **writes
into agent-workspace**. The copies under `data/analysis_dbs/` that the UI serves
arrive via a separate sync step — which is why they can drift from the DB.

## 5. How the UI consumes them

1. `src/pages/AnalysisPage.tsx` lists dashboards from
   `GET /api/analysis/dashboards`, which globs `data/analysis_dbs/*.html` and
   parses each file's `LangConfig Dashboard Meta` head comment.
2. Rows with `entry: detail` are **filtered out** of the panel list
   (`shouldShowDashboardInPanel`); `entry: hub` is the cockpit.
3. The page renders in an `<iframe src={API_BASE_URL + path}>` served by
   `GET /api/files/<name>`, which rewrites Plotly's CDN URL to
   `/static/plotly.min.js` so the page works offline.
4. The **Chat** panel posts to `/api/analysis/chat`; the agent gets the skill
   named in the meta (`skills: sunhing-analyst`) via `_load_skill_markdown_parts()`
   (reads `backend/skills/<name>/SKILL.md`) — this is the only path where the
   skill participates in *answering*, never in *rendering*.

## 6. Known issues / drift risks

1. **Two `sunhing_kpi.db` copies with different schemas**
   - LangConfig `data/analysis_dbs/sunhing_kpi.db` — 17 tables (11 raw + **3** dim + 2 fact)
   - agent-workspace `…/dashboard/db/sunhing_kpi.db` — 24 tables (11 raw + **9** dim + 2 fact; `dim_*_monthly` aggregates + detail `raw_*`)
   Dashboards point at whichever copy their `db:` meta names — the hub/profit use
   the agent-workspace copy, the ERD/gantt use the LangConfig copy.
2. **The skill documents the older schema** — `backend/skills/personal/1/sunhing-analyst/SKILL.md`
   has 0 mentions of `dim_*_monthly` (and 0 of the new detail `raw_*` tables), so
   Chat answers can query tables that no longer exist in the DB the page uses.
3. **Copy-propagated static pages** — `sunhing_erd.html` and friends are copied,
   not generated, so they drift silently (the ERD had 12/16 tables with wrong or
   invented columns before it was regenerated).
4. **Duplicated metadata** — the same facts live in two configs:
   `FACTOR_META` (`:59–104`, hub cards: `link`, `accent`, `summary`) and
   `SUB_DASHBOARDS` (`:275–333`, sub pages: `filename`, `accent`, `subtitle`).
   Change one, forget the other, and the hub links/colours diverge.
5. **Hub is inline, not a function** — ~603 lines of top-level f-string HTML
   (`:973–1576`) with its own CSS and hand-written `Plotly.newPlot` calls, while
   sub-dashboards go through `generate_sub_dashboard_html()` + shared
   `generate_chart_js()`. One file, two implementations.
6. **Three copies of the generator** — `deepresearch-custom-workflow/…/codes/`,
   `agent-workspace/…/codes/`, `langconfig/data/analysis_dbs/` (identical md5
   today; the agent edits the deepresearch one via `build_dashboards.py`).
   `data/` is **gitignored**, so the LangConfig copy is not version-controlled.
7. **`dashboard-builder` skill missing** — `agent-workspace/build_dashboards.py`
   declares `skills=["dashboard-builder", "sql-analyst"]` but no such skill
   directory exists in the workspace.

## 7. How to regenerate

```bash
# 1) rewrite the DB (dim/fact/raw) from the mock pipeline
cd langconfig/data/analysis_dbs && python sunhing_kpi_db.py

# 2) regenerate every dashboard (deterministic; no LLM)
cd langconfig/data/analysis_dbs && SUNHING_DASHBOARD_DIR=<dashboard dir> \
  ../../backend/.venv/bin/python gen_sunhing_kpi_dashboard.py
# default SUNHING_DASHBOARD_DIR: agent-workspace/reports/eyewear_industry/新溢眼镜/dashboard
# writes <dir>/html/*.html, reads <dir>/db/sunhing_kpi.db

# 3) serve them into the Analysis panel
cp <dir>/html/sunhing_*.html langconfig/data/analysis_dbs/
```

## 8. Recommended improvements

1. **Fix the skill/DB mismatch** — re-point `sunhing-analyst` at the schema the
   pages actually use (or standardise on one DB copy) so Chat and dashboards agree.
2. **One config, one code path** — derive both hub cards and sub-dashboards from a
   single `DASHBOARDS` list; extract `generate_hub_html()` and reuse
   `generate_chart_js()` for the hub's two charts.
3. **One canonical, tracked location** — move the generator into a tracked path
   (`backend/scripts/sunhing/` or `learning/phase5/sunhing/`) and have it write
   directly into `data/analysis_dbs/`, removing the cross-repo copies and manual sync.
4. **Reproducible output** — add `--no-timestamp` (or honour `SOURCE_DATE_EPOCH`)
   so runs are bit-identical and the suite can be diffed in CI/git.
5. **Provenance stamping** — extend the meta block with the generator name + DB
   hash so the UI can show which code/DB version produced a page.

## 9. Contrast: the other two regimes

| | Sun Hing cockpit | ERP demo | Upload dashboards |
|---|---|---|---|
| Code | `gen_sunhing_kpi_dashboard.py` | `backend/skills/personal/1/erp-analyst/9_erp_dashboard.py` | LLM: `services/dashboard_generator.py` + `api/analysis/routes.py` prompt |
| LLM | ❌ none | ❌ none | ✅ yes (+ optional companion `.skill.md`) |
| Determinism | byte-stable (modulo timestamp) | byte-stable (`Mode: static-embed`) | varies run-to-run — same CSV+skill can yield 0 charts or 12 |
| Business flavour | hard-coded in the script (`FACTOR_META`, `<h3>ROE 修复趋势</h3>`, 管理层结论 f-strings) | in the ERP script | in the companion skill's 4 injected sections |

That last row is the key mental model: **the deterministic paths keep the business
story in code/config; the LLM path keeps it in the companion skill, and the prompt
only supplies process rules.**

## 10. The ontology renderer (2026-11-11, `sunhing_v1`)

The generator in §1 renders from the SQLite copy and knows the schema. A second,
narrower producer renders the SAME six-page cockpit from the **ontology
declaration**, so the numbers come from a declaration a gate can check rather than
from a script:

```bash
cd langconfig
backend/.venv/bin/python backend/scripts/sunhing_dashboard_from_ontology.py --check   # values only
backend/.venv/bin/python backend/scripts/sunhing_dashboard_from_ontology.py           # write the 6 pages
```

| Artefact | Path |
|---|---|
| renderer | `backend/scripts/sunhing_dashboard_from_ontology.py` |
| KPI ↔ metric declaration | `backend/features/ontology/profiles/sunhing_v1/kpi_map.json` |
| layout (original CSS, verbatim) | `backend/scripts/templates/sunhing/{hub,factor}.css` |
| output | `data/analysis_dbs/sunhing_ontology_{hub,profit,turnover,leverage,support,risk}.html` |

**Why the `ontology_` prefix:** `/api/files/{name}` only accepts a bare filename
and `rglob`s the whole `data/analysis_dbs` tree, so reusing
`sunhing_dashboard_profit.html` would overwrite the 2026-11 originals — the only
comparison baseline there is. The prefix keeps both and still serves through
`/api/files/sunhing_ontology_hub.html` (HTTP 200, Plotly swapped to
`/static/plotly.min.js`, so it works offline).

### 10.1 Layout is copied, not re-imagined

The two `<style>` blocks in the original pages are *different* (hub 8 620 B with
`.factor-card`/`.section`; factor pages 4 396 B with `.kpi-card`/`.kpi-table`), so
both were copied verbatim into `templates/sunhing/`. The element vocabulary:

| Original hub | Renderer |
|---|---|
| `.header` h1 + `.sub` + ROE formula line | same, plus the profile name |
| `.baseline-bar` 5 cells | same 5 cells (时间范围/当前观察月/基准 ROE/当前 ROE/追缴已化解) |
| `.nav-links` → `/api/files/…` | same labels, **relative** hrefs (works from disk too) |
| `.dashboard` 3 `.factor-card {npm,at,em}` | same 3 cards (`sup`/`risk` were sections, not cards, in the original) |
| `.result-bar` ROE + 3 slider rows | ROE reading + the three factor scores, **no sliders** (see 10.2) |
| `.summary-bar` 达标 n/28 · 减员 · 追缴 | same, every number a declared metric (`liab_remaining` is `liabTotalWan − liabResolvedWan`) |
| `.overview-grid`: `#roe-trend`, `#factor-score` | same two chart ids and trace styling |
| 5 × `.section` with `kpi-head` + `kpi-row`/`kpi-note` | same, nested identically |
| `.insight-box` 关键洞察 | same box, bullets derived from the computed statuses |

| Original factor page | Renderer |
|---|---|
| `.page-title` + `.page-subtitle` | same strings |
| `.baseline-bar` (当前主题/观察期/当前月) | same 3 cells + 达标 + 平均得分 |
| `.kpi-row` of `.kpi-card {ok,warn}` "Target 100.0% △ 5.4 gap" | same, plus `danger` (the original had no third state) |
| `table.kpi-table` #/KPI/月/Target/Gap/Status | same columns, same 达标/⚠️ Near Miss/❌ Miss wording |
| `.grid` of `.card` + `.chart-title` + `div#cNN.chart` | same ids (`c01`…), 6-point line + dashed target |
| `.insight-box` | same |

### 10.2 What the renderer deliberately does NOT reproduce

1. **The ROE slider simulation.** The original `.result-bar` multiplied three
   factors by hand-picked weights (`npmWeight`, …) whose provenance is not
   declared anywhere. Reproducing it would mean inventing a model, so the band
   shows the measured reading and says so in the caption.
2. **The 追缴总额 / 2430 万-era numbers.** They belong to the earlier dataset (§10.5).
3. **A chart for a KPI with no series.** The card stays in the grid and states
   which `:…ByMonth` metric is missing and what the snapshot reading is, instead
   of drawing a one-point line that looks like a trend.
4. **A number for a KPI the ontology refuses.** Same: the card carries the
   refusal reason.

### 10.3 `kpi_map.json` — the declaration, and how it fails

One row per catalogue KPI (`dim_kpi`, 28 rows): `kpi_id` → ontology `metric`
(or `null` + `refusal`), the page it belongs to, and notes. Grouping/target/
direction/unit are read from `dim_kpi` and cross-checked against the ontology's
own `:unit`; a disagreement is a `[UNIT]` problem, not a silent format choice.

`--check` prints one line per finding and exits non-zero when anything is wrong:

| Line | Meaning |
|---|---|
| `[METRIC]` | the map names a metric the ontology does not declare — a map bug |
| `[VALUE]` | the metric's number differs from `fact_kpi_monthly` for the observation period |
| `[UNIT]` | value unit and target unit are different kinds of number |
| `[NO-SERIES]` | metric has no `:…ByMonth` variant (snapshot only — the page says so) |
| `[ACCEPTED]` | a known defect declared in `accepted_issues` **with its reason**; still printed |
| `[STAGED-ONLY]` | the `.ttl` on disk is newer than the applied publish — the pages would show unapplied numbers |

**Coverage today: 26 of 28 KPIs have a metric; 2 are refusals.** #17
`生态伙伴战略协同指数` and #18 `技术骨干留任率` were re-checked against the raw
tables and *do* reproduce exactly (`61.2711864` and `46.1538`, matching
`fact_kpi_monthly`), so they are declared in the map and become live metrics once
the profile declares them. RS06/RS07 stay refused because `dim_kpi.formula` is
the empty string — there is no definition to compile.

### 10.4 Accepted divergences (written down, not hidden)

| KPI | Divergence | Reason |
|---|---|---|
| 11 生态伙伴轻资产化指数 | ontology `37.5%` vs fact `0` | the old formula filtered `entity_type='eco_partner'`; the column holds `core`/`partner`, so it was always 0. `3/8 = 37.5%` is on the same scale as the 25% target. |
| 21 员工价值交换制度落地率 | value `5.06` (0–10) vs target `80%` | `dim_sentiment_monthly` stores a 0–10 score; `dim_kpi.unit` says `%`. The KPI can never be met — the page shows both numbers so the contradiction is visible. |
| RS05 海关违规/罚款金额 | no `fact` row | `fact_kpi_monthly.kpi_id` was sanitised to `RS05_海关违规_罚款金额` and `unit` written as `%`; the ontology computes 24.6 万元 from the raw side. |

### 10.5 The original pages' numbers do not come from either DB copy

Comparing the 2026-11 factor page against `fact_kpi_monthly` @ 2027-02 (identical
in both SQLite copies):

| KPI | original HTML | both DB copies | catalogue formula recomputed |
|---|---|---|---|
| 02 追缴化解率 | 84.5% | 85.47 | 85.47 |
| 03 预算控制率 | 93.5% | 128.47 | 128.47 |
| 05 工序保留率 | 98.0% | 40.0 | 40.0 |
| 06 生产人员占比 | 21.4% | 71.74 | 71.74 |
| 07 核心厂区利润贡献 | 38.5% | 71.06 | 71.06 |
| 09 数字资产转化 | 7.2% | 70.47 | 70.47 |

No month in either copy yields the HTML's values, so those pages were produced
from an earlier dataset generation. Consequence for this work: "same as the
original" is honoured for **layout and wording**, never for the numbers — the
numbers come from the ontology, which reproduces the database and the catalogue
formula exactly.
