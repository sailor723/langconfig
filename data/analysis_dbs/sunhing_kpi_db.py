"""
Convert 新溢眼镜 KPI mock data JSON → SQLite database in data/analysis_dbs/

Follows the same pattern as 8_erp_dataset.py but tailored to Sun Hing Vision Group's
"一分为多" transformation KPI system (ROE DuPont decomposition, 21 KPIs, 9 source systems).

Output: data/analysis_dbs/sunhing_kpi.db
"""

import json, sqlite3, pathlib

DB_DIR = pathlib.Path(__file__).parent
DB_PATH = DB_DIR / "sunhing_kpi.db"

# Load mock data
JSON_PATH = "/Users/weiping/dev/Learn/langchain-ai/deepagents-quickstarts/reports/eyewear_industry/新溢眼镜/client_input/mock_kpi_data_v2.0.json"
with open(JSON_PATH, encoding="utf-8") as f:
    data = json.load(f)

months = ["2026-09", "2026-10", "2026-11", "2026-12", "2027-01", "2027-02"]
month_labels = ["Sep", "Oct", "Nov", "Dec", "Jan", "Feb"]


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

    # --- 10. raw_pmo ---
    cursor.execute("DROP TABLE IF EXISTS raw_pmo")
    cursor.execute("""
        CREATE TABLE raw_pmo (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER DEFAULT 1,
            period TEXT NOT NULL,
            planned_milestones INTEGER,
            completed_milestones INTEGER,
            completion_rate_pct REAL,
            cumulative_milestones INTEGER,
            total_planned_all_phases INTEGER,
            pmo_risk_score INTEGER,
            month_index INTEGER
        )
    """)
    for i, row in enumerate(data["raw_sources"]["pmo_system"]):
        cursor.execute(
            "INSERT INTO raw_pmo (period, planned_milestones, completed_milestones, completion_rate_pct, cumulative_milestones, total_planned_all_phases, pmo_risk_score, month_index) VALUES (?,?,?,?,?,?,?,?)",
            (row["month"], row["planned_milestones"], row["completed_milestones"],
             row["completion_rate_pct"], row["cumulative_milestones"], row["total_planned_all_phases"],
             row["pmo_risk_score"], i)
        )

    # --- 11. raw_crm ---
    cursor.execute("DROP TABLE IF EXISTS raw_crm")
    cursor.execute("""
        CREATE TABLE raw_crm (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER DEFAULT 1,
            period TEXT NOT NULL,
            total_order_value_wan REAL,
            lost_order_value_wan REAL,
            order_loss_rate_pct REAL,
            client_complaints_received INTEGER,
            on_time_delivery_pct REAL,
            eco_partner_punctuality_pct REAL,
            eco_partner_data_upload_pct REAL,
            month_index INTEGER
        )
    """)
    for i, row in enumerate(data["raw_sources"]["crm_system"]):
        cursor.execute(
            "INSERT INTO raw_crm (period, total_order_value_wan, lost_order_value_wan, order_loss_rate_pct, client_complaints_received, on_time_delivery_pct, eco_partner_punctuality_pct, eco_partner_data_upload_pct, month_index) VALUES (?,?,?,?,?,?,?,?,?)",
            (row["month"], row["total_order_value_wan"], row["lost_order_value_wan"],
             row["order_loss_rate_pct"], row["client_complaints_received"], row["on_time_delivery_pct"],
             row["eco_partner_order_punctuality_pct"], row["eco_partner_data_upload_timeliness_pct"], i)
        )

    # --- 12. raw_entity_registration ---
    cursor.execute("DROP TABLE IF EXISTS raw_entity")
    cursor.execute("""
        CREATE TABLE raw_entity (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER DEFAULT 1,
            period TEXT NOT NULL,
            planned_new_entities INTEGER,
            entities_registered INTEGER,
            completion_pct REAL,
            entities_separate_accounting INTEGER,
            eco_entities_profitable INTEGER,
            month_index INTEGER
        )
    """)
    for i, row in enumerate(data["raw_sources"]["entity_registration"]):
        cursor.execute(
            "INSERT INTO raw_entity (period, planned_new_entities, entities_registered, completion_pct, entities_separate_accounting, eco_entities_profitable, month_index) VALUES (?,?,?,?,?,?,?)",
            (row["month"], row["planned_new_entities"], row["entities_registered_cumulative"],
             row["completion_pct"], row["entities_with_separate_accounting"],
             row["eco_entities_with_profit_gt_15pct"], i)
        )

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
