"""
Build sunhing_kpi.db — reads raw source data from source_data.db (agent-workspace).

Data lineage:
  source_data.db (raw finance/HR/production ...)
    -> sunhing_kpi_db.py (reads + computes DuPont factors)
    -> sunhing_kpi.db
    -> gen_sunhing_kpi_dashboard.py -> HTML dashboards

DuPont factor computation (from raw_finance):
  NPM (%)      = net_income_wan / revenue_wan * 100
  AT (x)       = revenue_wan / total_assets_wan
  EM (x)       = total_assets_wan / total_equity_wan
  ROE (%)      = (NPM / 100) * AT * EM * 100
"""

import sqlite3, pathlib, random, os

# Output to agent-workspace artifact directory (via env or default)
_DASHBOARD_DIR = os.getenv("SUNHING_DASHBOARD_DIR")
if not _DASHBOARD_DIR:
    _AW_ROOT = pathlib.Path("/Users/weiping/dev/Learn/langchain-ai/agent-workspace")
    _DASHBOARD_DIR = str(_AW_ROOT / "reports/eyewear_industry/新溢眼镜/dashboard")
DB_DIR = pathlib.Path(_DASHBOARD_DIR) / "db"
DB_PATH = DB_DIR / "sunhing_kpi.db"

# Source DB (single source of truth, seeded by gen_source_db.py)
_SOURCE_DB_PATH = (
    pathlib.Path("/Users/weiping/dev/Learn/langchain-ai/agent-workspace")
    / "reports/eyewear_industry/新溢眼镜/client_input/source_data.db"
)

months = ["2026-09", "2026-10", "2026-11", "2026-12", "2027-01", "2027-02"]
month_labels = ["Sep", "Oct", "Nov", "Dec", "Jan", "Feb"]


# ── Read source_data.db ──────────────────────────────────────────────────

