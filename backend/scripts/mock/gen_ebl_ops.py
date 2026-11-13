#!/usr/bin/env python3
"""生成 EBL OS（team-2）模拟数据集：把《11 亿营收目标与防御性毛利守护方案》变成可核查的库。

设计原则（来自 generate-mock-dataset 技能）：

* **断言先于数据**：方案里的每个数字都是一条可被查询证伪的 claim，写在
  `data/mock/ebl_ops/ebl_ops.dataset.json` 里，由 `check_dataset.py` 执行。
* **金额从目标往下分配，不是随机加总再凑**：季度目标固定（2.5/2.7/2.9/2.9 亿），
  在每个 (季度, 档位) 内按权重分配到订单行，再等比缩放到目标值 —— 于是季度与全年合计**精确**命中。
* **约束在构造上成立**：低毛利订单的行只能从利用率 <70% 的产线里抽，因此"违规 0 条"不是运气。
* **病理按设计植入**（不是随机漏）：分级在双签前为 NULL、年底仍有未分级客户；回款准时率有未记录；
  比价拖账是文本；订单头金额与行合计差 1.5%；一家供应商账期缺失。

用法：
    python backend/scripts/mock/gen_ebl_ops.py --dbname ebl_ops --seed 20260101
    python backend/scripts/mock/gen_ebl_ops.py --dbname ebl_ops --reset      # 重建
"""
from __future__ import annotations

import argparse
import datetime as dt
import random
import sys

import psycopg2
from psycopg2.extras import execute_values

# ── 方案里的数字（改数据前先改这里，否则门禁绿着而故事已经变了）─────────────────
FY2026_REVENUE = 1_100_000_000          # §一 11 亿
FY2025_REVENUE = 900_000_000            # §一 去年 9 亿
Q2026 = [250_000_000, 270_000_000, 290_000_000, 290_000_000]   # §四 季度节奏
Q2025 = [210_000_000, 220_000_000, 230_000_000, 240_000_000]
FY2026_MARGIN = 18.7                    # 目标区间 18–19% 的中点（校准时用）
HEADCOUNT = 2800                        # §二 约 2800 人
DEPARTMENTS = [("销售", 180), ("研发", 220), ("生产", 1800), ("行政", 180), ("人事", 230), ("财务", 190)]
IDLE_UTILIZATION = (55.0, 69.0)         # §四 低毛利订单只喂 <70% 的产线
BUSY_UTILIZATION = (70.0, 92.0)

# 产品档位：毛利率区间来自 §四；营收占比是要满足加权毛利的（校准时不动这些区间）
TIERS = {
    "差异化":      {"share": 0.23, "margin": (25.0, 28.0), "center": 26.5, "skus": 100},
    "标准":        {"share": 0.51, "margin": (15.0, 18.0), "center": 16.5, "skus": 200},
    "低毛利走量":   {"share": 0.23, "margin": (13.0, 16.0), "center": 14.5, "skus": 90},
    "微改良":      {"share": 0.03, "margin": (25.0, 28.0), "center": 26.5, "skus": 30},
}
GROWTH_BUCKETS = ("存量基本盘", "A 老客户加购", "B 新客户", "C 微改良")

CUSTOMERS = 180
CORE_CUSTOMERS = 12
NEW_CUSTOMERS_2026 = 30
ORDERS_FY2026_PER_Q = 600              # 2400 单
ORDERS_FY2025_PER_Q = 550              # 2200 单
LINES_PER_ORDER = 4

SURNAMES = "陈林黄张李王吴刘蔡杨许郑谢周叶郭邱曾廖赖徐"
GIVEN = "志明淑芬雅婷建宏美玲俊杰怡君家豪佩珊文彬丽华宗翰"
COMPANY_A = "东莞|深圳|广州|佛山|惠州|中山|珠海|厦门|苏州|宁波"
COMPANY_B = "精工|明辉|恒信|启盛|广达|锐志|博远|泰和|永安|昌隆"
COMPANY_C = "眼镜|光学|实业|科技|制造|贸易"
REGIONS = ["华南", "华东", "海外"]


def q(cur, sql: str, params=None) -> list[tuple]:
    """Run a query and return its rows (psycopg2's execute() returns None, not a cursor)."""
    cur.execute(sql, params or ())
    return cur.fetchall()


def _name(rng: random.Random) -> str:
    return rng.choice(SURNAMES) + rng.choice(GIVEN)


def _company(rng: random.Random, i: int) -> str:
    return f"{rng.choice(COMPANY_A.split('|'))}{rng.choice(COMPANY_B.split('|'))}{rng.choice(COMPANY_C.split('|'))}{i:03d}号"


