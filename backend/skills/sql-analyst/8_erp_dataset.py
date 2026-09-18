#!/usr/bin/env python3
"""
Step 8: ERP Mock Dataset — Single company, 5-6 tables, multi-year data.

This creates a realistic ERP dataset for a single mid-sized company
("AcmeCloud Inc.") with 3 years of quarterly data (Q1 2023 - Q4 2025).

Tables:
  1. companies           — 1 company
  2. income_statement    — quarterly P&L (12 rows)
  3. balance_sheet       — quarterly snapshot of assets/liabilities/equity (12 rows)
  4. cash_flow           — quarterly operating/investing/financing flows (12 rows)
  5. products            — 12 products with cost/price/margin
  6. customers           — 20 customers with tier/region/credit

Run: cd backend && uv run python skills/sql-analyst/8_erp_dataset.py

================================================================================
BUSINESS METRICS (computed from above tables)
================================================================================

── Profitability Metrics ──
EBITDA = Revenue - COGS - Operating Expenses (excludes D&A, interest, tax)
        → IS: revenue - cogs - operating_expenses
        → Measures core operating profitability

EBITDA Margin = EBITDA / Revenue × 100%
        → Industry avg SaaS: 25-35%, Hardware: 12-20%

Gross Profit = Revenue - COGS
Gross Margin = Gross Profit / Revenue × 100%
        → SaaS: 70-85%, Hardware: 30-50%, Retail: 20-40%

Operating Income (EBIT) = EBITDA - Depreciation - Amortization
Operating Margin = Operating Income / Revenue × 100%

Net Income = Operating Income - Interest Expense - Tax
Net Profit Margin = Net Income / Revenue × 100%

── Return Metrics ──
ROE (Return on Equity) = Net Income / Average Shareholders' Equity × 100%
        → Industry benchmark: 15%+ = good, 20%+ = excellent
        → Use AVERAGE equity = (beg + end) / 2

ROA (Return on Assets) = Net Income / Average Total Assets × 100%
        → Industry benchmark: 5-10%

ROIC (Return on Invested Capital) = NOPAT / (Equity + Debt) × 100%
        → NOPAT = Operating Income × (1 - tax_rate)
        → Industry benchmark: 10%+ = good

── Liquidity & Working Capital ──
Current Ratio = Current Assets / Current Liabilities
        → Healthy: 1.5-3.0; <1.0 = liquidity risk

Quick Ratio = (Current Assets - Inventory) / Current Liabilities
        → Stricter liquidity test

Working Capital = Current Assets - Current Liabilities

Cash Conversion Cycle = DIO + DSO - DPO
        → DIO = (Inventory / COGS) × 365 days
        → DSO = (AR / Revenue) × 365 days
        → DPO = (AP / COGS) × 365 days
        → Lower = more efficient

── Leverage & Solvency ──
Debt-to-Equity = Total Liabilities / Shareholders' Equity
        → Healthy: <2.0; >3.0 = high risk

Debt Ratio = Total Liabilities / Total Assets
        → Healthy: <0.6; >0.7 = high risk

Interest Coverage = Operating Income / Interest Expense
        → Healthy: >3.0; <1.5 = risk of default

── Efficiency Metrics ──
Asset Turnover = Revenue / Average Total Assets
        → Measures how efficiently assets generate revenue

Inventory Turnover = COGS / Average Inventory
        → Higher = more efficient

── Per-Share & Valuation ──
EPS = Net Income / Shares Outstanding
        → BS: shares_outstanding

Book Value per Share = Shareholders' Equity / Shares Outstanding

================================================================================
"""
import sqlite3
import pathlib

DB_PATH = pathlib.Path(__file__).parent / "erp_data.db"

# --- Company info ---
COMPANY = {
    "id": 1,
    "name": "AcmeCloud Inc.",
    "industry": "Cloud Infrastructure",
    "founded": "2018-01-15",
    "currency": "USD",
    "tax_rate": 0.21,  # 21% US federal corporate rate
    "shares_outstanding": 10_000_000,
}

