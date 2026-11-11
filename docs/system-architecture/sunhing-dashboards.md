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
| output | `data/analysis_dbs/sunhing_dashboard{,_profit,_turnover,_leverage,_support,_risk}.html` — the SAME canonical names the app, the registry and every 2026-09 cross-link already use |

**Naming (settled 2026-11-11, after getting it wrong once):** the pages were first written
under an `ontology_` prefix to keep the 2026-09 originals as a comparison baseline. That was the
wrong trade: the Analysis panel, the registry's `home`, every cross-link and every bookmark point
at `sunhing_dashboard*.html`, so those URLs kept serving the September numbers — the cockpit
existed and "I opened it and nothing changed" stayed true. The renderer now writes the
**canonical names** and archives the replaced pages to
`data/analysis_dbs/archive-2026-09-28/` (written once, never over an existing archive).
`--also-ontology-names` still produces the alias set; it is off by default because a second set
doubles the family in the panel.

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

**Coverage today (publish `1794405491-7e4275`, 87 metrics): 25 of 28 KPIs answer — 22 with a
6-point monthly series, 3 snapshot-only (#11 / #14 / #17 have no period column, and the card
says so) — and 3 are declared refusals (RS06, RS07, #18).** #17
`生态伙伴战略协同指数` is now a declared metric (`ecoPartnerSynergyIndex`, snapshot
`61.2712`, matching `fact_kpi_monthly` × 6) — its formula is
`60 + 伙伴订单占比×5 + 伙伴实体数×2`, where the third term is 0 because the column holds
`core`/`partner`, and the 60/5/2 constants are the catalogue's, not an interpretation.
RS06/RS07 stay refused because `dim_kpi.formula` is the empty string.

**#18 `技术骨干留任率` is refused for a compiler reason, not a data one** — and the page
says which. The value is computable (the source formula's cumulative term cancels
algebraically, leaving `(tech_lead_headcount − 当月 Tech/Team Lead 减员件数) × 100 ÷
tech_lead_headcount` = `46.1538`, matching `fact`), but `:formula` may only reference
columns of its own declared class, and `raw_hr_event` (the numerator's month) has no key to
`dim_hr_monthly` (the denominator). Probed: `REFUSED … 'count', not a column of the joined
classes`. Two ways in: materialise `severance_lead_events` as a `dim_hr_monthly` column, or
declare a same-period join key between the two tables. Open question for the business: in
2026-09 the source formula is `0×N/0` → NULL while the definition gives `98.80%`.

Monthly series arrived with publish `1794404310-52eb0f` (23 `…ByMonth` metrics). Seven of
them are named for their semantics rather than after the snapshot metric
(`oeePctByMonth`, `digitalReuseRateByMonth`, `severanceSatisfactionByMonth`,
`customsComplianceRateByMonth`, …), so `kpi_map.json` declares those seven mappings
explicitly with `series` + `series_why` instead of renaming the ontology's metrics. #11 and
#14 have no month grain at all and stay snapshot-only (the page says so in the card).

**Ordering trap:** `apply` copies the staging tree over the live profile — *including
`kpi_map.json`*. Editing the map between `stage` and `apply` loses the edit (measured: the
seven `series` mappings written at 21:45 came back as the 21:33 staged version). Edit the
declaration first, stage second, or redo the edit after an apply. The generator prints
`[STAGED-ONLY]` when the `.ttl` on disk is newer than the applied publish, so a render from
an unapplied declaration is never silent.

### 10.4 Accepted divergences (written down, not hidden)

| KPI | Divergence | Reason |
|---|---|---|
| 11 生态伙伴轻资产化指数 | ontology `37.5%` vs fact `0` | the old formula filtered `entity_type='eco_partner'`; the column holds `core`/`partner`, so it was always 0. `3/8 = 37.5%` is on the same scale as the 25% target. |
| 21 员工价值交换制度落地率 | value `5.06` (0–10) vs target `80%` | `dim_sentiment_monthly` stores a 0–10 score; `dim_kpi.unit` says `%`. The KPI can never be met — the page shows both numbers so the contradiction is visible. |
| RS05 海关违规/罚款金额 | no `fact` row | `fact_kpi_monthly.kpi_id` was sanitised to `RS05_海关违规_罚款金额` and `unit` written as `%`; the ontology computes 24.6 万元 from the raw side. |

### 10.5 There are THREE generations, and the ontology reproduces the older one

Corrected 2026-11-11 after the cross-check the reader asked for. The first version of this
section claimed the old pages' numbers "match no month in either DB copy". That was **wrong**:
it had compared them against the 23-table copy only. They match the *other* copy exactly, and
the two copies are two different data generations:

| Generation | Pages | Database | Shapes |
|---|---|---|---|
| **G1** 2026-07-25 | `agent-workspace/…/dashboard/html/` (14 pages) | `…/dashboard/sunhing_kpi.db` — **23 tables** (`dim_*_monthly` + detail `raw_*`), produced by `deepresearch-custom-workflow/phase7_dashboard_generation/src/kpi_db.py` | 25 KPI rows (the join drops the 3 sanitised ids) |
| **G2** 2026-09-28 | `data/analysis_dbs/sunhing_dashboard*.html` (11 pages) | `data/analysis_dbs/sunhing_kpi.db` — **16 tables**, produced by the dashboard package's own `codes/sunhing_kpi_db.py` | 28 KPI rows |
| **G3** 2026-11-11 | `data/analysis_dbs/sunhing_ontology_*.html` (6 pages) | PostgreSQL `sunhing_kpi`, migrated from **G1's** 23-table copy | 28 KPI rows |

The two SQLite copies disagree on the data, not on the catalogue: `dim_kpi` has identical
names / factors / units / **targets** in both (0 differences), while **137 of the 149 shared
`fact_kpi_monthly` cells differ** and `fact_roe_summary` tells two different stories
(G1: ROE −9.4% → 4.3%, margin −4.3 → 2.1; G2: ROE 21.5% → 50.0%, margin 34.1 → 66.1).
G2 also keeps the raw `RS05_海关违规/罚款金额` ids; G1 sanitised them to `_`.

**Which is newer is not what file dates say.** G2's file is dated later (Nov 3 vs Oct 8) but
its *content* is the September build: its 28 values match the Sep-28 pages 28/28, and G1's
values match the Jul-25 pages. The Sept regeneration ran the older 16-table generator; the
Phase-7 pipeline's 23-table database is the one the ontology was built on.

Consequence, measured by the same cross-check:

| comparison | agreement |
|---|---|
| G3 (ontology) vs G2 (Sep-28 pages) | **2 / 28** (only #01 and #20, which coincide in both) |
| G3 (ontology) vs G1 (Jul-25 pages) | **22 / 25** (+#17 equal up to display rounding) |

The three remaining differences from G1 are *not* data:

1. **#11 生态伙伴轻资产化指数 — the one number this renderer deliberately changes.** G1 shows
   `0.0` (its formula filters `entity_type='eco_partner'`, a value the column never takes);
   the ontology filters `partner` and shows `37.5%` (3 of 8 partners profitable). That flips
   the KPI from "miss" to "met" against the 25% target. It is declared in
   `accepted_issues` with the reason, but it is a *judgement*, so it is listed here.
2. **#18 技术骨干留任率** — G1 shows `46.1%`; the ontology refuses (the formula needs two
   tables joined on the period, and `:formula` may only use its own class's columns).
3. **#17** — `61.0` vs `61.3`: the same number at different display precision.

Rows G1 never had (RS05/RS06/RS07 — its join dropped the sanitised ids) are in G2 and G3.

### 10.6 Making the cockpit the app's entry page (2026-11-11)

The Analysis panel lists **databases, not files** ("一个数据库 = 一个入口页 + 若干子页").
`GET /api/analysis/databases` groups pages with `services/dashboard_keys.family_key_of`
(meta `db:` basename, else the filename prefix, plus the curated `databases.json` match
prefixes), and `_pick_home` chooses the page a click opens in this order:

1. the registry's `home` for that key,
2. the first page whose meta says `entry: hub`,
3. `<key>_dashboard.html`,
4. the newest page.

Three things were missing, and each one alone was enough for the new pages to look like
"just one more file" instead of the cockpit:

| Missing | Symptom | Fix |
|---|---|---|
| no `LangConfig Dashboard Meta` block | the API reported `db: None, entry: None` for all six pages, so `_pick_home` could not see a hub | `_meta_block()` writes the same block the 2026-09 pages carry (`db:` identical, so both generations stay in ONE card) |
| relative nav hrefs | fine from disk, wrong inside the panel's iframe (the panel's own comment records a relative asset resolving against the wrong origin) | absolute `/api/files/…`, the convention the rest of the folder follows |
| registry `home` still `sunhing_dashboard.html` | rule 1 beat rule 2: clicking the Sun Hing card opened the **2026-09** hub — the eight new pages were listed but unreachable from the entry | `databases.json` → `home: sunhing_ontology_hub.html` |

The hub's nav also lists the six pages this renderer does not produce (employees, liability,
raw data, Gantt, ERD, intro) under a labelled group — they are the 2026-09 data generation, and
the label says so, so nothing became unreachable and no page silently mixes generations.

Verified in the running app (headless, through the panel's iframe): card → hub (`28 项 KPI`
line present) → each of the five factor pages renders (kpi cards / charts / table rows /
insight box present) → 11 nav links on the hub.

### 10.7 D3 charts (2026-11-11): treemap, sankey, radar

Plotly draws the two trend charts well and nothing else the cockpit needs. Three shapes were added
with D3 — each for a reason a bar or line would hide:

| Chart | Where | Why this shape |
|---|---|---|
| **treemap** (`d3.treemap`) | hub (all 28 KPIs), every factor page (its own) | one tile per KPI, area = one KPI, **colour = status**, and the factor rectangles keep the grouping the catalogue declares — the whole board's health in one glance, including the three refusals (grey) |
| **sankey** (`d3-sankey`) | hub (money, 万元), support page (people) | a flow must **balance**: 计划减员 856 = 已完成 810 + 未完成 46; 赔偿实付 4948.8 = 预算内 3852 + 超预算 1096.8; 应追缴 6643 = 已化解 5678 + 未化解 965. If a number stops adding up, the picture stops adding up |
| **radar** (hand-rolled with `d3.line().curveLinearClosed`) | hub | the five factor averages against the same 0–100 axis — the one comparison the hub exists for |

Every number in these charts is passed in from Python (`payload["charts"]`), built from the same
`run_metric` results as the cards: nothing is recomputed in the browser, and the three refusals stay
refusals (grey tiles, not invented values).

**Offline.** `backend/static/d3.min.js` (v7.9.2) and `d3-sankey.min.js` (v0.12.3) are vendored, and
`main.py:_swap_plotly_cdn_to_local` rewrites the CDN URLs in any served page — the same treatment
Plotly already had, so a proxy-only browser gets charts instead of blank boxes. If D3 is missing
anyway, each container prints that the library did not load and the rest of the page keeps working
(a blank area would read as "the numbers failed").

Verified in a headless browser through the app's own iframe: `#kpiTree` 28 tiles, `#sankeyCash`
6 nodes / 4 links, `#factorRadar` 1 polygon, both Plotly charts still drawn, zero page errors.

### 10.8 Drill-down, the third flow layer, and the sunburst

1. **Treemap tile → the KPI it stands for.** Each tile carries the KPI's number and scrolls to
   `#kpi-<no>` on the hub (its row in the factor section) or `#c<no>` on a factor page (its chart
   card), flashing a ring for 1.6 s. The board stays put — nothing opens elsewhere.
2. **Sankey third layer = 部门.** `severedCountByDepartment` is the only declaration that splits
   people by department, and it is used **only when the parts add up to the whole**: 13 departments
   sum to exactly 810 = `hrSeveranceCompletedCumulative`, so 计划减员 856 → 已完成 810 → 13 部门,
   with 未完成 46 as the other leaf. When the sum does not match, the layer is dropped and `--check`
   prints `[FLOW] <metric> 合计 X ≠ 已减员 Y`, because a distribution nobody declared is worse than
   a missing one. **Money has no declared department split** — the cash Sankey stays two layers on
   purpose; adding a third would mean inventing the allocation.
3. **Sunburst on every factor page:** inner ring = one KPI (coloured by its snapshot status), outer
   ring = its six declared months (coloured by *that month's* status against the same target). The
   monthly verdict uses the same `judge()` the cards use, so a red slice and a red card always mean
   the same thing.

Verified headless: hub 28 tiles, a tile click scrolled 0 → 697 px and ringed row `kpi-06`; support
Sankey 16 nodes / 15 links with the department labels; profit sunburst 63 arcs; zero page errors.