# ── DDL ────────────────────────────────────────────────────────────────────────
DDL = """
DROP TABLE IF EXISTS order_adjustments, order_lines, orders, low_margin_approvals,
                     leads, core_customers, micro_improvements, opex_items,
                     customers, products, production_lines, suppliers, employees,
                     rule_regimes CASCADE;

CREATE TABLE rule_regimes (
  id serial PRIMARY KEY, at date NOT NULL, change text NOT NULL, source text
);

CREATE TABLE customers (
  id serial PRIMARY KEY,
  name text NOT NULL,
  region text NOT NULL CHECK (region IN ('华南','华东','海外')),
  source_channel text CHECK (source_channel IN ('转介绍','展会存量转化','存量老客户')),
  entered_at date NOT NULL,                       -- 首次合作
  churned_at date,                                 -- 停止合作（NULL = 仍在合作）
  purchase_amount_2025 numeric(14,2),
  gross_margin_2025 numeric(5,2),
  on_time_payment_rate numeric(5,2),               -- NULL = 未记录（病理）
  price_compare_behavior text,                     -- 文本，不是分数（病理）
  dim_margin_band text CHECK (dim_margin_band IN ('A','B','C')),
  dim_purchase_band text CHECK (dim_purchase_band IN ('A','B','C')),
  dim_payment_band text CHECK (dim_payment_band IN ('A','B','C')),
  dim_behavior_band text CHECK (dim_behavior_band IN ('A','B','C')),
  segment text CHECK (segment IN ('A','B','C')),   -- NULL = 未分级（病理）
  segment_scored_at date,
  is_boundary boolean DEFAULT false,
  arbitrated_by text,
  segment_rule_version text
);

CREATE TABLE products (
  id serial PRIMARY KEY,
  sku text UNIQUE NOT NULL,
  name text NOT NULL,
  category text NOT NULL CHECK (category IN ('镜架','镜片','配件')),
  tier text NOT NULL CHECK (tier IN ('差异化','标准','低毛利走量','微改良')),
  list_price numeric(12,2) NOT NULL,
  certification_premium numeric(5,2)               -- %，仅微改良且已认证的产品非空
);

CREATE TABLE production_lines (
  id serial PRIMARY KEY,
  code text UNIQUE NOT NULL,
  name text NOT NULL,
  capacity_units_month integer NOT NULL,
  utilization numeric(5,2) NOT NULL,               -- 方案口径输入，不可复算
  status text NOT NULL DEFAULT '运行' CHECK (status IN ('运行','关停','合并')),
  closed_at date,
  note text
);

CREATE TABLE suppliers (
  id serial PRIMARY KEY,
  name text NOT NULL,
  is_top10 boolean NOT NULL DEFAULT false,
  payment_days integer,                            -- NULL = 账期未记录（病理）
  spend_2025 numeric(14,2),
  spend_2026 numeric(14,2),
  unit_price_index_2025 numeric(8,2) DEFAULT 100,
  unit_price_index_2026 numeric(8,2)
);

CREATE TABLE employees (
  id serial PRIMARY KEY,
  name text NOT NULL,
  department text NOT NULL CHECK (department IN ('销售','研发','生产','行政','人事','财务')),
  hired_at date NOT NULL,
  left_at date,
  leave_reason text CHECK (leave_reason IN ('主动离职','退休','合同到期','裁员'))
);

CREATE TABLE core_customers (
  customer_id integer PRIMARY KEY REFERENCES customers(id),
  seq integer NOT NULL,
  locked_at date NOT NULL,
  approved_by text NOT NULL
);

CREATE TABLE micro_improvements (
  id serial PRIMARY KEY,
  kind text NOT NULL CHECK (kind IN ('微改良','认证')),
  title text NOT NULL,
  product_id integer REFERENCES products(id),
  status text NOT NULL CHECK (status IN ('立项','试产','客户验证中','已验证','已回撤')),
  started_at date NOT NULL,
  verified_at date,
  retreated_at date
);

CREATE TABLE opex_items (
  id serial PRIMARY KEY,
  category text NOT NULL,
  amount_2025 numeric(14,2) NOT NULL,
  amount_2026 numeric(14,2),
  freezable boolean NOT NULL,
  frozen_at date,
  approved_by text
);

CREATE TABLE leads (
  id serial PRIMARY KEY,
  source_channel text NOT NULL CHECK (source_channel IN ('转介绍','展会存量转化')),
  created_at date NOT NULL,
  is_qualified boolean NOT NULL,
  converted_customer_id integer REFERENCES customers(id)
);

CREATE TABLE orders (
  id serial PRIMARY KEY,
  order_no text UNIQUE NOT NULL,
  customer_id integer NOT NULL REFERENCES customers(id),
  order_date date NOT NULL,
  fiscal_year integer NOT NULL,
  quarter integer NOT NULL CHECK (quarter BETWEEN 1 AND 4),
  promised_date date,
  actual_date date,
  revenue_header numeric(14,2) NOT NULL,           -- 订单头口径（≠ 行合计，病理）
  currency text NOT NULL DEFAULT 'RMB' CHECK (currency = 'RMB')   -- 单一币种：跨币种换算在此不成立
);

CREATE TABLE low_margin_approvals (
  id serial PRIMARY KEY,
  order_line_id integer,                           -- 行插入后回填
  reason text NOT NULL,
  signed_by_sales text NOT NULL,
  signed_by_finance text NOT NULL,
  signed_at date NOT NULL,
  review_due_at date NOT NULL,
  reviewed_at date
);

CREATE TABLE order_lines (
  id serial PRIMARY KEY,
  order_id integer NOT NULL REFERENCES orders(id),
  product_id integer NOT NULL REFERENCES products(id),
  production_line_id integer REFERENCES production_lines(id),
  qty integer NOT NULL CHECK (qty > 0),
  unit_price numeric(12,2) NOT NULL,
  revenue numeric(14,2) NOT NULL CHECK (revenue > 0),
  cost numeric(14,2) NOT NULL,
  gross_margin numeric(5,2) NOT NULL,
  tier text NOT NULL CHECK (tier IN ('差异化','标准','低毛利走量','微改良')),
  growth_bucket text NOT NULL CHECK (growth_bucket IN ('存量基本盘','A 老客户加购','B 新客户','C 微改良')),
  certification_premium numeric(5,2),
  approval_id integer REFERENCES low_margin_approvals(id),
  commission_factor numeric(4,2) NOT NULL DEFAULT 1.0
);

CREATE TABLE order_adjustments (
  id serial PRIMARY KEY,
  order_id integer NOT NULL REFERENCES orders(id),
  kind text NOT NULL CHECK (kind IN ('折扣','返利')),
  amount numeric(14,2) NOT NULL
);

CREATE INDEX ON orders (order_date);
CREATE INDEX ON orders (fiscal_year, quarter);
CREATE INDEX ON order_lines (order_id);
CREATE INDEX ON order_lines (production_line_id);
CREATE INDEX ON order_lines (tier);
CREATE INDEX ON customers (segment);
"""