# --- Quarterly financial data (Q1 2023 - Q4 2025) ---
# 12 quarters. Each quarter: revenue, cogs, opex, da (D&A), interest, tax, etc.
QUARTERS = [
    # 2023
    ("2023-Q1", 8_500_000, 3_400_000, 4_200_000, 320_000, 95_000),
    ("2023-Q2", 9_200_000, 3_680_000, 4_400_000, 340_000, 90_000),
    ("2023-Q3", 10_100_000, 4_040_000, 4_700_000, 360_000, 100_000),
    ("2023-Q4", 11_400_000, 4_560_000, 5_100_000, 380_000, 105_000),
    # 2024
    ("2024-Q1", 12_300_000, 4_920_000, 5_300_000, 400_000, 110_000),
    ("2024-Q2", 13_500_000, 5_400_000, 5_600_000, 420_000, 115_000),
    ("2024-Q3", 14_800_000, 5_920_000, 5_900_000, 440_000, 120_000),
    ("2024-Q4", 16_500_000, 6_600_000, 6_300_000, 460_000, 125_000),
    # 2025
    ("2025-Q1", 18_200_000, 7_280_000, 6_800_000, 480_000, 130_000),
    ("2025-Q2", 20_000_000, 8_000_000, 7_200_000, 500_000, 135_000),
    ("2025-Q3", 21_800_000, 8_720_000, 7_600_000, 520_000, 140_000),
    ("2025-Q4", 24_000_000, 9_600_000, 8_100_000, 540_000, 150_000),
]
# Tuple format: (period, revenue, cogs, opex, depreciation_amortization, interest_expense)

# --- Balance sheet snapshots (cumulative position at quarter end) ---
# cash, ar, inventory, ppe, total_assets,
# ap, short_term_debt, long_term_debt, total_liabilities, retained_earnings, equity
BALANCE_SHEET = [
    # 2023
    ("2023-Q1", 2_100_000,  2_800_000,  450_000,  5_800_000, 11_200_000,  1_500_000, 800_000,  2_000_000,  4_400_000,  900_000,  6_800_000),
    ("2023-Q2", 2_400_000,  3_200_000,  520_000,  6_100_000, 12_300_000,  1_700_000, 850_000,  2_100_000,  4_750_000, 1_200_000,  7_550_000),
    ("2023-Q3", 2_900_000,  3_500_000,  600_000,  6_400_000, 13_500_000,  1_900_000, 900_000,  2_200_000,  5_100_000, 1_550_000,  8_400_000),
    ("2023-Q4", 3_600_000,  3_900_000,  720_000,  6_700_000, 15_000_000,  2_200_000, 950_000,  2_300_000,  5_550_000, 2_000_000,  9_450_000),
    # 2024
    ("2024-Q1", 4_200_000,  4_400_000,  820_000,  7_000_000, 16_500_000,  2_500_000, 1_000_000, 2_400_000,  6_000_000, 2_500_000,  10_500_000),
    ("2024-Q2", 4_900_000,  4_800_000,  920_000,  7_300_000, 18_000_000,  2_700_000, 1_050_000, 2_500_000,  6_350_000, 3_100_000, 11_650_000),
    ("2024-Q3", 5_700_000,  5_300_000, 1_050_000, 7_600_000, 19_800_000,  2_900_000, 1_100_000, 2_600_000,  6_700_000, 3_800_000, 13_100_000),
    ("2024-Q4", 6_800_000,  5_800_000, 1_200_000, 7_900_000, 21_800_000,  3_200_000, 1_150_000, 2_700_000,  7_150_000, 4_650_000, 14_650_000),
    # 2025
    ("2025-Q1", 7_900_000,  6_400_000, 1_350_000, 8_200_000, 24_000_000,  3_500_000, 1_200_000, 2_800_000,  7_600_000, 5_600_000, 16_400_000),
    ("2025-Q2", 9_200_000,  7_000_000, 1_500_000, 8_500_000, 26_400_000,  3_800_000, 1_250_000, 2_900_000,  8_050_000, 6_700_000, 18_350_000),
    ("2025-Q3", 10_700_000, 7_700_000, 1_650_000, 8_800_000, 28_900_000,  4_100_000, 1_300_000, 3_000_000,  8_500_000, 7_900_000, 20_400_000),
    ("2025-Q4", 12_500_000, 8_400_000, 1_800_000, 9_100_000, 31_800_000,  4_400_000, 1_350_000, 3_100_000,  8_950_000, 9_300_000, 22_850_000),
]

# --- Cash flow (quarterly) ---
# operating_cf, investing_cf (capex), financing_cf (debt + dividends)
CASH_FLOW = [
    # 2023
    ("2023-Q1",  1_200_000, -800_000,  -200_000),
    ("2023-Q2",  1_400_000, -900_000,  -200_000),
    ("2023-Q3",  1_600_000, -1_000_000, -200_000),
    ("2023-Q4",  1_900_000, -1_100_000, -200_000),
    # 2024
    ("2024-Q1",  2_200_000, -1_200_000, -200_000),
    ("2024-Q2",  2_500_000, -1_300_000, -200_000),
    ("2024-Q3",  2_800_000, -1_400_000, -200_000),
    ("2024-Q4",  3_200_000, -1_500_000, -200_000),
    # 2025
    ("2025-Q1",  3_600_000, -1_600_000, -200_000),
    ("2025-Q2",  4_000_000, -1_700_000, -200_000),
    ("2025-Q3",  4_400_000, -1_800_000, -200_000),
    ("2025-Q4",  4_900_000, -1_900_000, -200_000),
]