def load_from_source_db():
    """Read source_data.db and return a dict matching the old JSON structure.

    DuPont factors are computed from raw_finance using clear formulas:
      NPM = net_income / revenue * 100
      AT  = revenue / total_assets
      EM  = total_assets / total_equity
      ROE = (NPM/100) * AT * EM * 100
    """
    src_conn = sqlite3.connect(str(_SOURCE_DB_PATH))
    src_conn.row_factory = sqlite3.Row
    cur = src_conn.cursor()

    data = {}

    # ── kpi_dashboard ────────────────────────────────────────────────────
    data["kpi_dashboard"] = {}
    kpi_configs = cur.execute("SELECT * FROM kpi_config ORDER BY kpi_id").fetchall()
    for row in kpi_configs:
        monthly = cur.execute(
            "SELECT value FROM kpi_monthly WHERE kpi_id=? ORDER BY month_index",
            (row["kpi_id"],)
        ).fetchall()
        data["kpi_dashboard"][row["kpi_id"]] = {
            "roe_factor": row["roe_factor"],
            "unit": row["unit"],
            "target": row["target"],
            "monthly": [r["value"] for r in monthly],
            "raw_source": row["raw_source"],
            "note": row["note"],
        }

    # ── risk_dashboard ───────────────────────────────────────────────────
    data["risk_dashboard"] = {}
    risk_configs = cur.execute("SELECT * FROM risk_config ORDER BY risk_id").fetchall()
    for row in risk_configs:
        monthly = cur.execute(
            "SELECT value FROM risk_monthly WHERE risk_id=? ORDER BY month_index",
            (row["risk_id"],),
        ).fetchall()
        data["risk_dashboard"][row["risk_id"]] = {
            "risk_category": row["risk_category"],
            "unit": row["unit"],
            "target": row["target"],
            "monthly": [r["value"] for r in monthly],
            "raw_source": row["raw_source"],
            "note": row["note"],
        }

    # ── roe_summary (computed from raw_finance) ──────────────────────────
    fin_rows = cur.execute("SELECT * FROM raw_finance ORDER BY id").fetchall()
    roe_data = []
    for r in fin_rows:
        npm = round(r["net_income_wan"] / r["revenue_wan"] * 100, 1)
        at = round(r["revenue_wan"] / r["total_assets_wan"], 2)
        em = round(r["total_assets_wan"] / r["total_equity_wan"], 2)
        roe = round((npm / 100) * at * em * 100, 1)
        roe_data.append([r["month"], npm, at, em, roe])
    data["roe_summary"] = {
        "description": "ROE三因子月度趋势",
        "headers": ["month", "净利润率(%)", "资产周转率(x)", "权益乘数(x)", "ROE(%)"],
        "data": roe_data,
    }

    # ── raw_sources (fetch ALL before any iteration to avoid cursor reuse) ─
    data["raw_sources"] = {}

    hr_rows = cur.execute("SELECT * FROM raw_hr ORDER BY id").fetchall()
    data["raw_sources"]["hr_system"] = [
        {
            "month": r["month"],
            "total_headcount": r["total_headcount"],
            "production_headcount": r["production_headcount"],
            "prod_ratio_pct": r["prod_ratio_pct"],
            "severance_planned": r["severance_planned"],
            "severance_completed_cumulative": r["severance_completed_cumulative"],
            "severance_paid_cumulative_wan": r["severance_paid_cumulative_wan"],
            "a_level_tech_talent_end": r["a_talent_end"],
            "b_level_tech_talent_end": r["b_talent_end"],
            "employee_partner_converted": r["employee_partner_converted"],
        }
        for r in hr_rows
    ]

    detail_rows = cur.execute("SELECT * FROM raw_finance_detail ORDER BY id").fetchall()
    fin_map_rows = cur.execute("SELECT * FROM raw_finance ORDER BY id").fetchall()
    fin_map = {r["month"]: r for r in fin_map_rows}
    data["raw_sources"]["finance_system"] = []
    for r in detail_rows:
        fr = fin_map.get(r["month"])
        entry = {
            "month": r["month"],
            "gross_margin_pct": r["gross_margin_pct"],
            "net_profit_wan": r["net_profit_wan"],
            "severance_cost_actual_wan": r["severance_cost_actual_wan"],
            "severance_cost_budget_wan": r["severance_cost_budget_wan"],
            "liability_resolved_cumulative_wan": r["liability_resolved_cumulative_wan"],
            "liability_remaining_wan": round(6864.0 - r["liability_resolved_cumulative_wan"], 1),
            "core_factory_net_profit_wan": r["core_factory_net_profit_wan"],
            "eco_partner_net_profit_wan": r["eco_partner_net_profit_wan"],
            "total_mfg_net_profit_wan": r["total_mfg_net_profit_wan"],
            "cash_released_from_restructuring_wan": r["cash_released_wan"],
            "reinvested_in_automation_wan": r["reinvested_wan"],
            "fixed_asset_net_value_core_wan": r["fixed_asset_net_value_wan"],
            "core_factory_annualized_output_wan": r["annualized_output_wan"],
            "total_assets_wan": fr["total_assets_wan"] if fr else None,
            "total_equity_wan": fr["total_equity_wan"] if fr else None,
            "revenue_mfg_wan": fr["revenue_wan"] if fr else None,
        }
        if fr and fr["total_equity_wan"]:
            entry["debt_to_equity_ratio"] = round(
                (fr["total_assets_wan"] - fr["total_equity_wan"]) / fr["total_equity_wan"], 2
            )
        else:
            entry["debt_to_equity_ratio"] = None
        data["raw_sources"]["finance_system"].append(entry)

    prod_rows = cur.execute("SELECT * FROM raw_production ORDER BY id").fetchall()
    data["raw_sources"]["production_system"] = [
        {
            "month": r["month"],
            "critical_processes_running": r["critical_processes_running"],
            "oee_pct": r["oee_pct"],
            "output_frames_monthly": r["output_frames_monthly"],
            "defect_rate_pct": r["defect_rate_pct"],
            "machine_downtime_hours": r["machine_downtime_hours"],
        }
        for r in prod_rows
    ]

    legal_rows = cur.execute("SELECT * FROM raw_legal ORDER BY id").fetchall()
    data["raw_sources"]["legal_system"] = [
        {
            "month": r["month"],
            "new_labor_arbitration_cases": r["new_labor_arbitration_cases"],
            "pending_labor_cases": r["pending_labor_cases"],
            "major_group_incidents": r["major_group_incidents"],
            "near_miss_group_incidents": r["near_miss_group_incidents"],
            "customs_penalties_wan": r["customs_penalties_wan"],
            "customs_compliance_pct": r["customs_compliance_pct"],
        }
        for r in legal_rows
    ]

    digital_rows = cur.execute("SELECT * FROM raw_digital ORDER BY id").fetchall()
    data["raw_sources"]["digital_platform"] = [
        {
            "month": r["month"],
            "total_data_items_collected": r["total_data_items_collected"],
            "data_items_reused": r["data_items_reused"],
            "reuse_rate_pct": r["reuse_rate_pct"],
            "odai_models_deployed": r["odai_models_deployed"],
            "kdd_knowledge_density_score": r["kdd_knowledge_density_score"],
            "digital_platform_users": r["digital_platform_users"],
            "digital_cost_savings_wan": r["digital_cost_savings_wan"],
        }
        for r in digital_rows
    ]

    sentiment_rows = cur.execute("SELECT * FROM raw_sentiment ORDER BY id").fetchall()
    data["raw_sources"]["sentiment_monitoring"] = [
        {
            "month": r["month"],
            "employee_satisfaction_score": r["employee_satisfaction_score"],
            "severance_satisfaction_score": r["severance_satisfaction_score"],
            "change_readiness_score": r["change_readiness_score"],
            "negative_social_media_mentions": r["negative_social_media_mentions"],
            "positive_news_coverage": r["positive_news_coverage"],
            "competitor_poaching_intensity": r["competitor_poaching_intensity"],
        }
        for r in sentiment_rows
    ]

    src_conn.close()
    return data


