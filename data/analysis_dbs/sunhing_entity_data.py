"""
Generate per-entity registration data for Sun Hing Vision Group.

Replaces the old monthly-summary raw_entity with individual entity records.
12 entities registered as part of the 一分为多 restructuring.

Output: inserts into sunhing_kpi.db raw_entity table
"""

import sqlite3, pathlib, random

DB_DIR = pathlib.Path(__file__).parent
DB_PATH = DB_DIR / "sunhing_kpi.db"

# 12 entities in the 一分为多 restructuring
ENTITIES = [
    # (entity_name, entity_type, registration_month, legal_type, business_focus)
    ("泰阳花制造",       "core",     "2026-09", "有限责任公司", "核心制造基地"),
    ("光龙光学",         "partner",  "2026-10", "合伙企业",     "镜片加工"),
    ("光龙模具",         "partner",  "2026-10", "合伙企业",     "模具制造"),
    ("光龙电镀",         "partner",  "2026-11", "合伙企业",     "表面处理"),
    ("倍崇德品牌",       "core",     "2026-11", "有限责任公司", "品牌运营"),
    ("光龙装配",         "partner",  "2026-12", "合伙企业",     "成品装配"),
    ("光龙质检",         "partner",  "2026-12", "合伙企业",     "品质检测"),
    ("一零一品牌管理",   "core",     "2026-12", "有限责任公司", "品牌孵化"),
    ("春阳花精密制造",   "core",     "2027-01", "有限责任公司", "精密制造"),
    ("光龙物流",         "partner",  "2027-01", "合伙企业",     "供应链物流"),
    ("光龙技术服务",     "partner",  "2027-02", "合伙企业",     "技术咨询"),
    ("新溢越南",         "partner",  "2027-02", "有限责任公司", "越南生产基地"),
]

# Registration dates within each month
REG_DATES = {
    "2026-09": ["2026-09-15"],
    "2026-10": ["2026-10-08", "2026-10-22"],
    "2026-11": ["2026-11-05", "2026-11-19"],
    "2026-12": ["2026-12-03", "2026-12-10", "2026-12-18"],
    "2027-01": ["2027-01-08", "2027-01-20"],
    "2027-02": ["2027-02-05", "2027-02-18"],
}

random.seed(123)
date_idx = {m: 0 for m in REG_DATES}

def registration_date(month):
    dates = REG_DATES[month]
    idx = date_idx[month]
    date_idx[month] += 1
    return dates[idx % len(dates)]

def generate_entities():
    entities = []
    for i, (name, etype, reg_month, legal_type, focus) in enumerate(ENTITIES):
        reg_date = registration_date(reg_month)
        # Separate accounting starts 1-2 months after registration
        months_since_reg = 0
        for mi, m in enumerate(["2026-09","2026-10","2026-11","2026-12","2027-01","2027-02"]):
            if m <= reg_month:
                months_since_reg = len(["2026-09","2026-10","2026-11","2026-12","2027-01","2027-02"]) - mi - 1
        has_separate_accounting = 1 if months_since_reg >= 1 else 0
        # Profitability takes 2-3 months
        is_profitable = 1 if months_since_reg >= 3 else 0
        board_approved = 1 if months_since_reg >= 0 else 1

        entities.append({
            "entity_name": name,
            "entity_code": f"ENT-{i+1:03d}",
            "entity_type": etype,
            "legal_type": legal_type,
            "business_focus": focus,
            "registration_month": reg_month,
            "registration_date": reg_date,
            "board_approved": board_approved,
            "has_separate_accounting": has_separate_accounting,
            "is_profitable": is_profitable,
            "total_setup_cost_wan": random.randint(30, 150) if etype == "core" else random.randint(5, 30),
        })
    return entities


def recreate_entity_table(cursor):
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


def insert_entities(cursor, entities):
    for e in entities:
        cursor.execute("""
            INSERT INTO raw_entity (company_id, entity_code, entity_name, entity_type,
                legal_type, business_focus, registration_month, registration_date,
                board_approved, has_separate_accounting, is_profitable, total_setup_cost_wan)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            1, e["entity_code"], e["entity_name"], e["entity_type"],
            e["legal_type"], e["business_focus"], e["registration_month"],
            e["registration_date"], e["board_approved"], e["has_separate_accounting"],
            e["is_profitable"], e["total_setup_cost_wan"],
        ))


if __name__ == "__main__":
    entities = generate_entities()
    print(f"Generated {len(entities)} individual entities:\n")

    print(f"{'Name':<20} {'Type':<10} {'Month':<10} {'Approved':<10} {'Accounting':<12} {'Profitable':<10}")
    print("-"*75)
    for e in entities:
        print(f"{e['entity_name']:<20} {e['entity_type']:<10} {e['registration_month']:<10} "
              f"{'✅' if e['board_approved'] else '❌':<10} "
              f"{'✅' if e['has_separate_accounting'] else '❌':<12} "
              f"{'✅' if e['is_profitable'] else '❌':<10}")

    # Counts
    by_month = {}
    for e in entities:
        m = e["registration_month"]
        by_month.setdefault(m, {"total": 0, "acc": 0})
        by_month[m]["total"] += 1

    cumulative = 0
    print("\n--- Monthly Registration Progress ---")
    for m in ["2026-09","2026-10","2026-11","2026-12","2027-01","2027-02"]:
        if m in by_month:
            cumulative += by_month[m]["total"]
            print(f"  {m}: {by_month[m]['total']} entities (cumulative: {cumulative}/12 = {cumulative/12*100:.0f}%)")

    # Write to DB
    conn = sqlite3.connect(str(DB_PATH))
    cursor = conn.cursor()
    recreate_entity_table(cursor)
    insert_entities(cursor, entities)
    conn.commit()

    count = cursor.execute("SELECT COUNT(*) FROM raw_entity").fetchone()[0]
    print(f"\nWritten to {DB_PATH}: {count} rows in raw_entity ✅")
    conn.close()