def quarter_dates(year: int, quarter: int) -> tuple[dt.date, dt.date]:
    start_month = 3 * (quarter - 1) + 1
    start = dt.date(year, start_month, 1)
    end = dt.date(year + (1 if quarter == 4 else 0), 1 if quarter == 4 else start_month + 3, 1) - dt.timedelta(days=1)
    return start, end


def build(cur, seed: int) -> dict:
    rng = random.Random(seed)
    today = dt.date(2026, 12, 31)

    # ── 治理：制度切换点 ──────────────────────────────────────────────────
    execute_values(cur, "INSERT INTO rule_regimes (at, change, source) VALUES %s", [
        (dt.date(2026, 1, 5), "任务 1 启动：数据口径统一", "§六 第 1 周"),
        (dt.date(2026, 2, 2), "华南大区试点分级", "§六 第 2 周"),
        (dt.date(2026, 3, 20), "A/B/C 定义文件双签 —— 此前无分级", "§六 第 3 周"),
        (dt.date(2026, 4, 1), "全公司推开：名单与资源重配落地", "§六 第 4 周"),
    ])
    SCORED = dt.date(2026, 3, 20)

    # ── 产线：7 条 <70%（低毛利订单的唯一去处）────────────────────────────
    lines = []
    for i in range(1, 33):
        idle = i <= 7
        util = round(rng.uniform(*IDLE_UTILIZATION) if idle else rng.uniform(*BUSY_UTILIZATION), 2)
        status, closed_at = "运行", None
        if i in (8, 9):                     # §八 关停两条最低效的高负载线
            status, closed_at = "关停", dt.date(2026, 9, 30)
        lines.append((f"L{i:02d}", f"{'闲置' if idle else '量产'}线 {i:02d}",
                      rng.randrange(12000, 42000), util, status, closed_at,
                      "利用率 <70%：低毛利填产能订单仅可落在此线（§四）" if idle else None))
    execute_values(cur, "INSERT INTO production_lines (code,name,capacity_units_month,utilization,status,closed_at,note) VALUES %s", lines)
    idle_ids = [r[0] for r in q(cur, "SELECT id FROM production_lines WHERE utilization < 70 ORDER BY id")]
    busy_ids = [r[0] for r in q(cur, "SELECT id FROM production_lines WHERE utilization >= 70 ORDER BY id")]

    # ── 产品：四档，微改良里有 2 个已认证（溢价 2–3%）────────────────────
    products = []
    n = 0
    certified = 0
    for tier, cfg in TIERS.items():
        for k in range(cfg["skus"]):
            n += 1
            cat = rng.choice(["镜架", "镜片", "配件"])
            premium = None
            if tier == "微改良" and certified < 2:
                premium = round(rng.uniform(2.0, 3.0), 2)
                certified += 1
            products.append((f"SKU{n:04d}", f"{cat}·{tier}{k+1:02d}", cat, tier,
                             round(rng.uniform(30, 480), 2), premium))
    execute_values(cur, "INSERT INTO products (sku,name,category,tier,list_price,certification_premium) VALUES %s", products)
    tier_product_ids: dict[str, list[int]] = {t: [] for t in TIERS}
    for pid, tier, prem in q(cur, "SELECT id, tier, certification_premium FROM products"):
        tier_product_ids[tier].append((pid, prem))

    # ── 客户：180 家（12 核心 / 30 家 2026 新客 / 其余存量）───────────────
    customers = []
    new_ids = []
    for i in range(1, CUSTOMERS + 1):
        entered = dt.date(2025, 1, 1) + dt.timedelta(days=rng.randrange(0, 330))
        source = rng.choice(["存量老客户", "转介绍", "展会存量转化"])
        if i > CUSTOMERS - NEW_CUSTOMERS_2026:   # 新客排在最后，与核心客户不相交（§三）
            entered = dt.date(2026, 1, 10) + dt.timedelta(days=rng.randrange(0, 320))
            source = rng.choice(["转介绍", "展会存量转化"])
            new_ids.append(i)
        purchase = round(rng.uniform(2_000_000, 130_000_000), 2)
        gm2025 = round(rng.uniform(11.0, 31.0), 2)
        pay = None if rng.random() < 0.12 else round(rng.uniform(62.0, 99.5), 2)   # 病理
        behavior = None if rng.random() < 0.09 else rng.choice(
            ["无", "无", "多次比价", "拖账 30+ 天", "拖账 90+ 天"])

        def band_margin(v):
            return "A" if v >= 24 else ("C" if v < 16 else "B")

        def band_purchase(v):
            return "A" if v >= 60_000_000 else ("C" if v < 12_000_000 else "B")

        def band_payment(v):
            if v is None:
                return "C"           # 未记录按最低档处理，并在口径说明里写明（业务决定）
            return "A" if v >= 95 else ("C" if v < 80 else "B")

        def band_behavior(v):
            return {"无": "A", "多次比价": "B", "拖账 30+ 天": "C", "拖账 90+ 天": "C"}.get(v or "", "C")

        bands = [band_margin(gm2025), band_purchase(purchase), band_payment(pay), band_behavior(behavior)]
        a_count, c_count = bands.count("A"), bands.count("C")
        segment = "A" if a_count >= 3 else ("C" if c_count >= 3 else "B")
        boundary = rng.random() < 0.04          # §六 边界争议 ≤5%
        scored = SCORED + dt.timedelta(days=rng.randrange(0, 250))
        if scored > today:
            scored = today
        customers.append((
            _company(rng, i), rng.choice(REGIONS), source, entered, None,
            purchase, gm2025, pay, behavior,
            *bands, segment, scored, boundary,
            ("销售副总+财务总监" if boundary else None), "v1",
        ))
    execute_values(cur, """INSERT INTO customers
        (name,region,source_channel,entered_at,churned_at,purchase_amount_2025,gross_margin_2025,
         on_time_payment_rate,price_compare_behavior,dim_margin_band,dim_purchase_band,
         dim_payment_band,dim_behavior_band,segment,segment_scored_at,is_boundary,arbitrated_by,
         segment_rule_version) VALUES %s""", customers)

    # 病理：双签前未分级 —— 所有在 2026-03-20 之前"应该已经分级"的客户，segment 置 NULL，
    # 再让约 18% 的客户到年底仍未完成分级（评分日期晚于年底的清零）
    # 病理（§六 "数据质量差则维度降权并注明"）：约 20% 的客户到年底仍未完成分级，
    # 另有一批 2026-10 之后才进来的客户还没到评分时点 —— 这两类 segment 与四个档位都是 NULL。
    cur.execute("""UPDATE customers SET segment=NULL, segment_scored_at=NULL,
                          dim_margin_band=NULL, dim_purchase_band=NULL,
                          dim_payment_band=NULL, dim_behavior_band=NULL
                    WHERE id % 5 = 0 OR entered_at > DATE '2026-10-01'""")

    all_ids = [r[0] for r in q(cur, "SELECT id FROM customers ORDER BY id")]

    # 核心客户：12 家（其中 1 家 FY2026 之后不再下单 → 流失 1 家 ≤ 2）
    core_pick = all_ids[:CORE_CUSTOMERS]
    execute_values(cur, "INSERT INTO core_customers (customer_id,seq,locked_at,approved_by) VALUES %s",
                   [(cid, i + 1, dt.date(2026, 3, 31), "总经理") for i, cid in enumerate(core_pick)])
    churned_core = core_pick[0]
    cur.execute("UPDATE customers SET churned_at = DATE '2026-05-31' WHERE id = %s", (churned_core,))

    # ── 员工：2800 人，6 部门，含离职（不裁员）───────────────────────────
    emps = []
    eid = 0
    for dept, count in DEPARTMENTS:
        for _ in range(count):
            eid += 1
            hired = dt.date(2018, 1, 1) + dt.timedelta(days=rng.randrange(0, 2900))
            left, reason = None, None
            if rng.random() < 0.06:                       # 6% 离职，全部非裁员（§十）
                left = dt.date(2026, 1, 1) + dt.timedelta(days=rng.randrange(0, 360))
                reason = rng.choice(["主动离职", "主动离职", "退休", "合同到期"])
            emps.append((_name(rng), dept, hired, left, reason))
    execute_values(cur, "INSERT INTO employees (name,department,hired_at,left_at,leave_reason) VALUES %s", emps)

    # ── 供应商 40 家（前 10 标记；1 家账期缺失）──────────────────────────
    sup = []
    for i in range(1, 41):
        top = i <= 10
        spend25 = round(rng.uniform(30_000_000, 260_000_000), 2) if top else round(rng.uniform(1_000_000, 28_000_000), 2)
        idx25 = 100.0
        idx26 = round(idx25 * (1 - rng.uniform(0.03, 0.05)) if top else idx25 * (1 - rng.uniform(-0.01, 0.04)), 2)
        days = None if i == 17 else rng.choice([30, 45, 60, 60, 90, 120])
        spend26 = round(spend25 * rng.uniform(1.02, 1.12), 2)
        sup.append((_company(rng, 300 + i), top, days, spend25, spend26, idx25, idx26))
    execute_values(cur, """INSERT INTO suppliers
        (name,is_top10,payment_days,spend_2025,spend_2026,unit_price_index_2025,unit_price_index_2026)
        VALUES %s""", sup)

    # ── 非生产性支出 28 科目（可冻结项 Q1 冻结）────────────────────────────
    opex_cats = ["差旅", "招待", "非必要外包", "展会展位", "市场推广", "IT 订阅", "办公租赁",
                 "培训", "车辆", "仓储", "保险", "审计费", "招聘", "年会", "样品制作",
                 "客户拜访", "快递", "水电", "物业", "保洁", "安保", "绿化", "食堂",
                 "员工活动", "体检", "咨询费", "认证费", "软件许可"]
    opex = []
    for i, cat in enumerate(opex_cats, start=1):
        freezable = cat in ("差旅", "招待", "非必要外包", "展会展位", "市场推广", "培训", "年会",
                            "客户拜访", "员工活动", "咨询费")
        a25 = round(rng.uniform(200_000, 9_000_000), 2)
        a26 = round(a25 * (0.45 if freezable else rng.uniform(0.95, 1.12)), 2)
        frozen = dt.date(2026, 1, 31) if freezable and rng.random() < 0.8 else None
        opex.append((cat, a25, a26, freezable, frozen, "行政部" if frozen else None))
    execute_values(cur, "INSERT INTO opex_items (category,amount_2025,amount_2026,freezable,frozen_at,approved_by) VALUES %s", opex)

    # ── 微改良 5 个 + 认证 2 项 ───────────────────────────────────────────
    micro_pids = [p for p, _ in tier_product_ids["微改良"]]
    mi = []
    for i, title in enumerate(["镜架铰链轻量化（减重 12%）", "镜片镀膜耐刮等级提升",
                               "鼻托硅胶配方改良", "包装结构减材（可回收）",
                               "镜腿弹性合金替换"], start=1):
        status = "已验证" if i <= 3 else ("客户验证中" if i == 4 else "试产")
        verified = dt.date(2026, 7, 15) + dt.timedelta(days=20 * i) if status == "已验证" else None
        mi.append(("微改良", title, micro_pids[i % len(micro_pids)],
                   status, dt.date(2026, 4, 10) + dt.timedelta(days=15 * i), verified, None))
    for i, title in enumerate(["出口欧盟 CE 认证（镜片）", "美国 FDA 注册（镜架）"], start=1):
        mi.append(("认证", title, micro_pids[-(i)], "已验证",
                   dt.date(2026, 5, 1) + dt.timedelta(days=40 * i), dt.date(2026, 9, 30), None))
    execute_values(cur, """INSERT INTO micro_improvements
        (kind,title,product_id,status,started_at,verified_at,retreated_at) VALUES %s""", mi)

    # ── 线索：转介绍 / 展会存量转化（§三），有效询盘率约 38% ───────────────
    lead_rows = []
    for _ in range(900):
        ch = rng.choice(["转介绍", "展会存量转化"])
        created = dt.date(2026, 1, 5) + dt.timedelta(days=rng.randrange(0, 360))
        qualified = rng.random() < 0.38
        lead_rows.append((ch, created, qualified, None))
    execute_values(cur, "INSERT INTO leads (source_channel,created_at,is_qualified,converted_customer_id) VALUES %s", lead_rows)

    # ── 事实：FY2025 / FY2026 ─────────────────────────────────────────────
    def build_year(year: int, targets: list[int], orders_per_q: int) -> list[tuple]:
        """按 (季度, 档位) 精确分配营收；毛利率在档位区间内取，并校准到 FY 目标。"""
        line_rows: list[dict] = []
        order_rows = []
        order_id = 0
        for qi, target in enumerate(targets, start=1):
            start, end = quarter_dates(year, qi)
            days = (end - start).days + 1
            pool = all_ids if year == 2025 else [c for c in all_ids if c != churned_core]
            # 新客户订单权重：30 家 × 0.40 ≈ 7.4% 的订单 → 营收约 0.67 亿（§四 B 0.6–0.8 亿）
            _w = [0.40 if c in new_ids else 1.0 for c in pool]
            q_start = len(order_rows)                 # 这一季自己的订单，不是累计
            for _ in range(orders_per_q):
                order_id += 1
                cust = rng.choices(pool, weights=_w, k=1)[0]
                d = start + dt.timedelta(days=rng.randrange(0, days))
                promised = d + dt.timedelta(days=rng.choice([21, 30, 30, 45, 60]))
                late = rng.random() < (0.06 if cust in core_pick else 0.13)
                actual = promised + dt.timedelta(days=rng.randrange(1, 16)) if late else promised - dt.timedelta(days=rng.randrange(0, 6))
                order_rows.append({
                    "no": f"SO{year}{order_id:05d}", "cust": cust, "date": d,
                    "fy": year, "q": qi, "promised": promised, "actual": actual, "lines": [],
                })
            # 每季度 × 每档位的目标营收
            quarter_orders = order_rows[q_start:]
            for tier, cfg in TIERS.items():
                tier_target = target * cfg["share"]
                n_lines = max(1, int(round(orders_per_q * LINES_PER_ORDER * cfg["share"])))
                picks = [quarter_orders[rng.randrange(len(quarter_orders))] for _ in range(n_lines)]
                weights = [rng.lognormvariate(0, 0.55) for _ in picks]
                scale = tier_target / sum(weights)
                for order, w in zip(picks, weights):
                    order["lines"].append({"tier": tier, "revenue": w * scale})
        # 精确修正：每个 (季度,档位) 的合计与目标差多少，补到该组最大的一行上
        for qi, target in enumerate(targets, start=1):
            for tier, cfg in TIERS.items():
                pool = [ln for o in order_rows if o["q"] == qi and o["fy"] == year
                        for ln in o["lines"] if ln["tier"] == tier]
                if not pool:
                    continue
                delta = target * cfg["share"] - sum(ln["revenue"] for ln in pool)
                biggest = max(pool, key=lambda x: x["revenue"])
                biggest["revenue"] += delta
        return order_rows

    def insert_year(order_rows: list[dict], year: int) -> None:
        execute_values(cur, """INSERT INTO orders
            (order_no,customer_id,order_date,fiscal_year,quarter,promised_date,actual_date,revenue_header)
            VALUES %s""",
            [(o["no"], o["cust"], o["date"], o["fy"], o["q"], o["promised"], o["actual"],
              round(sum(ln["revenue"] for ln in o["lines"]) * 1.015, 2)) for o in order_rows])
        # 用 order_no 回查 id（插入顺序与列表一致，但用 SQL 取更稳）
        id_by_no = {r[0]: r[1] for r in q(cur, "SELECT order_no, id FROM orders WHERE fiscal_year = %s", (year,))}
        rows = []
        approvals = []
        for o in order_rows:
            oid = id_by_no[o["no"]]
            for ln in o["lines"]:
                tier = ln["tier"]
                premium = None
                lo, hi = TIERS[tier]["margin"]
                gm = min(hi, max(lo, TIERS[tier]["center"] + rng.uniform(-1.4, 1.4)))
                revenue = round(ln["revenue"], 2)
                if revenue <= 0:
                    revenue = 100.0
                cost = round(revenue * (1 - gm / 100.0), 2)
                if tier == "低毛利走量":
                    pid = rng.choice(tier_product_ids[tier])[0]
                    line_id = rng.choice(idle_ids)          # 只喂 <70% 的产线（构造上合规）
                    bucket = "存量基本盘"                     # 由配额重分配（见下）
                    comm = 0.5                              # §四 提成减半
                else:
                    pid, prem = rng.choice(tier_product_ids[tier])
                    line_id = rng.choice(busy_ids)
                    bucket = "存量基本盘"                     # 由配额重分配（见下）
                    comm = 1.0
                    premium = prem if tier == "微改良" else None
                qty = max(1, int(revenue / max(1.0, rng.uniform(28, 320))))
                rows.append((oid, pid, line_id, qty, round(revenue / qty, 2), revenue, cost,
                             round(gm, 2), tier, bucket, premium, None, comm))
                if tier == "低毛利走量":
                    approvals.append(len(rows) - 1)
        execute_values(cur, """INSERT INTO order_lines
            (order_id,product_id,production_line_id,qty,unit_price,revenue,cost,gross_margin,
             tier,growth_bucket,certification_premium,approval_id,commission_factor) VALUES %s""", rows)
        ids = [r[0] for r in q(cur, """SELECT ol.id FROM order_lines ol JOIN orders o ON o.id = ol.order_id
                                        WHERE o.fiscal_year = %s ORDER BY ol.id""", (year,))]
        appr = []
        appr_lines = []
        for idx in approvals:
            line_id = ids[idx]
            appr_lines.append(line_id)
            signed = dt.date(2026, 1, 1) + dt.timedelta(days=rng.randrange(0, 300)) if year == 2026 else dt.date(2025, 3, 1)
            due = signed + dt.timedelta(days=180)                       # §四 6 个月复审
            reviewed = None if rng.random() < 0.25 else due - dt.timedelta(days=rng.randrange(0, 20))
            appr.append((rng.choice(["产能利用率 <70% 填产能", "战略客户临时让价"]),
                         "销售总监", "财务总监", signed, due, reviewed))
        execute_values(cur, """INSERT INTO low_margin_approvals
            (reason,signed_by_sales,signed_by_finance,signed_at,review_due_at,reviewed_at)
            VALUES %s""", appr)
        appr_ids = [r[0] for r in q(cur, """SELECT id FROM low_margin_approvals
                                             ORDER BY id DESC LIMIT %s""", (len(appr),))][::-1]
        for line_id, appr_id in zip(appr_lines, appr_ids):
            cur.execute("UPDATE low_margin_approvals SET order_line_id = %s WHERE id = %s", (line_id, appr_id))
            cur.execute("UPDATE order_lines SET approval_id = %s WHERE id = %s", (appr_id, line_id))
        # growth_bucket 的营收配额（§四：B 0.6–0.8 亿 / C 0.3–0.4 亿 / A 0.2–0.3 亿）
        if year == 2026:
            A_CAP = 25_000_000
            cur.execute("""UPDATE order_lines ol SET growth_bucket =
                             CASE
                               WHEN ol.tier = '微改良' THEN 'C 微改良'
                               WHEN c.id IN (SELECT id FROM customers WHERE id = ANY(%s)) THEN 'B 新客户'
                               ELSE ol.growth_bucket
                             END
                             FROM orders o JOIN customers c ON c.id = o.customer_id
                            WHERE o.id = ol.order_id AND o.fiscal_year = 2026""", (list(new_ids),))
            # A 老客户加购：按营收升序取老客户差异化行，累计到 2.5 千万为止
            picked, running = [], 0.0
            for line_id, revenue in q(cur, """SELECT ol.id, ol.revenue FROM order_lines ol
                                                JOIN orders o ON o.id = ol.order_id
                                                JOIN customers c ON c.id = o.customer_id
                                               WHERE o.fiscal_year = 2026 AND ol.tier = '差异化'
                                                 AND c.id <> ALL(%s) AND ol.growth_bucket = '存量基本盘'
                                               ORDER BY ol.id""", (list(new_ids),)):
                if running + float(revenue) > A_CAP:
                    continue
                picked.append(line_id)
                running += float(revenue)
            if picked:
                cur.execute("UPDATE order_lines SET growth_bucket = 'A 老客户加购' WHERE id = ANY(%s)", (picked,))

        # 折扣/返利：约 1.5% 的差额落在 order_adjustments（两套营收口径的病理）
        adj = []
        for o in order_rows:
            oid = id_by_no[o["no"]]
            lines_sum = sum(ln["revenue"] for ln in o["lines"])
            if rng.random() < 0.5:
                adj.append((oid, "折扣", round(-lines_sum * rng.uniform(0.005, 0.025), 2)))
            else:
                adj.append((oid, "返利", round(-lines_sum * rng.uniform(0.002, 0.012), 2)))
        execute_values(cur, "INSERT INTO order_adjustments (order_id,kind,amount) VALUES %s", adj)

    # 保证那个"流失的核心客户"在 FY2025 确实下过单（否则流失无从谈起）
    t_core = next(o for o in enumerate(all_ids) if True)[0] if False else churned_core
    fy25 = build_year(2025, Q2025, ORDERS_FY2025_PER_Q)
    while not any(o["cust"] == churned_core for o in fy25):
        o = fy25[hash(churned_core) % len(fy25)]
        o["cust"] = churned_core
    insert_year(fy25, 2025)
    fy26 = build_year(2026, Q2026, ORDERS_FY2026_PER_Q)
    insert_year(fy26, 2026)

    # ── 校准：把 FY2026 加权毛利调到 18–19% 的中点（只在档位区间内平移）────────
    def weighted_margin() -> float:
        r = q(cur, """SELECT round(sum(revenue*gross_margin)/sum(revenue), 3) FROM order_lines ol
                       JOIN orders o ON o.id = ol.order_id WHERE o.fiscal_year = 2026""")
        return float(r[0][0] or 0)

    for _ in range(15):
        current = weighted_margin()
        shift = FY2026_MARGIN - current
        if abs(shift) < 0.03:
            break
        for tier, cfg in TIERS.items():
            lo, hi = cfg["margin"]
            cur.execute("""UPDATE order_lines ol
                              SET gross_margin = round(least(%s, greatest(%s, gross_margin + %s))::numeric, 2)
                             FROM orders o
                            WHERE o.id = ol.order_id AND o.fiscal_year = 2026 AND ol.tier = %s""",
                        (hi, lo, shift, tier))
        cur.execute("""UPDATE order_lines ol SET cost = round(revenue * (1 - gross_margin/100.0), 2)
                         FROM orders o WHERE o.id = ol.order_id AND o.fiscal_year = 2026""")

    cur.execute("ANALYZE")
    return {}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Generate the EBL OS mock dataset")
    ap.add_argument("--dbname", default="ebl_ops")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=5433)
    ap.add_argument("--user", default="langconfig")
    ap.add_argument("--seed", type=int, default=20260101)
    ap.add_argument("--reset", action="store_true", help="drop and rebuild every table")
    args = ap.parse_args(argv)

    import os
    conn = psycopg2.connect(host=args.host, port=args.port, dbname=args.dbname,
                            user=args.user, password=os.environ.get("PGPASSWORD", ""))
    conn.autocommit = True
    cur = conn.cursor()
    exists = cur.execute("SELECT to_regclass('public.orders')") or cur.fetchone()
    if exists and not args.reset:
        print(f"{args.dbname}: 已有表，拒绝覆盖（要重建请加 --reset）", file=sys.stderr)
        return 1
    cur.execute(DDL)
    build(cur, args.seed)
    print(f"{args.dbname}: built with seed {args.seed}")
    for table in ("customers", "products", "production_lines", "suppliers", "employees", "core_customers",
                  "micro_improvements", "opex_items", "leads", "orders", "order_lines",
                  "low_margin_approvals", "order_adjustments", "rule_regimes"):
        n = (cur.execute(f"SELECT count(*) FROM {table}") or cur.fetchone())[0]
        print(f"  {table:24} {n:>6}")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