# Load data from source_data.db
data = load_from_source_db()

EMPLOYEE_SURNAMES = [
    "陈", "李", "张", "王", "刘", "杨", "黄", "周", "吴", "徐",
    "孙", "胡", "朱", "林", "何", "郭", "罗", "梁", "谢", "宋",
    "邓", "许", "彭", "曾", "肖", "谭", "唐", "曹", "冯", "蔡",
    "韩", "魏", "叶", "潘", "戴", "钟", "汪", "范", "石", "姚",
    "廖", "邹", "熊", "金", "夏", "卢", "蒋", "余", "杜", "苏",
]
EMPLOYEE_GIVEN_NAMES = [
    "伟强", "志明", "建华", "国荣", "文杰", "海涛", "晓东", "嘉诚",
    "耀明", "永康", "志辉", "德民", "建军", "国平", "伟民", "文彬",
    "志强", "海波", "晓峰", "嘉俊", "耀华", "振华", "建国", "国强",
    "卫东", "文斌", "志刚", "海生", "晓明", "嘉文", "德强", "永华",
    "俊杰", "伟杰", "志鸿", "建国", "文华", "海龙", "天佑", "家豪",
    "秀英", "美玲", "秀珍", "丽华", "秀兰", "桂英", "秀芳", "玉珍",
    "玉梅", "桂芳", "秀英", "玉兰", "秀华", "美芳", "秀英", "美华",
    "小红", "秀娟", "秀英", "玉萍", "秀英", "美英", "秀珍", "玉芳",
]
SKILL_LEVELS_BY_POSITION = {
    "Operator": ["初级工", "初级工", "中级工", "中级工", "高级工"],
    "Senior Operator": ["中级工", "高级工", "高级工", "技师", "技师"],
    "Tech Lead": ["高级工", "技师", "技师", "高级技师", "高级技师"],
    "Inspector": ["中级工", "高级工", "技师", "高级技师"],
    "Team Lead": ["技师", "高级技师", "高级技师"],
}
DG_DEPARTMENTS = ["成型", "打磨", "抛光", "组装", "质检", "喷涂", "电镀", "包装"]
HY_DEPARTMENTS = ["注塑", "模具", "精加工", "装配", "质检", "物流"]
SEVERANCE_BY_MONTH = [
    ("2026-09", 0),
    ("2026-10", 120),
    ("2026-11", 220),
    ("2026-12", 220),
    ("2027-01", 160),
    ("2027-02", 90),
]
LIABILITY_ITEMS = [
    ("DG-SI-001", "社保", "东莞厂2018-2023社保欠缴(养老)", "东莞社保局", 820, 750, "分期缴纳", "2027-01", "部分化解"),
    ("DG-SI-002", "社保", "东莞厂2018-2023社保欠缴(医疗)", "东莞社保局", 410, 380, "分期缴纳", "2027-01", "部分化解"),
    ("DG-SI-003", "社保", "东莞厂2018-2023社保欠缴(失业)", "东莞社保局", 120, 120, "一次性结清", "2026-12", "已化解"),
    ("DG-SI-004", "社保", "东莞厂2018-2023社保欠缴(工伤)", "东莞社保局", 85, 85, "一次性结清", "2026-12", "已化解"),
    ("DG-SI-005", "社保", "东莞厂2018-2023社保欠缴(生育)", "东莞社保局", 55, 55, "一次性结清", "2026-12", "已化解"),
    ("DG-HF-001", "公积金", "东莞厂2015-2023住房公积金欠缴", "东莞公积金中心", 950, 800, "分期补缴协议", "2027-02", "部分化解"),
    ("DG-HF-002", "公积金", "东莞厂公积金利息及滞纳金", "东莞公积金中心", 180, 120, "协商减免+补缴", "2027-02", "部分化解"),
    ("DG-PF-001", "企业年金", "东莞厂企业年金欠缴", "东莞人社局", 320, 300, "分期补缴", "2027-01", "部分化解"),
    ("DG-TX-001", "税务", "东莞厂个人所得税代扣欠缴", "东莞税务局", 160, 160, "一次性补缴", "2026-11", "已化解"),
    ("DG-TX-002", "税务", "东莞厂附加费及其他税费欠缴", "东莞税务局", 75, 75, "一次性补缴", "2026-11", "已化解"),
    ("HY-SI-001", "社保", "河源厂2019-2023社保欠缴(养老)", "河源社保局", 520, 480, "协商分期", "2027-01", "部分化解"),
    ("HY-SI-002", "社保", "河源厂2019-2023社保欠缴(医疗)", "河源社保局", 260, 240, "协商分期", "2027-01", "部分化解"),
    ("HY-SI-003", "社保", "河源厂2019-2023社保欠缴(失业/工伤/生育)", "河源社保局", 105, 105, "一次性结清", "2026-12", "已化解"),
    ("HY-HF-001", "公积金", "河源厂2017-2023住房公积金欠缴", "河源公积金中心", 540, 420, "协商分期", "2027-02", "部分化解"),
    ("HY-HF-002", "公积金", "河源厂公积金滞纳金", "河源公积金中心", 95, 60, "减免协商中", "2027-02", "部分化解"),
    ("HY-PF-001", "企业年金", "河源厂企业年金欠缴", "河源人社局", 185, 160, "分期补缴", "2027-01", "部分化解"),
    ("HY-TX-001", "税务", "河源厂税务欠缴及滞纳金", "河源税务局", 88, 88, "一次性补缴", "2026-11", "已化解"),
    ("CF-LB-001", "劳动监察", "历史劳动监察罚款及整改费用", "东莞市劳动监察", 220, 180, "协商减免", "2027-01", "部分化解"),
    ("CF-LB-002", "劳动监察", "河源劳动监察历史欠款", "河源市劳动监察", 95, 80, "协商减免", "2027-02", "部分化解"),
    ("CF-SF-001", "社保", "异地用工社保差额追缴", "广东省社保局", 350, 300, "谈判中", "2027-02", "部分化解"),
    ("CF-SF-002", "社保", "越南工厂中国社保欠缴问题", "东莞市社保局", 150, 0, "待协商", None, "未启动"),
    ("CF-SF-003", "社保", "外籍员工社保欠缴", "东莞市社保局", 45, 0, "待协商", None, "未启动"),
    ("CF-OT-001", "其他", "历史加班费差额补偿基金(预留)", "企业自设", 400, 350, "分批发放", "2027-02", "部分化解"),
    ("CF-OT-002", "其他", "历史未休年假补偿(预估)", "企业自设", 250, 220, "分批发放", "2027-01", "部分化解"),
    ("CF-OT-003", "其他", "员工工会经费欠缴", "东莞市总工会", 165, 150, "补缴协议", "2027-02", "部分化解"),
]


