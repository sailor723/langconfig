#!/usr/bin/env python3
"""生成 team-3《產出標工與效率計算》的模拟数据集 `eff_ops`。

故事来源：`client/team-3/產出標工與效率計算-規格.md`（工具已存在，T1/T2/T4 已验收）。
本数据集不重写工具，而是把那套**已经被手工表验证过的口径**变成可被 SQL 复算的库：

    i（當月完成品標準工時）= Σ 標工秒數 × 報數 / 3600 × (舊款 ? 0.85 : 1)
    m（考核出勤工時）      = Σ 計入考核的人員工時 + 調入 − 調出 ± 調整 − 申訴扣減 + 被申訴
    n（實際效率）          = i / m
    l（目標定額工時）      = i / j
    達標                   = n ≥ j

**原始事实入库，指标由 SQL 复算**：`production_row` / `timesheet` / `bango_detail` 只放原始行，
`std_time` 放標工，`kpi_snapshot` 放"手工表当年算出的那个数"——于是"复算 vs 快照"本身就是一条可失败的对账。

精确性靠**残差吸收**：每个 (廠, 部門, 月) 的最后一行的標工秒数或工时，被反算成需要的值
（Excel 里的標工本来就是小数），因此 5771.679 / 96.48% 这些锚点是算出来的，不是写死的。

    python backend/scripts/mock/gen_eff_ops.py --dbname eff_ops --seed 20261001 --reset
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import random

import psycopg2
from psycopg2.extras import execute_values

MONTH = "202610"
DG, HY = "DG", "HY"

# ── 规格里的锚点（改动前先改这里；门禁就是拿它们对账）─────────────────────────
# (廠, 部門, i 目標秒數, m 目標小時, j 目標效率)
# m_kind: 'base' = 这个数是"按规则加总的底数"（HY 那三个，来自 §D 对账）；
#         'final' = 这个数是 KPI 表的最终"考核出勤工时"（DG 那两部，再加减帮工/调整）
ANCHORS = {
    ("DG", "金架九部"):    {"i_hours": 5771.679014476938, "m_hours": 5982.306661, "m_kind": "final",
                            "base_hours": 6170.206661, "j": 0.92},
    ("DG", "金架燒焊部"):  {"i_hours": 8884.684, "m_hours": 12095.367, "m_kind": "final", "j": 0.85},
    ("HY", "膠架五部"):    {"i_hours": None, "m_hours": 21529.57, "m_kind": "base", "j": 0.76},
    ("HY", "脾形中心"):    {"i_hours": None, "m_hours": 10794.47, "m_kind": "base", "j": 0.84},
    ("HY", "配件部/鐳射組"): {"i_hours": None, "m_hours": 973.67, "m_kind": "base", "j": 0.87},
}
DG_FRONT = 2317.6480          # 金架九部前段
DG_BACK = 3454.0311           # 金架九部後段

# DG 幫工（規格 §D2 的對賬表）：調出只計參與考核者；調入全計
BANGO_OUT = {"金架燒焊部": 468.5, "金架磨光部": 104.5, "脾形部": 361.5,
             "注塑噴塗部": 180.5, "加色部": 1698.98, "注塑成品部": 16.0}
BANGO_OUT_KPI = {"注塑成品部": 43.0}          # KPI 把浮动借出的 27h 也计入了
BANGO_IN = {"配件一部": 546.0, "金架成品部": 748.0, "金架燒焊部": 346.0,
            "金架磨光部": 405.0, "脾形部": 67.5, "注塑成品部": 782.72}

FRONT_DESC = "SH分公司前工序"
BACK_DESCS = ("SH分公司包裝", "SH分公司包裝HY")
NEW_PREFIXES = ("M3", "T14", "H128", "H129", "T15")
PERSON_CLASSES = ["生產-纳入效率计算", "生產-固定人员", "生產-办单", "生產-纳入效率计算"]
KPI_ATTRS = ["其他", "其他", "非W轉W級", "浮動", "做辦", "其他"]
ADJUST = {("DG", "金架九部"): [("調整工時", -27.9, "PIE 手工調整"), ("申訴扣減", -160.0, "申訴扣減（负值即扣减）")],
          ("HY", "配件部"): [("調整工時", 202.8, "PIE 手工調整")]}

DDL = """
DROP TABLE IF EXISTS kpi_snapshot, kpi_target, adjustments, bango_detail, timesheet,
                     production_row, std_time, material_master, rule_regimes CASCADE;

