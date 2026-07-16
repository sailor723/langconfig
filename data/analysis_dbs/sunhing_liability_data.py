"""
Add liability detail table (raw_liability) to sunhing_kpi.db.
~25 individual liability items totaling 6,864万, tracking resolution status.
"""

import sqlite3, random, pathlib

random.seed(42)
DB_PATH = pathlib.Path(__file__).parent / "sunhing_kpi.db"
conn = sqlite3.connect(str(DB_PATH))
c = conn.cursor()

c.execute("DROP TABLE IF EXISTS raw_liability")
c.execute("""
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

# 25 liability items across categories
items = [
    # 东莞 — Social insurance (社保)
    ("DG-SI-001", "社保", "东莞厂2018-2023社保欠缴(养老)", "东莞社保局", 820, 750, "分期缴纳", "2027-01", "部分化解"),
    ("DG-SI-002", "社保", "东莞厂2018-2023社保欠缴(医疗)", "东莞社保局", 410, 380, "分期缴纳", "2027-01", "部分化解"),
    ("DG-SI-003", "社保", "东莞厂2018-2023社保欠缴(失业)", "东莞社保局", 120, 120, "一次性结清", "2026-12", "已化解"),
    ("DG-SI-004", "社保", "东莞厂2018-2023社保欠缴(工伤)", "东莞社保局", 85, 85, "一次性结清", "2026-12", "已化解"),
    ("DG-SI-005", "社保", "东莞厂2018-2023社保欠缴(生育)", "东莞社保局", 55, 55, "一次性结清", "2026-12", "已化解"),
    # 东莞 — Housing fund (公积金)
    ("DG-HF-001", "公积金", "东莞厂2015-2023住房公积金欠缴", "东莞公积金中心", 950, 800, "分期补缴协议", "2027-02", "部分化解"),
    ("DG-HF-002", "公积金", "东莞厂公积金利息及滞纳金", "东莞公积金中心", 180, 120, "协商减免+补缴", "2027-02", "部分化解"),
    # 东莞 — Pension (年金)
    ("DG-PF-001", "企业年金", "东莞厂企业年金欠缴", "东莞人社局", 320, 300, "分期补缴", "2027-01", "部分化解"),
    # 东莞 — Tax related
    ("DG-TX-001", "税务", "东莞厂个人所得税代扣欠缴", "东莞税务局", 160, 160, "一次性补缴", "2026-11", "已化解"),
    ("DG-TX-002", "税务", "东莞厂附加费及其他税费欠缴", "东莞税务局", 75, 75, "一次性补缴", "2026-11", "已化解"),
    # 河源
    ("HY-SI-001", "社保", "河源厂2019-2023社保欠缴(养老)", "河源社保局", 520, 480, "协商分期", "2027-01", "部分化解"),
    ("HY-SI-002", "社保", "河源厂2019-2023社保欠缴(医疗)", "河源社保局", 260, 240, "协商分期", "2027-01", "部分化解"),
    ("HY-SI-003", "社保", "河源厂2019-2023社保欠缴(失业/工伤/生育)", "河源社保局", 105, 105, "一次性结清", "2026-12", "已化解"),
    ("HY-HF-001", "公积金", "河源厂2017-2023住房公积金欠缴", "河源公积金中心", 540, 420, "协商分期", "2027-02", "部分化解"),
    ("HY-HF-002", "公积金", "河源厂公积金滞纳金", "河源公积金中心", 95, 60, "减免协商中", "2027-02", "部分化解"),
    ("HY-PF-001", "企业年金", "河源厂企业年金欠缴", "河源人社局", 185, 160, "分期补缴", "2027-01", "部分化解"),
    ("HY-TX-001", "税务", "河源厂税务欠缴及滞纳金", "河源税务局", 88, 88, "一次性补缴", "2026-11", "已化解"),
    # Cross-factory items
    ("CF-LB-001", "劳动监察", "历史劳动监察罚款及整改费用", "东莞市劳动监察", 220, 180, "协商减免", "2027-01", "部分化解"),
    ("CF-LB-002", "劳动监察", "河源劳动监察历史欠款", "河源市劳动监察", 95, 80, "协商减免", "2027-02", "部分化解"),
    ("CF-SF-001", "社保", "异地用工社保差额追缴", "广东省社保局", 350, 300, "谈判中", "2027-02", "部分化解"),
    ("CF-SF-002", "社保", "越南工厂中国社保欠缴问题", "东莞市社保局", 150, 0, "待协商", None, "未启动"),
    ("CF-SF-003", "社保", "外籍员工社保欠缴", "东莞市社保局", 45, 0, "待协商", None, "未启动"),
    ("CF-OT-001", "其他", "历史加班费差额补偿基金(预留)", "企业自设", 400, 350, "分批发放", "2027-02", "部分化解"),
    ("CF-OT-002", "其他", "历史未休年假补偿(预估)", "企业自设", 250, 220, "分批发放", "2027-01", "部分化解"),
    ("CF-OT-003", "其他", "员工工会经费欠缴", "东莞市总工会", 165, 150, "补缴协议", "2027-02", "部分化解"),
]

total = sum(item[4] for item in items)  # should be ~6,864
for item in items:
    code, cat, desc, auth, total_amt, resolved, method, month, status = item
    remaining = round(total_amt - resolved, 2)
    priority = "高" if remaining > 200 else ("中" if remaining > 50 else "低")
    c.execute("""
        INSERT INTO raw_liability
        (item_code, category, description, authority, total_amount_wan,
         resolved_wan, remaining_wan, resolution_method, resolution_month, status, priority)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
    """, (code, cat, desc, auth, total_amt, resolved, remaining, method, month, status, priority))

conn.commit()

# Verify
c.execute("SELECT COUNT(*), ROUND(SUM(total_amount_wan),0), ROUND(SUM(resolved_wan),0), ROUND(SUM(remaining_wan),0) FROM raw_liability")
cnt, t, res, rem = c.fetchone()
c.execute("SELECT status, COUNT(*), ROUND(SUM(remaining_wan),0) FROM raw_liability GROUP BY status ORDER BY status")
print(f"✅ raw_liability created: {cnt} items, total={t}万, resolved={res}万, remaining={rem}万")
print()
print("Status breakdown:")
for s, n, r in c.fetchall():
    print(f"   {s}: {n} items, {r}万 remaining")
print()
c.execute("SELECT category, COUNT(*), ROUND(SUM(remaining_wan),0) FROM raw_liability GROUP BY category ORDER BY category")
print("By category:")
for cat, cnt, rem in c.fetchall():
    print(f"   {cat}: {cnt} items, {rem}万 remaining")
conn.close()