def create_raw_employee_table(cursor):
    """Build the employee detail table during the main DB build."""
    cursor.execute("DROP TABLE IF EXISTS raw_employee")
    cursor.execute("""
        CREATE TABLE raw_employee (
            id INTEGER PRIMARY KEY,
            company_id INTEGER DEFAULT 1,
            employee_code TEXT,
            name_cn TEXT,
            department TEXT,
            factory TEXT,
            position_category TEXT,
            skill_level TEXT,
            tenure_years INTEGER,
            is_severed INTEGER DEFAULT 0,
            severance_month TEXT,
            compensation_wan REAL,
            has_dispute INTEGER DEFAULT 0,
            satisfaction_score REAL,
            converted_to_partner INTEGER DEFAULT 0,
            notes TEXT
        )
    """)
    rng = random.Random(42)
    shuffled_surnames = EMPLOYEE_SURNAMES * (856 // len(EMPLOYEE_SURNAMES) + 1)
    shuffled_given_names = EMPLOYEE_GIVEN_NAMES * (856 // len(EMPLOYEE_GIVEN_NAMES) + 1)
    rng.shuffle(shuffled_surnames)
    rng.shuffle(shuffled_given_names)

    severed_count = 0
    employee_id = 0
    for factory, count, departments in [("东莞", 650, DG_DEPARTMENTS), ("河源", 206, HY_DEPARTMENTS)]:
        for _ in range(count):
            employee_id += 1
            employee_code = f"EMP-{factory[:1]}{employee_id:04d}"
            name_cn = (
                shuffled_surnames[employee_id % len(shuffled_surnames)]
                + shuffled_given_names[employee_id % len(shuffled_given_names)]
            )
            department = rng.choice(departments)
            position_category = rng.choice(list(SKILL_LEVELS_BY_POSITION))
            skill_level = rng.choice(SKILL_LEVELS_BY_POSITION[position_category])
            tenure_years = rng.randint(1, 35)

            is_severed = severed_count < 810
            severance_month = None
            compensation_wan = 0.0
            has_dispute = 0
            satisfaction_score = None
            converted_to_partner = 0

            if is_severed:
                target_count = severed_count + 1
                cumulative = 0
                for month, month_count in SEVERANCE_BY_MONTH:
                    cumulative += month_count
                    if target_count <= cumulative:
                        severance_month = month
                        break
                compensation_wan = round(rng.uniform(2.5, 6.5) * (1 + tenure_years / 50), 2)
                compensation_wan = min(compensation_wan, 12.0)
                has_dispute = 1 if rng.random() < 0.02 else 0
                satisfaction_score = round(
                    rng.uniform(5, 9.5) - (0.5 if has_dispute else 0) + rng.uniform(-0.5, 0.5),
                    1,
                )
                satisfaction_score = max(1, min(10, satisfaction_score))
                converted_to_partner = 1 if rng.random() < 0.4 else 0
                severed_count += 1

            cursor.execute("""
                INSERT INTO raw_employee
                (employee_code, name_cn, department, factory, position_category,
                 skill_level, tenure_years, is_severed, severance_month,
                 compensation_wan, has_dispute, satisfaction_score, converted_to_partner)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                employee_code, name_cn, department, factory, position_category,
                skill_level, tenure_years, 1 if is_severed else 0, severance_month,
                compensation_wan, has_dispute, satisfaction_score, converted_to_partner,
            ))


def create_raw_liability_table(cursor):
    """Build the liability detail table during the main DB build."""
    cursor.execute("DROP TABLE IF EXISTS raw_liability")
    cursor.execute("""
        CREATE TABLE raw_liability (
            id INTEGER PRIMARY KEY,
            company_id INTEGER DEFAULT 1,
            item_code TEXT,
            category TEXT,
            description TEXT,
            authority TEXT,
            total_amount_wan REAL,
            resolved_wan REAL DEFAULT 0,
            remaining_wan REAL,
            resolution_method TEXT,
            resolution_month TEXT,
            status TEXT,
            priority TEXT
        )
    """)
    for item_code, category, description, authority, total_amount, resolved_amount, method, resolution_month, status in LIABILITY_ITEMS:
        remaining_wan = round(total_amount - resolved_amount, 2)
        priority = "高" if remaining_wan > 200 else ("中" if remaining_wan > 50 else "低")
        cursor.execute("""
            INSERT INTO raw_liability
            (item_code, category, description, authority, total_amount_wan,
             resolved_wan, remaining_wan, resolution_method, resolution_month, status, priority)
            VALUES (?,?,?,?,?,?,?,?,?,?,?)
        """, (
            item_code, category, description, authority, total_amount,
            resolved_amount, remaining_wan, method, resolution_month, status, priority,
        ))


def create_db(db_path: str = str(DB_PATH)):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # ================================================================
    # DIMENSION TABLES
    # ================================================================

    # --- 1. company ---
    cursor.execute("DROP TABLE IF EXISTS company")
    cursor.execute("""
        CREATE TABLE company (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            name_cn TEXT,
            industry TEXT,
            founded TEXT,
            hkex_code TEXT,
            currency TEXT DEFAULT 'HKD',
            fiscal_year_start TEXT DEFAULT '04-01'
        )
    """)
    cursor.execute(
        "INSERT INTO company VALUES (?,?,?,?,?,?,?,?)",
        (1, "Sun Hing Vision Group Holdings Ltd",
         "新兴光学集团控股有限公司 (新溢眼镜)",
         "Eyewear ODM / OEM", "1975", "00125.HK", "HKD", "04-01")
    )

    # --- 2. dim_master_kpi ---
    cursor.execute("DROP TABLE IF EXISTS dim_kpi")
    cursor.execute("""
        CREATE TABLE dim_kpi (
            kpi_id TEXT PRIMARY KEY,
            kpi_name TEXT NOT NULL,
            roe_factor TEXT,
            unit TEXT,
            target REAL,
            data_source TEXT,
            kpi_type TEXT
        )
    """)
    for kid, kd in data["kpi_dashboard"].items():
        cursor.execute(
            "INSERT OR REPLACE INTO dim_kpi VALUES (?,?,?,?,?,?,?)",
            (kid, kid[3:], kd["roe_factor"], kd["unit"], kd["target"],
             kd["raw_source"][:500], "ROE")
        )
    for rid, rd in data["risk_dashboard"].items():
        raw_target = str(rd["target"])
        parsed = raw_target.replace("≥","").replace("≤","").replace("<","").replace(">","").replace("%","").strip()
        try:
            target = float(parsed) if parsed else 0.0
        except ValueError:
            target = 100.0
        cursor.execute(
            "INSERT OR REPLACE INTO dim_kpi VALUES (?,?,?,?,?,?,?)",
            (rid, rid[4:], "风险监控", rd["unit"],
             target,
             rd["raw_source"][:500], "风险")
        )

    # ================================================================
    # FACT TABLES
    # ================================================================

    # --- 3. fact_kpi_monthly ---
    cursor.execute("DROP TABLE IF EXISTS fact_kpi_monthly")
    cursor.execute("""
        CREATE TABLE fact_kpi_monthly (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER DEFAULT 1,
            kpi_id TEXT NOT NULL,
            period TEXT NOT NULL,
            actual REAL,
            target REAL,
            unit TEXT,
            month_index INTEGER,
            FOREIGN KEY (company_id) REFERENCES company(id),
            FOREIGN KEY (kpi_id) REFERENCES dim_kpi(kpi_id)
        )
    """)
    for kid, kd in data["kpi_dashboard"].items():
        target = kd["target"]
        unit = kd["unit"]
        for i, val in enumerate(kd["monthly"]):
            cursor.execute(
                "INSERT INTO fact_kpi_monthly (kpi_id, period, actual, target, unit, month_index) VALUES (?,?,?,?,?,?)",
                (kid, months[i], float(val) if val is not None else None, target, unit, i)
            )
    for rid, rd in data["risk_dashboard"].items():
        raw_target = str(rd["target"])
        parsed = raw_target.replace("≥","").replace("≤","").replace("<","").replace(">","").replace("%","").strip()
        try:
            target = float(parsed) if parsed else 0.0
        except ValueError:
            target = 100.0
        unit = rd["unit"]
        for i, val in enumerate(rd["monthly"]):
            if val is None:
                continue
            cursor.execute(
                "INSERT INTO fact_kpi_monthly (kpi_id, period, actual, target, unit, month_index) VALUES (?,?,?,?,?,?)",
                (rid, months[i], float(val), target, unit, i)
            )

    # --- 4. fact_roe_summary ---
    cursor.execute("DROP TABLE IF EXISTS fact_roe_summary")
    cursor.execute("""
        CREATE TABLE fact_roe_summary (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER DEFAULT 1,
            period TEXT NOT NULL,
            net_profit_margin REAL,
            asset_turnover REAL,
            equity_multiplier REAL,
            roe REAL,
            month_index INTEGER,
            FOREIGN KEY (company_id) REFERENCES company(id)
        )
    """)
    for i, row in enumerate(data["roe_summary"]["data"]):
        cursor.execute(
            "INSERT INTO fact_roe_summary (period, net_profit_margin, asset_turnover, equity_multiplier, roe, month_index) VALUES (?,?,?,?,?,?)",
            (row[0], row[1], row[2], row[3], row[4], i)
        )

    # ================================================================
    # RAW SOURCE TABLES (mimicking operational systems)
    # ================================================================

    # --- 5. raw_hr ---
    cursor.execute("DROP TABLE IF EXISTS raw_hr")
    cursor.execute("""
        CREATE TABLE raw_hr (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER DEFAULT 1,
            period TEXT NOT NULL,
            total_headcount INTEGER,
            production_headcount INTEGER,
            prod_ratio_pct REAL,
            severance_planned INTEGER,
            severance_completed_cumulative INTEGER,
            severance_paid_cumulative_wan REAL,
            a_level_talent_end INTEGER,
            b_level_talent_end INTEGER,
            employee_partner_converted INTEGER,
            month_index INTEGER
        )
    """)
    for i, row in enumerate(data["raw_sources"]["hr_system"]):
        cursor.execute(
            "INSERT INTO raw_hr (period, total_headcount, production_headcount, prod_ratio_pct, severance_planned, severance_completed_cumulative, severance_paid_cumulative_wan, a_level_talent_end, b_level_talent_end, employee_partner_converted, month_index) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (row["month"], row["total_headcount"], row["production_headcount"], row["prod_ratio_pct"],
             row["severance_planned"], row["severance_completed_cumulative"], row["severance_paid_cumulative_wan"],
             row["a_level_tech_talent_end"], row["b_level_tech_talent_end"], row["employee_partner_converted"], i)
        )

    # --- 6. raw_finance ---
    cursor.execute("DROP TABLE IF EXISTS raw_finance")
    cursor.execute("""
        CREATE TABLE raw_finance (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER DEFAULT 1,
            period TEXT NOT NULL,
            gross_margin_pct REAL,
            net_profit_wan REAL,
            severance_cost_actual_wan REAL,
            liability_resolved_cumulative_wan REAL,
            liability_remaining_wan REAL,
            core_factory_net_profit_wan REAL,
            eco_partner_net_profit_wan REAL,
            total_mfg_net_profit_wan REAL,
            cash_released_wan REAL,
            reinvested_wan REAL,
            revenue_mfg_wan REAL,
            month_index INTEGER
        )
    """)
    for i, row in enumerate(data["raw_sources"]["finance_system"]):
        cursor.execute(
            "INSERT INTO raw_finance (period, gross_margin_pct, net_profit_wan, severance_cost_actual_wan, liability_resolved_cumulative_wan, liability_remaining_wan, core_factory_net_profit_wan, eco_partner_net_profit_wan, total_mfg_net_profit_wan, cash_released_wan, reinvested_wan, revenue_mfg_wan, month_index) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (row["month"], row["gross_margin_pct"], row["net_profit_wan"], row["severance_cost_actual_wan"],
             row["liability_resolved_cumulative_wan"], row["liability_remaining_wan"],
             row["core_factory_net_profit_wan"], row["eco_partner_net_profit_wan"],
             row["total_mfg_net_profit_wan"], row["cash_released_from_restructuring_wan"],
             row["reinvested_in_automation_wan"], row["revenue_mfg_wan"], i)
        )

    # --- 7. raw_production ---
    cursor.execute("DROP TABLE IF EXISTS raw_production")
    cursor.execute("""
        CREATE TABLE raw_production (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER DEFAULT 1,
            period TEXT NOT NULL,
            critical_processes_running INTEGER,
            oee_pct REAL,
            output_frames_monthly INTEGER,
            defect_rate_pct REAL,
            machine_downtime_hours REAL,
            month_index INTEGER
        )
    """)
    for i, row in enumerate(data["raw_sources"]["production_system"]):
        cursor.execute(
            "INSERT INTO raw_production (period, critical_processes_running, oee_pct, output_frames_monthly, defect_rate_pct, machine_downtime_hours, month_index) VALUES (?,?,?,?,?,?,?)",
            (row["month"], row["critical_processes_running"], row["oee_pct"],
             row["output_frames_monthly"], row["defect_rate_pct"], row["machine_downtime_hours"], i)
        )

    # --- 8. raw_legal ---
    cursor.execute("DROP TABLE IF EXISTS raw_legal")
    cursor.execute("""
        CREATE TABLE raw_legal (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER DEFAULT 1,
            period TEXT NOT NULL,
            new_labor_arbitration_cases INTEGER,
            pending_labor_cases INTEGER,
            major_group_incidents INTEGER,
            near_miss_group_incidents INTEGER,
            customs_penalties_wan REAL,
            customs_compliance_pct REAL,
            month_index INTEGER
        )
    """)
    for i, row in enumerate(data["raw_sources"]["legal_system"]):
        cursor.execute(
            "INSERT INTO raw_legal (period, new_labor_arbitration_cases, pending_labor_cases, major_group_incidents, near_miss_group_incidents, customs_penalties_wan, customs_compliance_pct, month_index) VALUES (?,?,?,?,?,?,?,?)",
            (row["month"], row["new_labor_arbitration_cases"], row["pending_labor_cases"],
             row["major_group_incidents"], row["near_miss_group_incidents"],
             row["customs_penalties_wan"], row["customs_compliance_pct"], i)
        )

    # --- 9. raw_digital_platform ---
    cursor.execute("DROP TABLE IF EXISTS raw_digital_platform")
    cursor.execute("""
        CREATE TABLE raw_digital_platform (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER DEFAULT 1,
            period TEXT NOT NULL,
            total_data_items_collected INTEGER,
            data_items_reused INTEGER,
            reuse_rate_pct REAL,
            odai_models_deployed INTEGER,
            kdd_knowledge_density_score INTEGER,
            digital_platform_users INTEGER,
            digital_cost_savings_wan REAL,
            month_index INTEGER
        )
    """)
    for i, row in enumerate(data["raw_sources"]["digital_platform"]):
        cursor.execute(
            "INSERT INTO raw_digital_platform (period, total_data_items_collected, data_items_reused, reuse_rate_pct, odai_models_deployed, kdd_knowledge_density_score, digital_platform_users, digital_cost_savings_wan, month_index) VALUES (?,?,?,?,?,?,?,?,?)",
            (row["month"], row["total_data_items_collected"], row["data_items_reused"],
             row["reuse_rate_pct"], row["odai_models_deployed"], row["kdd_knowledge_density_score"],
             row["digital_platform_users"], row["digital_cost_savings_wan"], i)
        )

    # --- 18. raw_pmo (per-milestone level) ---
    cursor.execute("DROP TABLE IF EXISTS raw_pmo")
    cursor.execute("""
        CREATE TABLE raw_pmo (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER DEFAULT 1,
            milestone_id TEXT NOT NULL,
            phase_id TEXT,
            milestone_description TEXT,
            planned_date TEXT,
            actual_date TEXT,
            status TEXT,
            completed_on_time INTEGER,
            month TEXT
        )
    """)
    from sunhing_pmo_data import generate_milestones, insert_milestones
    pmo_ms = generate_milestones()
    insert_milestones(cursor, pmo_ms)

    # --- 19. dim_pmo_phase (phase dimension table) ---
    cursor.execute("DROP TABLE IF EXISTS dim_pmo_phase")
    cursor.execute("""
        CREATE TABLE dim_pmo_phase (
            phase_id TEXT PRIMARY KEY,
            phase_name TEXT NOT NULL,
            phase_name_cn TEXT,
            start_month TEXT,
            end_month TEXT,
            phase_owner TEXT,
            milestone_count INTEGER,
            budget_allocated_wan REAL
        )
    """)
    from sunhing_pmo_data import generate_phases, insert_phases
    phases = generate_phases()
    insert_phases(cursor, phases)

    # --- 11. raw_crm (per-order level) ---
    cursor.execute("DROP TABLE IF EXISTS raw_crm")
    cursor.execute("""
        CREATE TABLE raw_crm (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER DEFAULT 1,
            order_id TEXT NOT NULL,
            customer_name TEXT,
            order_date TEXT,
            order_value_wan REAL,
            status TEXT,
            delivered_on_time INTEGER,
            client_complaint INTEGER,
            is_eco_partner_order INTEGER,
            eco_partner_delivery_on_time INTEGER,
            month TEXT
        )
    """)
    # Generate per-order CRM data
    from sunhing_crm_data import generate_orders, insert_orders
    crm_orders = generate_orders()
    insert_orders(cursor, crm_orders)

    # --- 12. raw_entity (per-entity level) ---
    cursor.execute("DROP TABLE IF EXISTS raw_entity")
    cursor.execute("""
        CREATE TABLE raw_entity (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER DEFAULT 1,
            entity_code TEXT NOT NULL,
            entity_name TEXT,
            entity_type TEXT,
            legal_type TEXT,
            business_focus TEXT,
            registration_month TEXT,
            registration_date TEXT,
            board_approved INTEGER,
            has_separate_accounting INTEGER,
            is_profitable INTEGER,
            total_setup_cost_wan REAL
        )
    """)
    from sunhing_entity_data import generate_entities, insert_entities
    entities = generate_entities()
    insert_entities(cursor, entities)

    # --- 13. raw_sentiment ---
    cursor.execute("DROP TABLE IF EXISTS raw_sentiment")
    cursor.execute("""
        CREATE TABLE raw_sentiment (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER DEFAULT 1,
            period TEXT NOT NULL,
            employee_satisfaction REAL,
            severance_satisfaction REAL,
            change_readiness_score REAL,
            negative_social_media INTEGER,
            positive_news_coverage INTEGER,
            competitor_poaching_intensity INTEGER,
            month_index INTEGER
        )
    """)
    for i, row in enumerate(data["raw_sources"]["sentiment_monitoring"]):
        cursor.execute(
            "INSERT INTO raw_sentiment (period, employee_satisfaction, severance_satisfaction, change_readiness_score, negative_social_media, positive_news_coverage, competitor_poaching_intensity, month_index) VALUES (?,?,?,?,?,?,?,?)",
            (row["month"], row["employee_satisfaction_score"],
             row["severance_satisfaction_score"], row["change_readiness_score"],
             row["negative_social_media_mentions"], row["positive_news_coverage"],
             row["competitor_poaching_intensity"], i)
        )

    # --- 14. raw_employee ---
    create_raw_employee_table(cursor)

    # --- 15. raw_liability ---
    create_raw_liability_table(cursor)

    conn.commit()
    conn.close()
    return db_path


if __name__ == "__main__":
    path = create_db()
    print(f"✅ DB created: {path}")

    # Print summary
    conn = sqlite3.connect(path)
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = cur.fetchall()
    for t in tables:
        cur.execute(f'SELECT COUNT(*) FROM "{t[0]}"')
        cnt = cur.fetchone()[0]
        cur.execute(f'PRAGMA table_info("{t[0]}")')
        cols = cur.fetchall()
        print(f"  TABLE {t[0]} ({cnt} rows, {len(cols)} cols)")
        for c in cols:
            print(f"    {c[1]} ({c[2]})")
    conn.close()