CREATE TABLE rule_regimes (
  id serial PRIMARY KEY, at date NOT NULL, change text NOT NULL, source text
);

CREATE TABLE material_master (
  part_no text PRIMARY KEY,      -- 物料主檔：查得到 = 新款
  category text
);

CREATE TABLE std_time (
  id serial PRIMARY KEY,
  part_no text NOT NULL,                       -- 款號（比對不區分大小寫）
  side text NOT NULL CHECK (side IN ('front', 'back')),
  work_center_desc text,                       -- 標工庫裡該段對應的工作中心
  seconds numeric(12,4) NOT NULL CHECK (seconds >= 0),
  UNIQUE (part_no, side)
);

CREATE TABLE production_row (
  id serial PRIMARY KEY,
  factory text NOT NULL CHECK (factory IN ('DG','HY')),
  dept text NOT NULL,
  month text NOT NULL,                         -- YYYYMM
  order_no text NOT NULL,                      -- 生產單號
  part_no text NOT NULL,                       -- 成品款號
  model_prefix text,                           -- 款號前 4 位（新舊款判定的第一层）
  work_center_desc text NOT NULL,
  kind_a text NOT NULL CHECK (kind_a IN ('架','配件')),
  qty_report integer NOT NULL,                 -- 生產報數（唯一取數欄）
  qty_pr integer,                              -- 生產報數PR（配件行 = 報數/2，病理：两列不等）
  timeliness text NOT NULL,                    -- 時效（'不計' 排除）
  src_row integer                              -- Excel 行號（可定位）
);

CREATE TABLE timesheet (
  id serial PRIMARY KEY,
  factory text NOT NULL CHECK (factory IN ('DG','HY')),
  dept text NOT NULL,                          -- 部門屬性（考核歸屬）
  month text NOT NULL,
  emp_no text NOT NULL,
  name text NOT NULL,
  person_class text NOT NULL,                  -- 人員分類（含 -固定人员 / -办单 / -纳入效率计算）
  kpi_attr text NOT NULL CHECK (kpi_attr IN ('其他','非W轉W級','浮動','做辦','固定','W級')),
  employment text NOT NULL CHECK (employment IN ('在職','離職')),
  hours numeric(10,4) NOT NULL                 -- 含加班
);

CREATE TABLE bango_detail (
  id serial PRIMARY KEY,
  factory text NOT NULL CHECK (factory IN ('DG','HY')),
  month text NOT NULL,
  emp_no text NOT NULL,
  name text NOT NULL,
  from_dept text NOT NULL,                     -- 原部門（左表）
  to_dept text NOT NULL,                       -- 借調部門（右表）
  direction text NOT NULL CHECK (direction IN ('調出','調入')),
  hours numeric(10,4) NOT NULL,
  level1 text NOT NULL,                        -- W級 / 非W級
  kpi_attr text NOT NULL,                      -- 決定調出是否計入
  note text
);

CREATE TABLE kpi_target (
  factory text NOT NULL, dept text NOT NULL, month text NOT NULL,
  target numeric(6,4) NOT NULL CHECK (target > 0 AND target <= 1),
  PRIMARY KEY (factory, dept, month)
);

CREATE TABLE adjustments (
  id serial PRIMARY KEY,
  factory text NOT NULL, dept text NOT NULL, month text NOT NULL,
  kind text NOT NULL CHECK (kind IN ('調整工時','申訴扣減','被申訴')),
  hours numeric(10,2) NOT NULL,
  note text
);