# --- Products (12 SKUs) ---
PRODUCTS = [
    # (id, name, category, unit_price, unit_cost, units_sold_ytd)
    (1,  "Cloud VM S",        "IaaS",         49.00,  12.00,  45_000),
    (2,  "Cloud VM M",        "IaaS",         149.00, 35.00,  28_000),
    (3,  "Cloud VM L",        "IaaS",         399.00, 90.00,  14_000),
    (4,  "Cloud VM XL",       "IaaS",         899.00, 200.00,  6_500),
    (5,  "Object Storage",    "Storage",      0.02,   0.005,  120_000_000),
    (6,  "Block Storage",     "Storage",      0.10,   0.025,  35_000_000),
    (7,  "CDN Bandwidth",     "Networking",   0.08,   0.020,  90_000_000),
    (8,  "Load Balancer",     "Networking",   29.00,  8.00,   18_000),
    (9,  "Managed Postgres",  "PaaS",         199.00, 60.00,  9_500),
    (10, "Managed Redis",     "PaaS",         99.00,  30.00,  16_000),
    (11, "Kubernetes Engine", "PaaS",         299.00, 95.00,  8_200),
    (12, "AI Inference API",  "AI Services",  0.001,  0.0003, 50_000_000),
]

# --- Customers (20 B2B accounts) ---
CUSTOMERS = [
    # (id, name, tier, region, country, arr, credit_limit, signup_date)
    (1,  "DataCorp Global",       "enterprise", "NA",    "USA",         4_800_000, 500_000, "2018-03-15"),
    (2,  "FinTech Solutions",     "enterprise", "EU",    "UK",          3_200_000, 350_000, "2018-08-22"),
    (3,  "MedTech Innovations",   "enterprise", "NA",    "Canada",      2_900_000, 300_000, "2019-01-10"),
    (4,  "EduPlatform Inc.",      "mid-market", "NA",    "USA",         1_200_000, 150_000, "2019-06-30"),
    (5,  "RetailNext",            "mid-market", "NA",    "USA",         950_000,   120_000, "2020-02-14"),
    (6,  "LogiFlow Systems",      "mid-market", "EU",    "Germany",     1_100_000, 130_000, "2020-04-18"),
    (7,  "TravelTech Asia",       "mid-market", "APAC",  "Singapore",   880_000,   100_000, "2020-07-09"),
    (8,  "MediaStream Co.",       "mid-market", "NA",    "USA",         1_400_000, 160_000, "2020-09-25"),
    (9,  "AgriTech Brasil",       "smb",        "LATAM", "Brazil",      180_000,   25_000,  "2021-01-12"),
    (10, "DesignStudio Pro",      "smb",        "EU",    "France",      240_000,   30_000,  "2021-03-20"),
    (11, "HealthBook Network",    "smb",        "NA",    "USA",         320_000,   40_000,  "2021-05-08"),
    (12, "GamingVerse",           "smb",        "APAC",  "Japan",       410_000,   50_000,  "2021-08-14"),
    (13, "AutoDrive Labs",        "mid-market", "NA",    "USA",         780_000,   90_000,  "2021-11-22"),
    (14, "SmartCity Solutions",   "enterprise", "EU",    "Netherlands", 2_300_000, 250_000, "2022-02-03"),
    (15, "BioGen Research",       "enterprise", "NA",    "USA",         2_600_000, 280_000, "2022-05-19"),
    (16, "CloudKitch",            "smb",        "EU",    "Spain",       150_000,   20_000,  "2022-08-07"),
    (17, "RealEstate Hub",        "smb",        "NA",    "USA",         280_000,   35_000,  "2022-11-11"),
    (18, "InsurTech Plus",        "mid-market", "EU",    "Italy",       640_000,   75_000,  "2023-02-25"),
    (19, "CryptoLedger",          "smb",        "APAC",  "Korea",       195_000,   25_000,  "2023-06-30"),
    (20, "WeddingPlanner Co.",    "smb",        "NA",    "USA",         85_000,    15_000,  "2023-10-15"),
]


