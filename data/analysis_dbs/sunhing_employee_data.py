"""
Regenerate employee table with Chinese names and skill levels.
Drops and recreates raw_employee with new columns: name_cn, skill_level.
"""

import sqlite3, random, pathlib

random.seed(42)

DB_PATH = pathlib.Path(__file__).parent / "sunhing_kpi.db"
conn = sqlite3.connect(str(DB_PATH))
cursor = conn.cursor()

# ── Chinese name components ────────────────────────────────────────────
surnames = ["陈", "李", "张", "王", "刘", "杨", "黄", "周", "吴", "徐",
            "孙", "胡", "朱", "林", "何", "郭", "罗", "梁", "谢", "宋",
            "邓", "许", "彭", "曾", "肖", "谭", "唐", "曹", "冯", "蔡",
            "韩", "魏", "叶", "潘", "戴", "钟", "汪", "范", "石", "姚",
            "廖", "邹", "熊", "金", "夏", "卢", "蒋", "余", "杜", "苏"]

given_names = ["伟强", "志明", "建华", "国荣", "文杰", "海涛", "晓东", "嘉诚",
               "耀明", "永康", "志辉", "德民", "建军", "国平", "伟民", "文彬",
               "志强", "海波", "晓峰", "嘉俊", "耀华", "振华", "建国", "国强",
               "卫东", "文斌", "志刚", "海生", "晓明", "嘉文", "德强", "永华",
               "俊杰", "伟杰", "志鸿", "建国", "文华", "海龙", "天佑", "家豪",
               "秀英", "美玲", "秀珍", "丽华", "秀兰", "桂英", "秀芳", "玉珍",
               "玉梅", "桂芳", "秀英", "玉兰", "秀华", "美芳", "秀英", "美华",
               "小红", "秀娟", "秀英", "玉萍", "秀英", "美英", "秀珍", "玉芳"]

skill_levels = ["初级工", "中级工", "高级工", "技师", "高级技师"]

# Weighted by position
skill_by_pos = {
    "Operator":       ["初级工", "初级工", "中级工", "中级工", "高级工"],
    "Senior Operator":["中级工", "高级工", "高级工", "技师", "技师"],
    "Tech Lead":      ["高级工", "技师", "技师", "高级技师", "高级技师"],
    "Inspector":      ["中级工", "高级工", "技师", "高级技师"],
    "Team Lead":      ["技师", "高级技师", "高级技师"],
}

departments_dg = ["成型", "打磨", "抛光", "组装", "质检", "喷涂", "电镀", "包装"]
departments_hy = ["注塑", "模具", "精加工", "装配", "质检", "物流"]

severance_by_month = [
    ("2026-09", 0),
    ("2026-10", 120),
    ("2026-11", 220),
    ("2026-12", 220),
    ("2027-01", 160),
    ("2027-02", 90),
]

# ── Drop & recreate table ──────────────────────────────────────────────
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

# ── Generate 856 employees ─────────────────────────────────────────────
shuffled_surnames = surnames * (856 // len(surnames) + 1)
shuffled_given = given_names * (856 // len(given_names) + 1)
random.shuffle(shuffled_surnames)
random.shuffle(shuffled_given)

severed_count = 0
employee_id = 0

for factory, count, depts in [("东莞", 650, departments_dg), ("河源", 206, departments_hy)]:
    for i in range(count):
        employee_id += 1
        emp_code = f"EMP-{factory[:1]}{employee_id:04d}"
        name_cn = shuffled_surnames[employee_id % len(shuffled_surnames)] + shuffled_given[employee_id % len(shuffled_given)]
        dept = random.choice(depts)
        pos = random.choice(list(skill_by_pos.keys()))
        skill = random.choice(skill_by_pos[pos])
        tenure = random.randint(1, 35)

        is_severed = severed_count < 810
        sev_month = None
        compensation = 0
        has_dispute = 0
        satisfaction = None
        converted = 0

        if is_severed:
            target_count = severed_count + 1
            cum = 0
            for s_month, s_count in severance_by_month:
                cum += s_count
                if target_count <= cum:
                    sev_month = s_month
                    break
            compensation = round(random.uniform(2.5, 6.5) * (1 + tenure / 50), 2)
            compensation = min(compensation, 12.0)
            has_dispute = 1 if random.random() < 0.02 else 0
            satisfaction = round(random.uniform(5, 9.5) - (0.5 if has_dispute else 0) + random.uniform(-0.5, 0.5), 1)
            satisfaction = max(1, min(10, satisfaction))
            converted = 1 if random.random() < 0.4 else 0
            severed_count += 1

        cursor.execute("""
            INSERT INTO raw_employee
            (employee_code, name_cn, department, factory, position_category,
             skill_level, tenure_years, is_severed, severance_month,
             compensation_wan, has_dispute, satisfaction_score, converted_to_partner)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (emp_code, name_cn, dept, factory, pos, skill, tenure,
              1 if is_severed else 0, sev_month,
              compensation, has_dispute, satisfaction, converted))

conn.commit()
conn.close()

# ── Verify ─────────────────────────────────────────────────────────────
conn = sqlite3.connect(str(DB_PATH))
cur = conn.cursor()
cur.execute("SELECT COUNT(*) FROM raw_employee")
total = cur.fetchone()[0]
cur.execute("SELECT COUNT(*) FROM raw_employee WHERE is_severed=1")
severed = cur.fetchone()[0]

# Show some 资深 (senior) employees
cur.execute("SELECT employee_code, name_cn, factory, department, skill_level, tenure_years FROM raw_employee WHERE skill_level IN ('技师','高级技师') LIMIT 10")
print(f"✅ Employee table regenerated: {total} employees ({severed} severed)")
print(f"   New columns: name_cn, skill_level")
print(f"   Skill levels: {dict(cur.connection.execute('SELECT skill_level, COUNT(*) FROM raw_employee GROUP BY skill_level ORDER BY COUNT(*) DESC').fetchall())}")
print()

print("Sample 高级技师 (Senior Master) employees:")
for row in cur.fetchall():
    print(f"   {row[0]} | {row[1]:6s} | {row[2]} | {row[3]:4s} | {row[4]:8s} | {row[5]}yr")
conn.close()