CREATE TABLE kpi_snapshot (
  factory text NOT NULL, dept text NOT NULL, month text NOT NULL,
  i_hours numeric(14,4),                       -- 手工表当年的 i（None = 该厂未做产量侧）
  m_hours numeric(14,4),                       -- KPI 表 考核效率的總出勤工時
  n_ratio numeric(8,4),                        -- KPI 表 實際效率
  review_hours numeric(14,4),                  -- W級調整前出勤工時（工具算的底數，用于对账）
  source text,
  PRIMARY KEY (factory, dept, month)
);

CREATE INDEX ON production_row (factory, dept, month);
CREATE INDEX ON production_row (part_no);
CREATE INDEX ON timesheet (factory, dept, month);
CREATE INDEX ON bango_detail (factory, direction);
"""


def q(cur, sql, params=None):
    cur.execute(sql, params or ())
    return cur.fetchall()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Generate the team-3 efficiency mock dataset")
    ap.add_argument("--dbname", default="eff_ops")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=5433)
    ap.add_argument("--user", default="langconfig")
    ap.add_argument("--seed", type=int, default=20261001)
    ap.add_argument("--reset", action="store_true")
    args = ap.parse_args(argv)
    rng = random.Random(args.seed)

    conn = psycopg2.connect(host=args.host, port=args.port, dbname=args.dbname,
                            user=args.user, password=os.environ.get("PGPASSWORD", ""))
    conn.autocommit = True
    cur = conn.cursor()
    if q(cur, "SELECT to_regclass('public.production_row')") [0][0] and not args.reset:
        print(f"{args.dbname}: 已有表，拒绝覆盖（--reset 重建）")
        return 1
    cur.execute(DDL)

    # ── 制度切换点（口径变更史，来自规格）────────────────────────────────────
    execute_values(cur, "INSERT INTO rule_regimes (at, change, source) VALUES %s", [
        (dt.date(2026, 10, 1), "驗收基準月：2026 年 10 月手工表 / KPI 表", "規格 v1"),
        (dt.date(2026, 11, 13), "數量一律取 `生產報數`，不再取 `生產報數PR`（配件行 PR=報數/2）", "規格 §A 口徑變更"),
        (dt.date(2026, 11, 13), "0.85 係數只對舊款生效（來源未查明，照抄行為）", "規格 §進一步說明"),
    ])

    def make_part(i: int) -> str:
        prefix = rng.choice(["M3", "T14", "H128", "M290", "T150", "H129"])
        return f"{prefix}{i:05d}"

    # ── 標工庫：每個款號 前段/後段 各一個秒數 ─────────────────────────────────
    parts = [make_part(i) for i in range(1, 901)]
    std_rows, master_rows = [], []
    for p in parts:
        # 80% 新款（物料主檔查得到或前缀命中）；20% 舊款（主檔查不到）
        if rng.random() < 0.8:
            master_rows.append((p, rng.choice(["鏡架", "鏡片", "配件"])))
        for side, desc in (("front", FRONT_DESC), ("back", rng.choice(BACK_DESCS))):
            secs = round(rng.uniform(600, 5400), 4)
            std_rows.append((p, side, desc, secs))
    execute_values(cur, "INSERT INTO material_master (part_no, category) VALUES %s", master_rows)
    execute_values(cur, "INSERT INTO std_time (part_no, side, work_center_desc, seconds) VALUES %s", std_rows)

    # ── 產量明細：每個 (廠,部門) 造行；最后一个锚点部门做残差吸收 ──────────────
    prod_rows: list[tuple] = []
    src_row = 2
    dg_depts = ["金架九部", "金架燒焊部", "金架磨光部", "金架成品部", "脾形部", "注塑噴塗部",
                "注塑成品部", "配件一部", "CNC圈形部/生產", "加色部"]
    hy_depts = ["膠架二部", "膠架三部", "膠架五部", "配件部", "配件部/鐳射組", "脾形中心",
                "CNC中心", "加色部"]
    # 部门私有款号池：每部门 40 个，互不相交
    pools: dict[tuple[str, str], list[str]] = {}
    cursor_idx = 0
    for _factory, _depts in ((DG, dg_depts), (HY, hy_depts)):
        for _d in _depts:
            pools[(_factory, _d)] = parts[cursor_idx:cursor_idx + 40]
            cursor_idx += 40
    for factory, depts in ((DG, dg_depts), (HY, hy_depts)):
        for dept in depts:
            n_rows = rng.randrange(40, 90)
            pool = pools[(factory, dept)]
            for k in range(n_rows):
                p = rng.choice(pool)
                is_accessory = rng.random() < 0.12
                side_desc = FRONT_DESC if (not is_accessory and rng.random() < 0.5) else rng.choice(BACK_DESCS)
                qty = rng.randrange(20, 600)
                if rng.random() < 0.03:
                    # 病理：查不到標工的款號（异常清单要能点名）
                    p = f"UNK{src_row:05d}"
                    cur.execute("INSERT INTO std_time (part_no, side, work_center_desc, seconds) "
                                "VALUES (%s,'front',%s,0) ON CONFLICT DO NOTHING", (p, FRONT_DESC))
                prod_rows.append((
                    factory, dept, MONTH, f"{factory}{dept[:2]}{1000+k}", p, p[:4],
                    side_desc,
                    "配件" if is_accessory else "架",
                    qty, qty // 2 if is_accessory else qty,
                    "不計" if rng.random() < 0.03 else "計入",
                    src_row,
                ))
                src_row += 1
    execute_values(cur, """INSERT INTO production_row
        (factory,dept,month,order_no,part_no,model_prefix,work_center_desc,kind_a,
         qty_report,qty_pr,timeliness,src_row) VALUES %s""", prod_rows)

    # ── 工時明細：每部門按其錨點總額造，最後一行吸收残差 ─────────────────────
    def insert_timesheet(factory: str, dept: str, total_hours: float,
                         review_hours: float | None = None) -> None:
        rows, acc = [], 0.0
        n = rng.randrange(25, 60)
        weighted_class = ["生產-纳入效率计算", "生產-纳入效率计算", "生產-固定人员", "生產-办单"]
        for k in range(n):
            cls = rng.choice(weighted_class)
            kpi = rng.choice(KPI_ATTRS)
            emp = f"{factory}{rng.randrange(10000, 99999)}"
            hours = round(rng.uniform(120, 260), 4)
            rows.append([factory, dept, MONTH, emp, f"員工{k:03d}", cls, kpi,
                         "離職" if rng.random() < 0.04 else "在職", hours])
            # 只有"計入考核"的行计入底数（规则见规格 §D）：固定/办单/做辦/浮動 全部排除
            counts = not (("固定人员" in cls) or ("办单" in cls) or (kpi in ("做辦", "浮動")))
            if counts:
                acc += hours
        # 残差：让"按规则加总"精确等于目标（残差可以为负，就从不计入的行里扣）
        residual = round(total_hours - acc, 4)
        if residual > 0:
            rows.append([factory, dept, MONTH, f"{factory}99999", "殘差行", "生產-纳入效率计算",
                         "其他", "在職", residual])
        elif residual < 0 and acc > 0:
            # 超了：按比例缩"計入考核"的那些行（固定/办单/浮动的工时不影响合计，保持原样）
            factor = total_hours / acc
            for r in rows:
                if not (("固定人员" in r[5]) or ("办单" in r[5]) or (r[6] in ("做辦", "浮動"))):
                    r[8] = round(r[8] * factor, 4)
            # 再补一次零头，保证精确
            new_acc = sum(r[8] for r in rows
                          if not (("固定人员" in r[5]) or ("办单" in r[5]) or (r[6] in ("做辦", "浮動"))))
            gap = round(total_hours - new_acc, 4)
            if abs(gap) > 1e-6:
                big = max((i for i, r in enumerate(rows)
                           if not (("固定人员" in r[5]) or ("办单" in r[5]) or (r[6] in ("做辦", "浮動")))),
                          key=lambda i: rows[i][8])
                rows[big][8] = round(rows[big][8] + gap, 4)
        execute_values(cur, """INSERT INTO timesheet
            (factory,dept,month,emp_no,name,person_class,kpi_attr,employment,hours) VALUES %s""", rows)

    insert_timesheet(DG, "金架九部", 6170.206661, 6170.206661)   # 底數（W級調整前出勤工時）
    # 燒焊部的锚点是最终 m：底数 = 最终 − 调入(346) + 调出(468.5)
    insert_timesheet(DG, "金架燒焊部", 12095.367 - BANGO_IN["金架燒焊部"] + BANGO_OUT["金架燒焊部"])
    insert_timesheet(HY, "膠架五部", 21529.57, None)
    insert_timesheet(HY, "脾形中心", 10794.47, None)
    insert_timesheet(HY, "配件部/鐳射組", 973.67, None)
    for dept in ("金架磨光部", "金架成品部", "脾形部", "注塑噴塗部", "注塑成品部", "配件一部",
                 "CNC圈形部/生產", "加色部"):
        insert_timesheet(DG, dept, round(rng.uniform(3000, 16000), 2), None)
    for dept in ("膠架二部", "膠架三部", "配件部", "CNC中心", "加色部"):
        insert_timesheet(HY, dept, round(rng.uniform(3000, 20000), 2), None)

    # ── 幫工明細：調出（只計參與考核）/ 調入（全計）─────────────────────────
    bango = []
    # 調出：可计部分等分到 n 行（保证合计精确），另加"不计入"的浮动/做辦行作为对照证据
    for dept, target in BANGO_OUT.items():
        n = 4
        each = round(target / n, 2)
        acc = 0.0
        for k in range(n - 1):
            bango.append([DG, MONTH, f"DG{50000 + k}", f"借出{k}", dept, "借調部門X",
                          "調出", each, "非W級", "其他", None])
            acc += each
        bango.append([DG, MONTH, "DG50099", "借出末", dept, "借調部門X", "調出",
                      round(target - acc, 2), "非W級", "其他", None])
        # 注塑成品部：KPI 43 = 16（参与考核）+ 27（浮动借出，应剔除）—— 反例锚点
        floating = 27.0 if dept == "注塑成品部" else round(rng.uniform(8, 30), 2)
        bango.append([DG, MONTH, "DG50100", "浮動借出", dept, "借調部門X", "調出", floating,
                      "非W級", "浮動", "浮动借出不计入调出（KPI 曾把它算进去）"])
    # 調入：全部计入，等分保证精确
    for dept, target in BANGO_IN.items():
        n = 3
        each = round(target / n, 2)
        acc = 0.0
        for k in range(n - 1):
            bango.append([DG, MONTH, f"DG{60000 + k}", f"借入{k}", "原部門Y", dept, "調入",
                          each, "W級" if k % 2 else "非W級", "其他", None])
            acc += each
        bango.append([DG, MONTH, "DG60099", "借入末", "原部門Y", dept, "調入",
                      round(target - acc, 2), "非W級", "其他", None])

    execute_values(cur, """INSERT INTO bango_detail
        (factory,month,emp_no,name,from_dept,to_dept,direction,hours,level1,kpi_attr,note)
        VALUES %s""", bango)

    # ── 效率目标 j ───────────────────────────────────────────────────────────
    targets = []
    for (factory, dept), cfg in ANCHORS.items():
        targets.append((factory, dept, MONTH, cfg["j"]))
    for dept, j in (("金架磨光部", 0.87), ("金架成品部", 0.80), ("脾形部", 0.84), ("配件一部", 0.88),
                    ("注塑噴塗部", 0.82), ("注塑成品部", 0.83), ("CNC圈形部/生產", 0.81),
                    ("加色部", 0.80), ("膠架二部", 0.76), ("膠架三部", 0.76), ("配件部", 0.87),
                    ("CNC中心", 0.81)):
        factory = HY if dept in ("膠架二部", "膠架三部", "配件部", "CNC中心") else DG
        targets.append((factory, dept, MONTH, j))
    execute_values(cur, "INSERT INTO kpi_target (factory,dept,month,target) VALUES %s", targets)

    # ── 调整项（手填，留痕）──────────────────────────────────────────────────
    adj = []
    for (factory, dept), items in ADJUST.items():
        for kind, hours, note in items:
            adj.append((factory, dept, MONTH, kind, hours, note))
    execute_values(cur, "INSERT INTO adjustments (factory,dept,month,kind,hours,note) VALUES %s", adj)

    # ── KPI 快照：手工表当年算出的数（对账的另一半）───────────────────────────
    snaps = []
    for (factory, dept), cfg in ANCHORS.items():
        i_h = cfg["i_hours"]
        m_h = cfg["m_hours"]
        n = round(i_h / m_h, 4) if i_h else None
        review = 6170.206661 if (factory, dept) == (DG, "金架九部") else None
        snaps.append((factory, dept, MONTH, i_h, m_h, n, review,
                      "客戶手工表 / KPI 工作簿 2026.10"))
    execute_values(cur, """INSERT INTO kpi_snapshot
        (factory,dept,month,i_hours,m_hours,n_ratio,review_hours,source) VALUES %s""", snaps)

    # ── 每个有 i 锚点的部门都要精确命中（含旧款 0.85 系数）────────────────────
    def coef_sql() -> str:
        return """case when (left(upper(pr.part_no),2)='M3'
                            or left(upper(pr.part_no),3) in ('T14','T15')
                            or left(upper(pr.part_no),4) in ('H128','H129'))
                       or mm.part_no is not null then 1.0 else 0.85 end"""

    def balance(factory: str, dept: str, target_hours: float, side: str | None) -> None:
        """把该部门（该侧）的产出标工精确调到 target_hours。

        side=None 表示"这个部门的两段一起算"：此时 JOIN 必须按工作中心决定是前段还是后段，
        否则只缩放后段、前段保留随机值，总数永远对不上（实测过一次，差 80%）。
        """
        side_key = side or "back"
        if side is None:
            join_cond = ("st.side = CASE WHEN pr.work_center_desc = %s THEN 'front' ELSE 'back' END")
            join_param = FRONT_DESC
            scope, scope_params = "", []
        else:
            join_cond = "st.side = %s"
            join_param = side_key
            scope = " AND pr.work_center_desc = %s" if side == "front" else " AND pr.work_center_desc = ANY(%s)"
            scope_params = [FRONT_DESC] if side == "front" else [list(BACK_DESCS)]

        def current() -> float:
            return float(q(cur, f"""
                SELECT coalesce(sum(st.seconds * pr.qty_report / 3600.0 * {coef_sql()}), 0)
                  FROM production_row pr
                  LEFT JOIN std_time st ON upper(st.part_no) = upper(pr.part_no) AND {join_cond}
                  LEFT JOIN material_master mm ON upper(mm.part_no) = upper(pr.part_no)
                 WHERE pr.month=%s AND pr.factory=%s AND pr.dept=%s
                   AND pr.kind_a='架' AND pr.timeliness <> '不計' {scope}""",
                ([join_param, MONTH, factory, dept] + scope_params))[0][0])

        cur_val = current()
        if cur_val <= 0:
            return
        factor = target_hours / cur_val
        target_side_sql = (f"st.side = %s" if side else
                           "st.side IN ('front','back')")
        target_side_param = [side_key] if side else []
        cur.execute(f"""UPDATE std_time st SET seconds = round((st.seconds * %s)::numeric, 8)
                         WHERE {target_side_sql} AND st.part_no IN (
                           SELECT DISTINCT upper(pr.part_no) FROM production_row pr
                            WHERE pr.month=%s AND pr.factory=%s AND pr.dept=%s
                              AND pr.kind_a='架' AND pr.timeliness <> '不計' {scope})""",
                    ([factor] + target_side_param + [MONTH, factory, dept] + scope_params))
        # 零头：专用款号吸收
        again = current()
        gap = target_hours - again
        if abs(gap) > 1e-4:
            rows = q(cur, f"""
                SELECT pr.id, pr.qty_report, {coef_sql()} AS coef FROM production_row pr
                  LEFT JOIN material_master mm ON upper(mm.part_no) = upper(pr.part_no)
                 WHERE pr.month=%s AND pr.factory=%s AND pr.dept=%s
                   AND pr.kind_a='架' AND pr.timeliness <> '不計' {scope}
                 ORDER BY pr.id DESC LIMIT 1""", ([MONTH, factory, dept] + scope_params))
            if rows:
                rid, qty, coef = rows[0]
                bal_part = f"BAL{dept[:10]}{side_key}"[:28]
                cur.execute("INSERT INTO material_master (part_no, category) VALUES (%s,'鏡架') ON CONFLICT DO NOTHING", (bal_part,))
                cur.execute("""UPDATE production_row SET part_no=%s, model_prefix=%s,
                                      work_center_desc = CASE WHEN %s='front' THEN %s ELSE %s END
                                WHERE id=%s""",
                            (bal_part, bal_part[:4], side_key, FRONT_DESC, BACK_DESCS[0], rid))
                need = gap * 3600.0 / max(1, qty) / max(float(coef), 1e-9)
                cur.execute("""INSERT INTO std_time (part_no, side, work_center_desc, seconds)
                               VALUES (%s,%s,%s,%s)
                               ON CONFLICT (part_no, side) DO UPDATE SET seconds = EXCLUDED.seconds""",
                            (bal_part, side_key, FRONT_DESC if side == "front" else BACK_DESCS[0],
                             round(max(0.01, need), 6)))

    balance(DG, "金架九部", DG_FRONT, "front")
    balance(DG, "金架九部", DG_BACK, "back")

    # 其余部门：i 由 m × j × 系数 决定（没有手工锚点的部门也必须给出一个合理的效率，
    # 否则会造出 113% 这种不可能的数——实测过）
    rows_m = q(cur, """
        WITH base AS (
          SELECT t.factory, t.dept, sum(t.hours) b FROM timesheet t WHERE t.month=%s
            AND NOT (t.person_class LIKE '%%固定人员%%' OR t.person_class LIKE '%%办单%%'
                     OR t.kpi_attr IN ('做辦','浮動')) GROUP BY 1,2),
        inn AS (SELECT to_dept d, sum(hours) h FROM bango_detail WHERE direction='調入' GROUP BY 1),
        out AS (SELECT from_dept d, sum(hours) h FROM bango_detail WHERE direction='調出'
                  AND kpi_attr NOT IN ('浮動','做辦','固定') GROUP BY 1),
        adj AS (SELECT dept d, sum(hours) h FROM adjustments GROUP BY 1)
        SELECT base.factory, base.dept,
               coalesce(base.b,0) + coalesce(inn.h,0) - coalesce(out.h,0) + coalesce(adj.h,0) AS m
          FROM base LEFT JOIN inn ON inn.d = base.dept LEFT JOIN out ON out.d = base.dept
          LEFT JOIN adj ON adj.d = base.dept""", (MONTH,))
    anchor_i = {(f, d): cfg["i_hours"] for (f, d), cfg in ANCHORS.items() if cfg.get("i_hours")}
    for factory, dept, m_final in rows_m:
        if (factory, dept) == (DG, "金架九部"):
            continue
        if (factory, dept) in anchor_i:
            balance(factory, dept, anchor_i[(factory, dept)], None)
            continue
        jrow = q(cur, "SELECT target FROM kpi_target WHERE factory=%s AND dept=%s AND month=%s",
                 (factory, dept, MONTH))
        j = float(jrow[0][0]) if jrow else 0.85
        ratio = 0.88 + (rng.random() * 0.26)        # 0.88–1.14：有达标也有不达标（膠架六部式）
        balance(factory, dept, float(m_final) * j * ratio, None)

    cur.execute("ANALYZE")
    for table in ("material_master", "std_time", "production_row", "timesheet", "bango_detail",
                  "kpi_target", "adjustments", "kpi_snapshot", "rule_regimes"):
        n = q(cur, f"SELECT count(*) FROM {table}")[0][0]
        print(f"  {table:20} {n:>6}")
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