def create_erp_db(db_path: str = str(DB_PATH)):
    """Create the ERP database with all 6 tables."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # --- 1. companies ---
    cursor.execute("DROP TABLE IF EXISTS companies")
    cursor.execute("""
        CREATE TABLE companies (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            industry TEXT,
            founded TEXT,
            currency TEXT DEFAULT 'USD',
            tax_rate REAL DEFAULT 0.21,
            shares_outstanding INTEGER,
            fiscal_year_start TEXT DEFAULT '01-01'
        )
    """)
    cursor.execute(
        "INSERT INTO companies VALUES (?,?,?,?,?,?,?,?)",
        (
            COMPANY["id"],
            COMPANY["name"],
            COMPANY["industry"],
            COMPANY["founded"],
            COMPANY["currency"],
            COMPANY["tax_rate"],
            COMPANY["shares_outstanding"],
            "01-01",
        ),
    )

    # --- 2. income_statement ---
    cursor.execute("DROP TABLE IF EXISTS income_statement")
    cursor.execute("""
        CREATE TABLE income_statement (
            id INTEGER PRIMARY KEY,
            company_id INTEGER,
            period TEXT NOT NULL,           -- e.g. '2024-Q1'
            revenue REAL,
            cogs REAL,                      -- Cost of Goods Sold
            operating_expenses REAL,        -- SG&A, R&D, sales, marketing
            depreciation_amortization REAL, -- D&A
            interest_expense REAL,
            FOREIGN KEY (company_id) REFERENCES companies(id)
        )
    """)
    for i, (period, rev, cogs, opex, da, interest) in enumerate(QUARTERS, 1):
        cursor.execute(
            "INSERT INTO income_statement VALUES (?,?,?,?,?,?,?,?)",
            (i, 1, period, rev, cogs, opex, da, interest),
        )

    # --- 3. balance_sheet ---
    cursor.execute("DROP TABLE IF EXISTS balance_sheet")
    cursor.execute("""
        CREATE TABLE balance_sheet (
            id INTEGER PRIMARY KEY,
            company_id INTEGER,
            period TEXT NOT NULL,
            cash REAL,
            accounts_receivable REAL,
            inventory REAL,
            property_plant_equipment REAL,
            total_assets REAL,
            accounts_payable REAL,
            short_term_debt REAL,
            long_term_debt REAL,
            total_liabilities REAL,
            retained_earnings REAL,
            shareholders_equity REAL,
            FOREIGN KEY (company_id) REFERENCES companies(id)
        )
    """)
    for i, row in enumerate(BALANCE_SHEET, 1):
        cursor.execute(
            "INSERT INTO balance_sheet VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (i, 1, *row),
        )

    # --- 4. cash_flow ---
    cursor.execute("DROP TABLE IF EXISTS cash_flow")
    cursor.execute("""
        CREATE TABLE cash_flow (
            id INTEGER PRIMARY KEY,
            company_id INTEGER,
            period TEXT NOT NULL,
            operating_cash_flow REAL,
            investing_cash_flow REAL,  -- capex typically negative
            financing_cash_flow REAL,  -- debt repayment + dividends
            FOREIGN KEY (company_id) REFERENCES companies(id)
        )
    """)
    for i, (period, ocf, icf, fcf) in enumerate(CASH_FLOW, 1):
        cursor.execute(
            "INSERT INTO cash_flow VALUES (?,?,?,?,?,?)",
            (i, 1, period, ocf, icf, fcf),
        )

    # --- 5. products ---
    cursor.execute("DROP TABLE IF EXISTS products")
    cursor.execute("""
        CREATE TABLE products (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            category TEXT,
            unit_price REAL,
            unit_cost REAL,
            units_sold_ytd INTEGER
        )
    """)
    for p in PRODUCTS:
        cursor.execute("INSERT INTO products VALUES (?,?,?,?,?,?)", p)

    # --- 6. customers ---
    cursor.execute("DROP TABLE IF EXISTS customers")
    cursor.execute("""
        CREATE TABLE customers (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            tier TEXT,                      -- enterprise / mid-market / smb
            region TEXT,                    -- NA / EU / APAC / LATAM
            country TEXT,
            arr REAL,                       -- Annual Recurring Revenue
            credit_limit REAL,
            signup_date TEXT
        )
    """)
    for c in CUSTOMERS:
        cursor.execute("INSERT INTO customers VALUES (?,?,?,?,?,?,?,?)", c)

    conn.commit()
    conn.close()
    return db_path


if __name__ == "__main__":
    path = create_erp_db()
    print(f"✅ ERP database created: {path}")
    print(f"   Company: {COMPANY['name']} ({COMPANY['industry']})")
    print(f"   Period: 2023-Q1 → 2025-Q4 (12 quarters)")
    print(f"   Tables: companies, income_statement, balance_sheet, "
          f"cash_flow, products ({len(PRODUCTS)}), customers ({len(CUSTOMERS)})")

    # Show schema
    conn = sqlite3.connect(path)
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
    tables = cursor.fetchall()
    for t in tables:
        cursor.execute(f"SELECT COUNT(*) FROM {t[0]}")
        count = cursor.fetchone()[0]
        cursor.execute(f"PRAGMA table_info({t[0]})")
        cols = cursor.fetchall()
        print(f"\n  📋 {t[0]} ({count} rows, {len(cols)} cols)")
        for c in cols:
            print(f"     {c[1]} ({c[2]})")
    conn.close()
