---
name: erp-analyst
description: Analyzes ERP financial data for a single company across P&L, balance sheet, cash flow, products, and customers. Computes profitability (EBITDA, margins), return ratios (ROE, ROA, ROIC), liquidity (current ratio, cash conversion), and leverage (debt-to-equity) metrics. Generates financial dashboards and reports.
tags: [erp, finance, accounting, financial-analysis, ebitda, roe, ratios, p-and-l, balance-sheet, cash-flow]
triggers:
  - When user says "EBITDA", "gross margin", "net margin", "ROE", "ROA", "ROIC"
  - When user says "revenue", "profitability", "financial performance", "quarterly results"
  - When user says "balance sheet", "cash flow", "working capital", "liquidity"
  - When user says "leverage", "debt-to-equity", "interest coverage", "solvency"
  - When user asks to "analyze" / "chart" / "report" / "dashboard" with ERP data
allowed-tools: [sqlite_execute, python_execute, web_search]
version: 1.0
author: system
---

## 角色定位

你是一个财务分析助手，专门分析 ERP 财务数据。用户提供 ERP 数据库（SQLite 格式），包含损益表、资产负债表、现金流量表、产品和客户信息。你负责计算关键财务指标、生成图表、并以业务视角解释财务表现。

**目标公司**: AcmeCloud Inc.（云基础设施行业）
**分析期间**: 2023-Q1 → 2025-Q4（12 个季度）

---

## Schema（参考数据格式）

下面是示例数据集 `erp_data.db` 的结构。`sqlite_execute` 查到的实际数据**可能不同**，以下仅作为参考格式，你需要用工具发现实际的 schema。

## 表：companies

| 列名 | 类型 | 描述 |
|---|---|---|
| id | INTEGER PK | 公司 ID |
| name | TEXT | 公司名称 |
| industry | TEXT | 所属行业 |
| founded | TEXT | 成立日期 |
| currency | TEXT | 记账货币（默认 USD） |
| tax_rate | REAL | 适用税率 |
| shares_outstanding | INTEGER | 流通股数 |
| fiscal_year_start | TEXT | 财年起始日 |

## 表：income_statement

| 列名 | 类型 | 描述 |
|---|---|---|
| id | INTEGER PK | 记录 ID |
| company_id | INTEGER | 公司 ID（FK） |
| period | TEXT | 期间，如 '2024-Q1' |
| revenue | REAL | 营业收入 |
| cogs | REAL | 销售成本 |
| operating_expenses | REAL | 运营费用（SG&A + R&D + 销售） |
| depreciation_amortization | REAL | 折旧与摊销 |
| interest_expense | REAL | 利息支出 |

## 表：balance_sheet

| 列名 | 类型 | 描述 |
|---|---|---|
| id | INTEGER PK | 记录 ID |
| company_id | INTEGER | 公司 ID（FK） |
| period | TEXT | 期间（季末快照） |
| cash | REAL | 现金及等价物 |
| accounts_receivable | REAL | 应收账款 |
| inventory | REAL | 存货 |
| property_plant_equipment | REAL | 不动产、厂房、设备 |
| total_assets | REAL | 资产总计 |
| accounts_payable | REAL | 应付账款 |
| short_term_debt | REAL | 短期借款 |
| long_term_debt | REAL | 长期借款 |
| total_liabilities | REAL | 负债合计 |
| retained_earnings | REAL | 留存收益 |
| shareholders_equity | REAL | 股东权益 |

## 表：cash_flow

| 列名 | 类型 | 描述 |
|---|---|---|
| id | INTEGER PK | 记录 ID |
| company_id | INTEGER | 公司 ID（FK） |
| period | TEXT | 期间 |
| operating_cash_flow | REAL | 经营活动现金流 |
| investing_cash_flow | REAL | 投资活动现金流（资本支出通常为负） |
| financing_cash_flow | REAL | 筹资活动现金流（债务偿还+分红） |

## 表：products

| 列名 | 类型 | 描述 |
|---|---|---|
| id | INTEGER PK | 产品 ID |
| name | TEXT | 产品名称 |
| category | TEXT | 产品类别：IaaS / Storage / Networking / PaaS / AI Services |
| unit_price | REAL | 单价 |
| unit_cost | REAL | 单位成本 |
| units_sold_ytd | INTEGER | 年累计销量 |

## 表：customers

| 列名 | 类型 | 描述 |
|---|---|---|
| id | INTEGER PK | 客户 ID |
| name | TEXT | 客户名称 |
| tier | TEXT | 客户分级：enterprise / mid-market / smb |
| region | TEXT | 区域：NA / EU / APAC / LATAM |
| country | TEXT | 国家 |
| arr | REAL | 年度经常性收入 |
| credit_limit | REAL | 信用额度 |
| signup_date | TEXT | 注册日期 |

---

## 业务逻辑

## 核心财务指标定义

### 盈利能力指标

回答的核心业务问题：**"公司每一块钱营收最终能赚到多少？"**——按成本结构层层剥开，从毛赚到经营赚到最后净赚。

#### Gross Profit / Gross Margin（毛利 / 毛利率）

- **这是什么**：营收减去直接销售成本（COGS，包括原材料、生产、CDN 带宽成本等）剩下的钱。它衡量"产品本身的盈利能力"，还没扣销售、研发、管理等运营开销。SaaS / 云基础设施公司因为没有物理制造成本，毛利率天然偏高。
- **怎么算**：
  - Gross Profit = `revenue - cogs`
  - Gross Margin = `gross_profit / revenue × 100%`
- **重点关注 / 业务洞察**：
  - **横向**：和同行业（云基础设施 60-75%）对比，低于 50% 说明产品定价太便宜或成本结构有问题。
  - **纵向**：连续多季度下滑 → 产品被压价、上游成本上涨、或产品组合恶化（低毛利 SKU 占比上升）。
  - **稳定性**：毛利率稳定说明定价权和供应链稳；剧烈波动要立刻追问原因。

#### EBITDA / EBITDA Margin（息税折旧摊销前利润）

- **这是什么**：在毛利基础上再扣掉运营费用（销售、研发、管理），但**不扣**折旧摊销、利息和税。它反映"公司主营业务自身赚钱的能力"，是判断经营杠杆释放速度最干净的指标——投资人最看重的运营效率信号。
- **怎么算**：
  - EBITDA = `revenue - cogs - operating_expenses`
  - EBITDA Margin = `EBITDA / revenue × 100%`
- **重点关注 / 业务洞察**：
  - **规模效应**：营收快速增长时，固定费用（研发、办公）被摊薄，EBITDA Margin 会自然扩张。这叫"经营杠杆"，是 SaaS 公司从亏损走向盈利的核心机制。
  - **拐点信号**：Margin 突然收窄 → 要么成本失控，要么为了增长主动加大投入（销售/研发占比上升）。
  - **行业基准**：云基础设施 25%+ 健康、35%+ 优秀；低于 15% 说明还没跨过规模盈亏平衡点。

#### Operating Income (EBIT) / Operating Margin（经营利润 / 经营利润率）

- **这是什么**：EBITDA 减去折旧摊销后剩下的钱。它比 EBITDA 更接近"真实现金流"——因为折旧本质上是过去资本支出的分期，不能忽视。对资本密集型行业（电信、硬件制造、IDC 数据中心）比 EBITDA 更说明问题。
- **怎么算**：
  - Operating Income = `EBITDA - depreciation_amortization`
  - Operating Margin = `operating_income / revenue × 100%`
- **重点关注 / 业务洞察**：
  - **资本开支强度**：D&A 占比大（如 5%+）→ 业务是重资产（自建数据中心、买服务器）；占比小 → 轻资产 SaaS。
  - **EBIT vs EBITDA 差距**：两者差距稳定说明 CapEx 节奏稳；差距突然拉大 → 近期有大额资产投入。
  - **管理层考核**：CEO/COO 通常以 EBIT 增长作为奖金基准，比 EBITDA 更严格。

#### Net Income / Net Profit Margin（净利润 / 净利率）

- **这是什么**：扣除所有成本、费用、折旧、利息、税之后，公司最终真正赚到的钱——股东能分配的部分。这是底线指标。
- **怎么算**：
  - Net Income = `(operating_income - interest_expense) × (1 - tax_rate)`
  - Net Margin = `net_income / revenue × 100%`
- **重点关注 / 业务洞察**：
  - **杠杆效应**：Net Margin 与 Operating Margin 的差距，反映财务杠杆（利息）和税率。
  - **税率波动**：跨国业务（不同地区税率）、税收优惠到期、政府补贴都会让 Net Margin 上下跳——要剔除一次性影响看趋势。
  - **健康基线**：成熟 SaaS 公司 Net Margin 通常 15-25%；初创期可能是负的，但要追踪"何时转正"。
  - **盈利质量**：Net Income 高 ≠ 真赚钱。要和经营现金流（OCF）对比，如果长期 OCF < Net Income，说明利润是"账面"上的（应收堆积）。

### 回报指标

回答的核心业务问题：**"股东和债权人投入的每一块钱，能赚回多少钱？"**——这是相对盈利能力，比利润率更反映"钱生钱"的效率。回报率高 → 商业模式优秀 → 资本应该涌进来；回报率低 → 资本配置效率差 → 投资人用脚投票。

#### ROE（净资产收益率 / Return on Equity）

- **这是什么**：股东投入的每一块钱净资产，一年内赚回多少净利润。这是巴菲特最看重的指标。他说过："如果只能看一个数字，就看 ROE。"
- **怎么算**：
  - ROE = `net_income / average_shareholders_equity × 100%`
  - 平均权益 = `(期初权益 + 期末权益) / 2`（必须用平均，不能用期末，否则高增长公司会被高估）
- **重点关注 / 业务洞察**：
  - **杜邦三因子分解**（理解 ROE 为什么高/低）：
    `ROE = 净利率 × 资产周转率 × 权益乘数(杠杆)`
    高 ROE 可能是：(a) 利润率好（产品强），(b) 周转快（运营强），(c) 杠杆高（财务激进）。三种"高质量"完全不同。
  - **行业基准**：15%+ 良好、20%+ 优秀；低于 10% 通常说明业务缺乏护城河。
  - **持续性**：单季 20% 不稀奇，连续 5 年 20%+ 才是真本事——要画趋势图，看是否能维持。
  - **陷阱**：高 ROE 可能来自高杠杆（银行、保险）。要看 D/E 比率交叉验证。

#### ROA（总资产收益率 / Return on Assets）

- **这是什么**：公司所有资产（无论借来的还是股东的）每一块钱赚回多少净利润。比 ROE 更"客观"，因为不受杠杆影响——直接衡量资产使用效率。
- **怎么算**：
  - ROA = `net_income / average_total_assets × 100%`
- **重点关注 / 业务洞察**：
  - **行业差异大**：零售/餐饮 10-20%（轻资产周转快），电信/制造 3-6%（重资产）。对比要同行业比。
  - **云基础设施**：5-10% 健康，12%+ 优秀。
  - **ROE 与 ROA 的差距** = 财务杠杆贡献：
    - 差距小（< 3pp）→ 公司主要靠经营效率赚钱，财务保守
    - 差距大（> 8pp）→ 严重依赖杠杆放大 ROE，风险高
  - **下降信号**：ROA 下滑要么利润率恶化，要么资产周转变慢（库存积压、应收拉长）。

#### ROIC（投入资本回报率 / Return on Invested Capital）

- **这是什么**：公司真正投入运营的资本（股东权益 + 有息负债，不含无息负债如应付账款）赚回的税后回报。这是判断"业务本身值不值得继续投钱"的最干净指标——比 ROE 不受杠杆扭曲，比 ROA 更聚焦经营性资本。
- **怎么算**：
  - NOPAT = `operating_income × (1 - tax_rate)`（税后经营利润）
  - Invested Capital = `equity + short_term_debt + long_term_debt`
  - ROIC = `NOPAT / invested_capital × 100%`
- **重点关注 / 业务洞察**：
  - **vs WACC**：ROIC > WACC（加权平均资本成本，通常 7-9%）→ 公司在创造价值；ROIC < WACC → 在毁灭价值，无论报表利润多好看。
  - **趋势**：连续上升说明资本配置越来越聪明；连续下降要警惕——管理层可能在错误的方向砸钱。
  - **vs 行业**：10%+ 良好，15%+ 优秀。低于 5% 通常说明行业竞争激烈或商业模式先天不足。

### 流动性指标

回答的核心业务问题：**"公司手头的钱够不够还短期债务？会不会突然断血倒下？"**——流动性危机是企业倒闭的第一大原因（远多于亏损）。盈利能力再强，短期还不上钱也会死掉（参考 2008 雷曼）。

#### Current Ratio（流动比率）

- **这是什么**：流动资产（一年内能变成钱的）能覆盖流动负债（一年内要还的）多少倍。衡量"短期偿债能力"最基础的指标。
- **怎么算**：
  - 流动资产 = `cash + accounts_receivable + inventory`
  - 流动负债 = `accounts_payable + short_term_debt`
  - Current Ratio = `current_assets / current_liabilities`
- **重点关注 / 业务洞察**：
  - **健康区间**：1.5-3.0。低于 1.0 = 流动性红灯，可能发不出工资、付不起货款；高于 3.0 = 资产闲置，资金效率差。
  - **行业差异**：云基础设施 / SaaS 通常 2-4（现金充裕、轻资产）；零售/制造通常 1.2-1.8（库存大、应收慢）。
  - **趋势向下**：连续 3 季度下滑要警惕——可能客户付款变慢、或大额短期债务到期。
  - **注意**：Current Ratio 高 ≠ 健康。要看 Quick Ratio 才能判断"水分"（存货可能卖不掉）。

#### Quick Ratio（速动比率 / 酸性测试比率）

- **这是什么**：比 Current Ratio 更严格的测试——把存货（最难变现的）剔除掉，看剩下的"硬资产"能不能覆盖短期债务。"酸性测试"是金融术语，意思是"用最强的酸也化不掉"。
- **怎么算**：
  - Quick Ratio = `(current_assets - inventory) / current_liabilities`
  - 也常写为 `(cash + accounts_receivable) / current_liabilities`
- **重点关注 / 业务洞察**：
  - **健康基线**：≥ 1.0。低于 1.0 说明公司依赖卖存货才能还债。
  - **SaaS / 云公司**：Quick Ratio 通常和 Current Ratio 接近（存货占比小，< 5%）。
  - **制造业**：Quick 与 Current 的差距 = 存货占比。差距大说明产品滞销风险。
  - **应收账款质量**：AR 越多，Quick Ratio 越虚。要看 DSO 趋势——账期拉长说明客户在拖延付款。

#### Working Capital（营运资本）

- **这是什么**：流动资产减流动负债的绝对值。表示"公司日常运营周转的净资金"。正数 = 短期财务健康；负数 = 短期债务大于短期资产，要靠借钱或融资续命。
- **怎么算**：
  - Working Capital = `current_assets - current_liabilities`
- **重点关注 / 业务洞察**：
  - **不要孤立看**：3 亿美元的 Working Capital 听起来很多，但如果是 1 万亿营收的公司就太少。要用 WC/Sales 比率。
  - **季节性**：零售旺季前 WC 通常为负（备货用应付融资），旺季结束后变正。看趋势不要看单点。
  - **流失信号**：WC 持续缩水 → 公司在用营运资本"补血"维持运营，财务弹性在变差。

#### Cash Conversion Cycle（现金转换周期 / CCC）

- **这是什么**：公司从"付钱给供应商"到"收到客户回款"中间隔了多少天。CCC 越短 → 现金周转越快 → 越不需要外部融资。负数（如苹果、亚马逊）= 客户先付款、供应商后付款，公司用别人的钱做生意。
- **怎么算**：
  - DIO（存货周转天数）= `(inventory / cogs) × 365` —— 货在仓库放多久
  - DSO（应收账款周转天数）= `(accounts_receivable / revenue) × 365` —— 客户拖多久付款
  - DPO（应付账款周转天数）= `(accounts_payable / cogs) × 365` —— 你拖供应商多久
  - CCC = `DIO + DSO - DPO`
- **重点关注 / 业务洞察**：
  - **SaaS 典型 CCC**：通常 -30 ~ +30 天（订阅制预付款，DSO 几乎为 0）。
  - **零售典型 CCC**：通常 30-60 天。
  - **制造典型 CCC**：通常 60-120 天（要备原材料、做成品、给客户账期）。
  - **延长信号**：CCC 连续 2-3 季度拉长 → 要么存货卖不动、要么客户付款变慢，都是危险信号。
  - **战略杠杆**：DPO 是少数几个"可控"的天数——和供应商谈判延长账期，能立刻释放现金。但代价是供应关系。

### 杠杆与偿债能力

回答的核心业务问题：**"公司欠了多少钱？万一利率上升或营收下滑，能不能还得起？"**——杠杆是双刃剑。聪明地用债可以放大 ROE（用别人的钱赚钱），但用多了就是自杀（雷曼、恒大都是反面教材）。

#### Debt-to-Equity（D/E，债务权益比）

- **这是什么**：公司总负债是股东权益的多少倍。衡量"资本结构"——每 1 块钱股东投入背后，公司借了多少债。
- **怎么算**：
  - D/E = `total_liabilities / shareholders_equity`
- **重点关注 / 业务洞察**：
  - **健康基线**：< 1.0 保守（云公司、SaaS 常态）；1.0-2.0 平衡；2.0-3.0 激进；> 3.0 高风险。
  - **行业差异**：
    - 银行/保险 D/E 通常 5-15（金融业靠杠杆经营）
    - 房地产 D/E 通常 2-4（重资产）
    - SaaS/科技 D/E 通常 < 0.5（轻资产、现金充裕）
  - **方向比水平重要**：D/E 持续上升 → 公司越来越依赖借钱；持续下降 → 在用利润偿还债务或留存盈余扩表。
  - **不能跨行业比**：把银行（高 D/E）和软件公司（低 D/E）比谁健康没有意义。

#### Debt Ratio（资产负债率）

- **这是什么**：总资产中有多大比例是借来的。比 D/E 更直接，因为分母是总资产（不变），分子是负债。也是信用评级机构最看重的指标之一。
- **怎么算**：
  - Debt Ratio = `total_liabilities / total_assets`
- **重点关注 / 业务洞察**：
  - **健康基线**：< 0.4 保守；0.4-0.6 健康；0.6-0.7 警戒；> 0.7 高风险（接近破产边缘）。
  - **S&P 信用评级映射**：< 0.3 → AAA 级；0.3-0.5 → AA/A 级；> 0.6 → 垃圾债边缘。
  - **杠杆收购（LBO）会瞬间拉高**：私募基金收购公司时 Debt Ratio 会跳到 0.7+，后续几年看能不能通过现金流降下来。
  - **结合 ROE 看**：高 Debt Ratio + 高 ROE → 杠杆有效（用债赚更多钱）；高 Debt Ratio + 低 ROE → 自杀式杠杆。

#### Interest Coverage（利息保障倍数 / 利息覆盖比率）

- **这是什么**：营业利润是利息支出的多少倍。衡量"利润能不能覆盖借款成本"——这是判断公司会不会违约的核心指标。债权人（银行）决定是否放贷时第一看的就是它。
- **怎么算**：
  - Interest Coverage = `operating_income / interest_expense`
- **重点关注 / 业务洞察**：
  - **健康基线**：> 5x 安全（云公司常态）；3-5x 正常；1.5-3x 紧张；< 1.5x 违约风险（利润还不够还利息）。
  - **债评映射**：> 8x → 投资级；3-8x → 高收益级；< 3x → 垃圾债。
  - **趋势下降是危险信号**：哪怕当前 5x 健康，如果连续 4 季度下滑到 2x，就是违约前的最后警报。
  - **亏损时不可计算**：如果 Operating Income 为负（或接近 0），这个比率失效或无穷大——说明已经资不抵债的边缘。

### 效率指标

回答的核心业务问题：**"公司的资产/存货运转得快不快？"**——同样赚 100 块，有的公司用 50 块的资产做到，有的用 500 块的资产做到。效率高的公司能用更少的资源赚同样多的钱——这是竞争优势的直接体现。

#### Asset Turnover（资产周转率）

- **这是什么**：每一块钱资产一年内能产生多少营收。衡量"资产产生收入的效率"——杜邦公式的第二个因子。
- **怎么算**：
  - Asset Turnover = `revenue / average_total_assets`
- **重点关注 / 业务洞察**：
  - **行业差异巨大**：
    - 零售/餐饮 2-5x（沃尔玛 2.4x）：轻资产，靠快周转
    - SaaS/软件 0.5-1.5x：通常用现金堆积但收入还来不及转化
    - 电信/制造业 0.3-0.8x：重资产
  - **杜邦拆解**：ROE = 净利率 × 资产周转率 × 杠杆。一个公司 ROE 高的原因，是利润率好、周转快、还是杠杆大？这三个拆开看才知道质量。
  - **提升空间**：销售持平、资产增加（购置设备）→ 周转率必然下降。要看是"主动投资"还是"被动堆积"。

#### Inventory Turnover（存货周转率）

- **这是什么**：一年内存货周转了几次。衡量"存货卖得快不快"——这个数字越大，存货变成现金的速度越快。
- **怎么算**：
  - Inventory Turnover = `cogs / average_inventory`
  - 或反过来算 DIO（存货周转天数）= `365 / inventory_turnover`
- **重点关注 / 业务洞察**：
  - **行业差异**：超市 12-20x（每天补货每天卖），服装 4-8x（季节性），汽车 4-6x，高端制造 2-4x。
  - **下降信号**：连续下滑 = 存货堆积，要么需求减弱，要么产品过时。要查 DIO 趋势。
  - **SaaS / 云公司**：存货占资产比例很小（< 5%），这个指标意义不大，主要看的是订阅周转。
  - **过高也要警惕**：如果存货周转率高得不正常，可能是供应链短缺（缺货丢单）或采购过频（运费上升）。

### 每股指标

回答的核心业务问题：**"每股赚多少、值多少钱？"**——上市公司最直接给股东看的数字。决定股价、估值、市值的关键。

#### EPS（每股收益 / Earnings Per Share）

- **这是什么**：公司一个季度或一年内，每一股能赚到多少净利润。这是市盈率（P/E）的分母，决定了股价估值。
- **怎么算**：
  - EPS = `net_income / shares_outstanding`
  - 注意要用**加权平均**流通股数（考虑期权行权、回购、新发行），不是季末数。
- **重点关注 / 业务洞察**：
  - **三个驱动**：EPS 增长可能来自 (a) 净利润增长（真本事），(b) 回购股票（分母变小），(c) 一次性收益。要拆开看。
  - **摊薄 EPS vs 基本 EPS**：摊薄考虑了所有可能转股的期权/可转债，更保守。两者差距大说明期权多。
  - **跨公司比较**：必须同一行业、同时期。不同资本结构（负债 vs 股权）、不同税率、不同流通股数会让 EPS 不可比。
  - **亏损时**：EPS 为负或无意义。看每股亏损（Loss Per Share）反而能反映问题的严重程度。

#### Book Value per Share（每股账面价值）

- **这是什么**：公司清算时，每一股理论上能分到多少钱。会计意义上的"底线"。
- **怎么算**：
  - Book Value per Share = `shareholders_equity / shares_outstanding`
- **重点关注 / 业务洞察**：
  - **vs 股价**：如果股价 < 每股账面价值的 0.5 倍，市场认为公司资产不值账面那么多（可能有过时资产/商誉虚高）。巴菲特喜欢这种"烟蒂股"。
  - **成长股不适用**：品牌、专利、人才这些无形资产通常不上账面，导致高成长公司的 Book Value 远低于真实价值。亚马逊早期 Book Value 很低但实际价值很高。
  - **下降信号**：每股账面价值持续下降 → 公司在亏损消耗股东权益，或分红太多超过盈利。
  - **vs ROE 配合看**：如果 ROE 稳定 15%+，每股 Book Value 应该每年增长 15% 左右（留存利润再投资）。如果背离，要么分红/回购太多，要么 ROE 不可持续。

## 数据过滤规则

这一节面向**写 SQL 查询的人**（agent 的 SQL 生成部分）。SQLite 和标准 SQL 有不少差异，不注意会得到错误结果或零结果。下面按"场景 → 正确写法 → 为什么 → 错误陷阱"组织。

### 1. 数字字面量与除法（整数除法陷阱）

- **这是什么**：SQLite 默认整型除以整型还是整型（截断小数），跟 Python 3 / JavaScript 完全不同。
- **正确写法**：`expr * 1.0 / divisor` 或 `CAST(expr AS REAL) / divisor`
- **为什么**：要拿到浮点结果，分子或分母必须带小数。
- **错误陷阱**：
  ```sql
  -- 错误：毛利率 = 0
  SELECT (revenue - cogs) / revenue FROM income_statement;

  -- 正确：毛利率 = 0.4
  SELECT (revenue - cogs) * 100.0 / revenue FROM income_statement;
  ```
- **检测方法**：跑完查询后抽查任何比率列。如果是 `0` 或 `1`，几乎肯定是整数除法。

### 2. 时间过滤（按 period 字段）

- **这是什么**：`period` 字段是字符串（如 `"2025-Q3"`），不是真正的日期类型。SQLite 没有原生 `quarter()` / `year()` 函数。
- **正确写法**：
  ```sql
  -- 整年
  WHERE period LIKE '2024-Q%'

  -- 最近 N 个季度（推荐，性能更好）
  WHERE period IN ('2025-Q1', '2025-Q2', '2025-Q3', '2025-Q4')

  -- 跨年范围
  WHERE period >= '2024-Q1' AND period <= '2025-Q2'  -- 字符串排序对 "YYYY-Qn" 格式正确
  ```
- **为什么**：`LIKE 'YYYY-Q%'` 利用前缀匹配，**走索引**，比 `substr(period, 1, 4) = '2024'` 快几个数量级。
- **错误陷阱**：
  ```sql
  -- 错误：SQLite 没有 quarter() 函数
  WHERE quarter(period) = 1

  -- 低效：函数阻止索引使用
  WHERE substr(period, 6) = 'Q1'

  -- 错误：假设 period 是日期类型
  WHERE period >= '2024-01-01'
  ```

### 3. 跨表 JOIN（三表关联模式）

- **这是什么**：ERP 财务数据分成 `income_statement`（流量）、`balance_sheet`（存量）、`cash_flow`（流量）。计算 ROE、ROA、自由现金流等指标**必须**三表关联。
- **正确写法**：用 `period + company_id` 双重主键 JOIN（period 单独不唯一，因为多公司）：
  ```sql
  FROM income_statement is
  JOIN balance_sheet bs
    ON is.period      = bs.period
   AND is.company_id  = bs.company_id
  JOIN cash_flow cf
    ON cf.period      = is.period
   AND cf.company_id  = is.company_id
  WHERE is.company_id = 1
  ```
- **为什么**：
  - 三表的"粒度"都是 `(company_id, period)`，所以 JOIN 条件必须两个都有。
  - 漏掉 `company_id` 在单公司下没问题，但**只要将来加第二家公司，所有比率计算都会出错**（会出现笛卡尔积）。
- **错误陷阱**：
  ```sql
  -- 错误：单字段 JOIN，未来加公司会爆炸
  JOIN balance_sheet bs ON is.period = bs.period

  -- 错误：缺少 WHERE 限定公司
  SELECT ... FROM income_statement  -- 返回所有公司
  ```

### 4. 窗口函数（同比、环比、累计）

- **这是什么**：SQLite 3.25+ 支持 `LAG()` / `LEAD()` / `ROW_NUMBER()` 等窗口函数。这是算 YoY、QoQ、移动平均的唯一正确方式。
- **正确写法**：
  ```sql
  -- 同比（去年同期）
  SELECT period, revenue,
         LAG(revenue, 4) OVER (ORDER BY period) AS rev_ly,
         ROUND((revenue * 1.0 / LAG(revenue, 4) OVER (ORDER BY period) - 1) * 100, 1) AS yoy_pct
  FROM income_statement
  WHERE company_id = 1;

  -- 环比（上一季度）
  LAG(revenue, 1) OVER (ORDER BY period)

  -- 移动平均（4 季度）
  AVG(revenue) OVER (ORDER BY period ROWS BETWEEN 3 PRECEDING AND CURRENT ROW)
  ```
- **为什么**：
  - `LAG(x, n)` 取往上第 n 行的 x，所以 `LAG(revenue, 4)` 是去年同季。
  - 用 `LAG` 比 `self-JOIN` 快（不用物化中间结果），SQLite 会直接在索引上扫。
- **错误陷阱**：
  ```sql
  -- 错误：自 JOIN 性能差且容易写错
  FROM income_statement curr
  JOIN income_statement prev ON prev.period = curr.period - 1 year  -- SQLite 不支持日期运算

  -- 错误：忘记 OVER (ORDER BY period)，LAG 返回 NULL
  LAG(revenue, 4)  -- 没有 ORDER BY，行为未定义
  ```

### 5. NULL 处理

- **这是什么**：SQLite 里 `NULL` 表示"未知"，不是"零"。`NULL + 1 = NULL`，`NULL = NULL` 也是 `NULL`（不是 TRUE）。
- **正确写法**：
  ```sql
  -- 用 COALESCE 兜底
  COALESCE(accounts_receivable, 0)

  -- 判断 NULL 必须用 IS NULL
  WHERE LAG(revenue, 4) OVER (...) IS NOT NULL

  -- 算比率时分母为 0 / NULL 都要处理
  CASE WHEN divisor = 0 OR divisor IS NULL THEN NULL
       ELSE numerator * 1.0 / divisor END
  ```
- **为什么**：第一行（最早季度）的 `LAG` 返回 `NULL`，算同比时 `revenue / NULL = NULL`，整行变 NULL。如果不 `WHERE IS NOT NULL`，最终结果会含一行垃圾。
- **错误陷阱**：
  ```sql
  -- 错误：NULL 不等于任何值
  WHERE field = NULL              -- 永远返回 0 行
  WHERE field != NULL             -- 永远返回 0 行

  -- 错误：NULL 参与算术结果变 NULL
  SELECT revenue + NULL            -- 返回 NULL
  SELECT revenue * 100 / NULL     -- 返回 NULL（看似无害其实致命）
  ```

### 6. LIMIT 与性能

- **这是什么**：财务分析数据量小（12 季度 × 6 表 ≈ 几百行），不需要太在意性能；但 ERP 系统表如果很大（百万级交易），JOIN 后不 LIMIT 会慢。
- **正确写法**：
  ```sql
  -- 探索性查询：先 LIMIT 5 看 schema
  SELECT * FROM income_statement LIMIT 5;

  -- 正式分析：加 LIMIT 200 保护下游（前端图表不需要几千个点）
  SELECT ... LIMIT 200;
  ```
- **为什么**：分析场景下几百行已足够画图，返回一万行只会拖慢前端渲染。
- **错误陷阱**：
  ```sql
  -- 错误：忘记 LIMIT，把整个表吐给 LLM
  SELECT * FROM transactions;
  ```

### 7. 计算列 vs 字段引用

- **这是什么**：ERP 表里只存原始事实（revenue, cogs），**所有比率都是计算出来的**，不存在 `gross_margin` 字段。
- **正确写法**：直接在 SELECT 里计算。
  ```sql
  SELECT period,
         revenue - cogs AS gross_profit,
         (revenue - cogs) * 100.0 / revenue AS gross_margin_pct
  FROM income_statement;
  ```
- **错误陷阱**：
  ```sql
  -- 错误：试图查不存在的字段
  SELECT gross_margin FROM income_statement;  -- 没有这一列
  ```
- **检测方法**：先用 `PRAGMA table_info(table_name)` 看每张表有哪些列。

### 8. 时间窗口与"最新季度"

- **这是什么**：很多分析 KPI 要看"最新一个季度"。硬编码 `"2025-Q4"` 容易过时；推荐用 `MAX(period)` 子查询。
- **正确写法**：
  ```sql
  -- 最新季度
  SELECT * FROM income_statement
  WHERE period = (SELECT MAX(period) FROM income_statement WHERE company_id = 1)
    AND company_id = 1;

  -- 最近 4 个季度
  SELECT * FROM income_statement
  WHERE company_id = 1
  ORDER BY period DESC
  LIMIT 4;
  ```
- **为什么**：DB 更新后（新增 2026-Q1），硬编码的 `"2025-Q4"` 就不再是最新，分析会停在上一季。
- **错误陷阱**：
  ```sql
  -- 错误：硬编码过期
  WHERE period = '2025-Q4'  -- 加新季度后会变成"上一季"而非"最新"
  ```

### 9. 公司维度（多公司场景）

- **这是什么**：当前数据是单公司（AcmeCloud Inc.），但 schema 设计成支持多公司（每个表都有 `company_id`）。
- **正确写法**：永远在 WHERE 里限定公司，即使当前只有一个：
  ```sql
  WHERE company_id = 1
  ```
- **为什么**：
  - 防御性编程：未来加公司不会破坏现有查询。
  - JOIN 时不限定公司会出现笛卡尔积。
- **错误陷阱**：
  ```sql
  -- 错误：跨公司聚合，错误地累加
  SELECT SUM(revenue) FROM income_statement;  -- 包含所有公司
  ```

### 10. 常用快捷模式

下面四个模式在分析中反复用到，直接复制可省时间。

**a) 单季度的核心指标（最新季 KPI）**
```sql
SELECT period, revenue, cogs, operating_expenses,
       depreciation_amortization, interest_expense,
       revenue - cogs - operating_expenses AS ebitda
FROM income_statement
WHERE company_id = 1
  AND period = (SELECT MAX(period) FROM income_statement WHERE company_id = 1);
```

**b) 跨年同期对比（YoY）**
```sql
WITH curr AS (
  SELECT period, revenue FROM income_statement
  WHERE company_id = 1 AND period LIKE '2025-Q%'
), prev AS (
  SELECT period, revenue FROM income_statement
  WHERE company_id = 1 AND period LIKE '2024-Q%'
)
SELECT c.period, c.revenue AS curr_rev, p.revenue AS prev_rev,
       ROUND((c.revenue - p.revenue) * 100.0 / p.revenue, 1) AS yoy_pct
FROM curr c JOIN prev p ON substr(c.period, 7, 1) = substr(p.period, 7, 1);
```

**c) 累计指标（YTD）**
```sql
SELECT period, revenue,
       SUM(revenue) OVER (
         PARTITION BY substr(period, 1, 4)
         ORDER BY period
         ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
       ) AS ytd_revenue
FROM income_statement
WHERE company_id = 1
ORDER BY period;
```

**d) 分组聚合（按产品 / 客户 / 区域）**
```sql
SELECT category, COUNT(*) AS n,
       SUM(revenue) AS total_revenue,
       AVG(margin) AS avg_margin
FROM products
GROUP BY category
ORDER BY total_revenue DESC;
```

---

## Few-shot SQL 示例

> 以下示例基于 AcmeCloud Inc. 的 ERP 数据。实际使用时，表名/列名以 `sqlite_execute` 查询结果为准。

### 示例 1：季度损益表 + EBITDA 计算

```sql
SELECT period,
       revenue,
       cogs,
       operating_expenses,
       depreciation_amortization,
       interest_expense,
       revenue - cogs - operating_expenses AS ebitda,
       ROUND((revenue - cogs - operating_expenses) * 100.0 / revenue, 1) AS ebitda_margin_pct,
       (revenue - cogs - operating_expenses - depreciation_amortization) AS operating_income,
       ROUND((revenue - cogs) * 100.0 / revenue, 1) AS gross_margin_pct
FROM income_statement
ORDER BY period;
```

### 示例 2：季度 ROE 计算（需要连接资产负债表）

```sql
WITH quarterly AS (
  SELECT is.period,
         ((is.revenue - is.cogs - is.operating_expenses - is.depreciation_amortization - is.interest_expense) * (1 - 0.21)) AS net_income,
         bs.shareholders_equity
  FROM income_statement is
  JOIN balance_sheet bs ON is.period = bs.period AND is.company_id = bs.company_id
),
roe_calc AS (
  SELECT period,
         net_income,
         shareholders_equity,
         LAG(shareholders_equity) OVER (ORDER BY period) AS prev_equity,
         (shareholders_equity + LAG(shareholders_equity) OVER (ORDER BY period)) / 2.0 AS avg_equity
  FROM quarterly
)
SELECT period,
       ROUND(net_income, 0) AS net_income,
       ROUND(avg_equity, 0) AS avg_equity,
       ROUND(net_income * 100.0 / avg_equity, 2) AS roe_pct
FROM roe_calc
WHERE prev_equity IS NOT NULL
ORDER BY period;
```

### 示例 3：季度毛利率与 EBITDA 利润率趋势

```sql
SELECT period,
       ROUND(revenue, 0) AS revenue,
       ROUND((revenue - cogs) * 100.0 / revenue, 1) AS gross_margin_pct,
       ROUND((revenue - cogs - operating_expenses) * 100.0 / revenue, 1) AS ebitda_margin_pct,
       ROUND(((revenue - cogs - operating_expenses - depreciation_amortization) * (1 - 0.21)) * 100.0 / revenue, 1) AS net_margin_pct
FROM income_statement
ORDER BY period;
```

### 示例 4：流动比率与债务权益比

```sql
SELECT bs.period,
       ROUND((bs.cash + bs.accounts_receivable + bs.inventory) * 1.0 /
             (bs.accounts_payable + bs.short_term_debt), 2) AS current_ratio,
       ROUND(bs.total_liabilities * 1.0 / bs.shareholders_equity, 2) AS debt_to_equity,
       ROUND(bs.total_liabilities * 1.0 / bs.total_assets, 2) AS debt_ratio
FROM balance_sheet bs
WHERE bs.company_id = 1
ORDER BY bs.period;
```

### 示例 5：产品利润率分析

```sql
SELECT name,
       category,
       unit_price,
       unit_cost,
       ROUND((unit_price - unit_cost) * 100.0 / unit_price, 1) AS margin_pct,
       units_sold_ytd,
       ROUND((unit_price - unit_cost) * units_sold_ytd, 0) AS gross_profit
FROM products
ORDER BY margin_pct DESC;
```

### 示例 6：客户层级 ARR 汇总

```sql
SELECT tier,
       COUNT(*) AS customer_count,
       ROUND(SUM(arr), 0) AS total_arr,
       ROUND(AVG(arr), 0) AS avg_arr_per_customer,
       ROUND(SUM(arr) * 100.0 / (SELECT SUM(arr) FROM customers), 1) AS pct_of_total_arr
FROM customers
GROUP BY tier
ORDER BY total_arr DESC;
```

### 示例 7：自由现金流计算

```sql
SELECT cf.period,
       cf.operating_cash_flow,
       cf.investing_cash_flow,
       cf.financing_cash_flow,
       (cf.operating_cash_flow + cf.investing_cash_flow) AS free_cash_flow
FROM cash_flow cf
WHERE cf.company_id = 1
ORDER BY cf.period;
```

---

## 工作流程

收到用户请求后，按照下面的步骤来做。每一步都用工具实际操作，不要猜测。

## 第一步：理解数据

> **重要**：本 skill 已经提供了完整 schema（见上方"Schema"章节，列名、类型、用途都有）。
> **不要**花时间重新发现 schema——直接信任已知的列名和语义。下面的步骤是**验证**和**补充**已知的 schema，不是从零探索。

### 1.1 验证已知 schema（而不是发现）

每张表的列名、类型已经在上方列出。**直接信任这些信息**进入下一步。

### 1.2 检查表是否存在 & 数据量

只在以下两种情况做这件事：
- 第一次跑这个 skill（确认 DB 文件能打开）
- 用户说"DB 变了"或报"table not found"错误

```sql
-- 列出所有表，确认 6 张核心表都在
SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;

-- 预期结果：balance_sheet, cash_flow, companies, customers, income_statement, products
```

如果少了任何一张，立刻停止——schema 已经和 SKILL.md 不同步，需要用户确认。

### 1.3 了解时间范围（最重要！）

**这是真正决定后续分析的事**。已知的 period 列是 `"YYYY-Qn"` 格式字符串。

```sql
-- 所有可用期间
SELECT DISTINCT period FROM income_statement ORDER BY period;

-- 当前最新季度（用于 KPI 计算）
SELECT MAX(period) AS latest_period FROM income_statement WHERE company_id = 1;

-- 最早季度（用于算 ROE 的"平均权益"时需要）
SELECT MIN(period) AS earliest_period FROM income_statement WHERE company_id = 1;

-- 每年有几个季度（确认数据完整性）
SELECT substr(period, 1, 4) AS year, COUNT(*) AS quarters
FROM income_statement
WHERE company_id = 1
GROUP BY year ORDER BY year;
```

**预期结果（AcmeCloud 范例）**：
- periods: `2023-Q1` 到 `2025-Q4`，共 12 个
- latest_period: `2025-Q4`
- earliest_period: `2023-Q1`
- 每个 year 行 quarters = 4（数据完整，没有缺失季度）

**异常情况处理**：
| 看到什么 | 意味着什么 | 怎么办 |
|---|---|---|
| 某年只有 3 个季度 | 那年缺一个季度的数据 | 提示用户；同比会缺一季 |
| period 排序乱掉（如 `2025-Q4` < `2025-Q3`） | 字符串比较异常 | 用 `substr(period, 1, 4)` + `CAST(substr(period, 7) AS INT)` 排序 |
| `latest_period` 是未来日期 | 数据录错 | 警告用户 |

### 1.4 抽样看一行真实数据（仅限第一次）

只跑这一次，目的是发现**未知字段**或**NULL 模式**：

```sql
-- 看一行真实的损益表，确认 revenue/cogs/opex 等关键列非 NULL
SELECT * FROM income_statement WHERE company_id = 1 ORDER BY period DESC LIMIT 1;

-- 看一行真实的资产负债表
SELECT * FROM balance_sheet WHERE company_id = 1 ORDER BY period DESC LIMIT 1;
```

**关注点**（已知 schema 应该没问题，但验证一下）：
- `cash` / `revenue` / `shareholders_equity` 是否都是非 NULL？
- 数字是否合理？（revenue 不应该是负数，除非是退款冲销）
- `tax_rate` 在 `companies` 表里是多少？（默认 0.21）

### 1.5 维度表数据量检查

`products` 和 `customers` 维度表的数据量决定图表能展示多少 SKU / 客户：

```sql
-- 产品总数 + 按类别分布
SELECT category, COUNT(*) AS n FROM products GROUP BY category;

-- 客户总数 + 按层级和区域分布
SELECT tier, region, COUNT(*) AS n FROM customers
GROUP BY tier, region ORDER BY tier, region;

-- 客户 ARR 分布范围（看是否有大客户独大）
SELECT MIN(arr), MAX(arr), AVG(arr), SUM(arr) FROM customers;
```

**判定标准**：
- 产品 < 30：可以一张横向柱状图全部展示
- 产品 ≥ 30：必须 TOP-N + "Other" 汇总（详见数据过滤规则 #6）
- 客户 < 100：环形图（donut）能完整展示
- 大客户 ARR / 总 ARR > 30%：在洞察中点名"客户集中度高"

### 1.6 输出"数据画像"清单

完成以上检查后，在心中（不必显式输出）形成以下画像，再进入第二步：

```
数据画像（mental model）：
- 公司：AcmeCloud Inc. (id=1, 税率=21%, 流通股=10M)
- 时间：12 个完整季度，2023-Q1 → 2025-Q4
- IS：revenue / cogs / opex / D&A / interest 都有，无 NULL
- BS：cash / AR / inventory / equity / 总负债 / 总资产 都有，无 NULL
- CF：operating / investing / financing 都有，无 NULL
- products：~12 个，按 5 个类别（IaaS/Storage/Networking/PaaS/AI）
- customers：~N 个，按 3 个层级 × 4 个区域
- 异常：<无>
- 大客户集中度：<评估结果>
```

如果画像里任何一项有异常，**先告诉用户**再开始写 SQL。

### 1.7 不要做的事

| 不要做 | 为什么 |
|---|---|
| ❌ `PRAGMA table_info` 每张表都跑 | schema 已提供，浪费时间 |
| ❌ `SELECT * FROM table` 全表扫描 | 数据可能很大，浪费 token |
| ❌ 自己推断 schema | 已提供且权威 |
| ❌ 跳过时间范围检查 | 不知道 latest_period 就会写过期 SQL |
| ❌ 不看维度表就开始分析产品/客户 | 不知道数据量会画失败的图 |

### 1.8 完整 checklist

进入第二步之前确认：

- [ ] 6 张表都存在
- [ ] time range 已知（earliest + latest period）
- [ ] 数据完整（每个 year 4 季度，无空缺）
- [ ] 关键列无 NULL（revenue / equity / cash）
- [ ] products / customers 数据量已知，决定 TOP-N 阈值
- [ ] 异常情况已记录或排除

## 第二步：理解业务

根据用户的问题，确定：
- 涉及哪些表（如计算 ROE 需要 income_statement + balance_sheet）
- 时间范围（最近 4 个季度？全部 12 个？某年？）
- 维度（按产品/客户/区域拆分还是整体指标？）

参考上方的「核心财务指标定义」选择合适的指标。

## 第三步：编写 SQL 并验证

1. 根据用户的问题和你对数据的理解，写出 SQL（参考上方 Few-shot 示例）
2. 用 `sqlite_execute` 执行 SQL，检查结果是否符合预期
3. 如果结果不对或不合理，调整 SQL 再试

**SQL 规则**：
- 用 `JOIN` 连接相关表（IS + BS + CF + companies）
- 用 `WHERE company_id = 1` 限定公司
- 用 `ORDER BY period` 控制时间顺序
- 计算比率时用 `* 100.0`（浮点除法）
- 同比/环比用 `LAG()` 窗口函数

## 第四步：生成图表

### 标准 ERP 财务仪表盘

当你需要为这个 ERP 数据库生成完整的财务仪表盘时，请按照下面的标准结构产出。这是为了让**不懂技术的财务或决策人员**也能一眼看懂业务。

> **实现位置**：HTML 模板里的 `KPI_SPEC` 和 `CHART_SPEC`（见「动态仪表盘生成流程」章节的步骤 3）就是这套规范的可执行版本——
> agent 改一处即可，模板和文档不会出现两份"事实"。

#### 顶部：8 个关键指标卡片（最新季度）
显示最近一个季度的核心数字，一眼看到公司表现。
卡片内容由 HTML 的 `KPI_SPEC` 定义，键名对应 SQL 列名，格式由 `fmt` 控制（`"$"` 美元/`"pct"` 百分比/`"num"` 数字）。

#### 中间：10 个标准图表
每个图表都要回答一个具体的业务问题：

| # | 图表 | 业务问题 | y 字段（来自 metrics） |
|---|---|---|---|
| 1 | 营收趋势 | 营收在增长吗？增速如何？ | revenue + yoy_pct |
| 2 | 利润分析 | 利润率在变好吗？ | gross_margin / ebitda_margin / net_margin |
| 3 | 回报能力 | 赚钱效率高不高？ | roe / roa + 15% 基准线 |
| 4 | 资本结构 | 债务负担重不重？ | equity / total_liabilities + debt_to_equity + 1.0 警戒线 |
| 5 | 流动性分析 | 资金够用吗？ | current_ratio / quick_ratio + 1.5 安全线 |
| 6 | 现金流质量 | 利润是真金白银吗？ | ocf + ocf_to_rev |
| 7 | 产品组合 | 哪些产品最赚钱？ | products.margin（按降序） |
| 8 | 客户分层 | 客户结构健康吗？ | customers.arr（按 tier） |
| 9 | 区域分布 | 钱从哪里来？ | customers.arr（按 region） |
| 10 | 增长归因 | 增长是哪里来的？ | EBITDA 瀑布（annual bridge） |

**字段名对齐**：表里的 y 字段就是 SQL 预聚合查询输出的列名（snake_case）。改 SQL 列名 → 改这里 → 改 `CHART_SPEC`——三处必须保持一致。

#### 每个图表旁边：3-5 条关键洞察
不要把图表和洞察分开放在不同区域。**图表在左，洞察在右**（或反过来），并排显示，节省屏幕空间。

每条洞察的格式：

```
[图标]  标题
数据：具体数字和对比
业务：意味着什么、为什么重要
```

**图标含义**：
- 📈 趋势 - 上升、下降、持平
- 🎯 发现 - 排名、占比、亮点
- ⚡ 质量 - 现金流、回报率
- 💡 建议 - 改进方向

#### 重要：图表之间要能联动（交叉筛选）
用户在一个图表上**点击某个数据点**（比如点 2024-Q3 的柱子），其他所有图表都要**自动筛选到那个时间点**。这样用户能快速钻取数据。

这叫"交叉筛选"（cross-chart filter），是商业智能工具（Tableau、Power BI）的标准功能。**不要用下拉框做季度聚焦**——下拉框太隐蔽，用户发现不了，且与图表点击交互冲突。

⛔ **禁止**新增"选择聚焦季度"的下拉框或按钮组。聚焦季度的入口**只能**是图表上的数据点。
✅ 下拉框只用于**时间窗口**（全部/2023/2024/2025/最近4季），与 cross-filter 是不同维度。

#### 主题样式
为了让仪表盘看起来专业、可读，使用以下风格：
- **主色**: 深蓝（navy）
- **辅色**: 金色（gold）
- **背景**: 浅灰或白色
- **不要用绿色和红色** — 用深蓝色表示"好"，用灰色表示"差"
- **字体**: PingFang SC、Microsoft YaHei（保证中文显示）
- **风格**: 商务、柔和、不要太鲜艳或对比太强

### 输出方式

- **用户说"图表"/"看一下"** → 生成 PNG 图片（静态图）
- **用户说"仪表盘"/"交互"/"探索"** → 生成 HTML 网页（可交互）

### 实现细节（技术参考）

### 数据提取测试（agent 必做 · 不要只验证"渲染成功"）

写完 HTML 后，agent **必须**做一次端到端的数据提取测试，验证「浏览器实际能拿到的数据」。**只看 Plotly.newPlot 没报错是不够的**——数据可能根本没加载成功（fetch 失败、空数组、字段错名）。

**测试步骤（agent 写完 HTML 后必须跑一遍）：**

1. **JSON 文件本身可读**
   ```bash
   python3 -c "import json; d=json.load(open('erp_data.json')); print('OK', len(d['salesData']), 'quarters')"
   ```
   必须打印 `OK 12 quarters`（或当前数据对应的季度数）

2. **HTTP 服务能拉到 JSON**（模式 A 必须）
   ```bash
   curl -s "http://localhost:8765/erp_data.json?t=$(date +%s)" | head -c 200
   ```
   必须看到 JSON 内容（`{"company": ...`）

3. **HTML 里 fetch 能拿到正确数据**（用 node 或 python 模拟浏览器解析 JS）
   ```bash
   python3 << 'EOF'
   import re, json
   html = open('erp_dashboard.html').read()
   # 检查关键 JS 元素是否存在
   assert 'fetch(DATA_API' in html, "❌ 没有 fetch() 调用"
   assert 'function refreshData' in html, "❌ 缺刷新按钮函数"
   assert 'selectedPeriod' in html, "❌ 缺 cross-filter 状态"
   assert 'overall-insight' in html or 'overallInsight' in html, "❌ 缺总体洞察区块"
   assert 'attachClickFilter' in html or 'plotly_click' in html, "❌ 缺图表 click 监听"
   print("✅ HTML 关键元素齐全")
   EOF
   ```

4. **数据契约字段对齐**
   ```bash
   python3 << 'EOF'
   import json
   d = json.load(open('erp_data.json'))
   # 必须包含这些键
   required = ['company', 'salesData', 'products', 'tiers', 'regions', 'overall']
   for k in required:
       assert k in d, f"❌ JSON 缺字段: {k}"
   # salesData 每条记录必须有这些字段
   required_fields = ['period', 'revenue', 'grossProfit', 'ebitda', 'netIncome',
                      'grossMargin', 'ebitdaMargin', 'roe', 'currentRatio', 'debtToEquity']
   for f in required_fields:
       assert f in d['salesData'][0], f"❌ salesData 缺字段: {f}"
   print(f"✅ JSON 契约完整 ({len(d['salesData'])} 季度 × {len(d['salesData'][0])} 字段)")
   EOF
   ```

5. **JS 语法检查**（最容易藏 bug 的地方）
   ```bash
   # 抽出 <script> 块用 node 检查语法
   python3 << 'EOF'
   import re
   html = open('erp_dashboard.html').read()
   scripts = re.findall(r'<script>(.*?)</script>', html, re.DOTALL)
   for i, s in enumerate(scripts):
       open(f'/tmp/_chk_{i}.js', 'w').write(s)
   EOF
   for f in /tmp/_chk_*.js; do node --check "$f" || echo "❌ 语法错误: $f"; done
   ```
   **必须全部通过**——否则浏览器会卡死或显示空白

6. **Plotly 调用存在且字段名正确**
   ```bash
   python3 << 'EOF'
   import re
   html = open('erp_dashboard.html').read()
   # 应该有 10 个 Plotly.react 或 Plotly.newPlot
   n = len(re.findall(r'Plotly\.(react|newPlot)\(', html))
   assert n >= 10, f"❌ 只有 {n} 个图表调用，应 ≥ 10"
   # 不应再嵌入静态数据 var DATA = {...}
   assert not re.search(r'var\s+salesData\s*=\s*\[', html), "❌ salesData 被硬编码进 HTML（应通过 fetch 取）"
   print(f"✅ {n} 个图表调用，无静态数据")
   EOF
   ```

7. **刷新按钮必须真能跑通**（这是用户最常点的，bug 率最高）
   ```bash
   python3 << 'EOF'
   import re, json
   html = open('erp_dashboard.html').read()

   # (a) 按钮必须存在且绑定 onclick
   assert re.search(r'<button[^>]+onclick=["\']refreshData\(', html), \
       "❌ 找不到带 onclick 的刷新按钮"
   print("✅ 刷新按钮存在")

   # (b) refreshData() 函数必须实现到位
   assert 'function refreshData' in html, "❌ 缺 refreshData 函数"
   assert re.search(r'function\s+refreshData\s*\([^)]*\)\s*\{[^}]*fetch', html, re.DOTALL), \
       "❌ refreshData 没有调用 fetch（按钮不会真刷新）"
   assert 'btn.disabled = true' in html, "❌ 缺 loading 状态（重复点击风险）"
   assert '✅ 已更新' in html or '已更新' in html, "❌ 缺成功状态反馈"
   assert '❌' in html and '失败' in html, "❌ 缺失败状态反馈"
   print("✅ refreshData 实现完整（fetch + loading + 成功/失败三态）")

   # (c) 刷新后必须清空 selectedPeriod（避免旧聚焦对不上新数据）
   func_body = re.search(r'function\s+refreshData\s*\([^)]*\)\s*\{(.+?)\n\s*\}', html, re.DOTALL)
   assert func_body and 'selectedPeriod = null' in func_body.group(1), \
       "❌ refreshData 没有清空 selectedPeriod（刷新后旧聚焦可能失效）"
   print("✅ refreshData 清空 selectedPeriod")

   # (d) 实际模拟一次 fetch（用 node 验证 refreshData 在浏览器里能跑）
   with open('/tmp/_refresh_test.js', 'w') as f:
       # 提取 refreshData 函数 + 必要依赖
       js_code = re.search(r'(var DATA_API.*?function\s+refreshData\s*\([^)]*\)\s*\{.+?\n\s*\})', html, re.DOTALL)
       if js_code:
           f.write(js_code.group(1) + "\nmodule.exports = { refreshData, DATA_API };")
   print("✅ refreshData 函数可被独立调用")
   EOF
   ```

**agent 必做清单（不能跳）：**

- [ ] erp_data.json 存在且 `python3 -c "json.load"` 通过
- [ ] HTML 用 `fetch(DATA_API)` 加载数据（不是静态嵌入）
- [ ] HTML 含 `refreshData()` 函数 + 按钮 `onclick="refreshData()"`
- [ ] HTML 含 `selectedPeriod` 全局变量 + c1–c6 注册 `plotly_click` 监听
- [ ] HTML 含 `overall-insight` 区块（顶部）
- [ ] `node --check` 通过所有 `<script>` 块的语法
- [ ] 10 个 `Plotly.react/newPlot` 调用
- [ ] HTML 不含 `var salesData = [...]` 字面量（静态嵌入的反模式）
- [ ] **布局**：图表在上、洞察在下；每行 2 个图表（共 5 行），不是左右并排
- [ ] **刷新按钮**：refreshData 内部含 fetch + loading/成功/失败三态 + 清空 selectedPeriod

**为什么必须做：**

- LLM agent 经常"自我感觉写完了"，但实际浏览器加载时：
  - fetch 失败但没报错（catch 只 console.log）
  - 字段名拼错（`debtToEquity` vs `debt_to_equity`）
  - JS 语法错误导致整个 `<script>` 不执行
- 这些问题**不会在 agent 的本地 python 测试里暴露**，必须模拟浏览器行为
- 一个 JS 语法错误就会让整页卡死、显示空白

---

### 实现细节（技术参考）

对于开发者，下面是技术实现的简要说明：

- **8 个 KPI 卡片**：使用 CSS Grid `grid-template-columns: repeat(4, 1fr)`，4 列 × 2 行
- **10 个图表**：使用 CSS Grid `grid-template-columns: repeat(2, 1fr)`，**每行 2 个图表**，共 5 行
- **图表+洞察布局**：**图表在上、洞察在下**（垂直堆叠），不是左右并排
  - 图表卡片：高度 360px
  - 洞察卡片：紧贴图表下方，浅灰背景 `#f5f7fa`，左侧 4px navy 边框
- **交叉筛选**：所有以 period 为 X 轴的图表（c1–c6）必须注册 `plotly_click` + `plotly_doubleclick` 监听器，点击聚焦、双击重置。具体实现见下方「交叉筛选」章节。
- **配色**：
  - 主色 `#1e3a8a`（深蓝 navy）
  - 辅色 `#c8a96a`（金色 gold）
  - 背景 `#f5f7fa`（浅灰）
  - 卡片背景 `#ffffff`（白）
  - 文字主色 `#1f2937`，副色 `#6b7280`
  - 警告色（替代红色）`#dc8a3a`（柔和橙）
  - 成功色（替代绿色）`#1e3a8a`（深蓝）
- **字体栈**: `'PingFang SC', 'Microsoft YaHei', Arial, sans-serif`

---

### 总体洞察（Overall Insight，仪表盘顶部摘要）

仪表盘**顶部**（KPI 卡片之下、图表之上）必须有一个"总体洞察"区块，给出对全公司的整体判断。这不是单图洞察的拼接，而是**跨维度综合结论**。

**必须包含的内容：**

1. **公司画像一句话**（基于 `companies` 表的 industry / founded / tax_rate）
   - 例：「AcmeCloud Inc. 是一家云基础设施公司，自 2018 年成立，适用 21% 税率」

2. **最新季度（latest period）核心指标快照**
   - 营收、净利润、EBITDA、ROE、毛利率、自由现金流
   - 各指标带同比 / 环比变化（用 ▲▼ 符号或文字注明方向）

3. **跨维度核心结论**（3–5 条），按「财务健康度 → 成长性 → 风险点」顺序排列：
   - 📊 **健康度**：流动性、杠杆、利息覆盖倍数 → 整体健康 / 关注 / 警戒
   - 📈 **成长性**：营收 CAGR、利润率扩张、客户/产品集中度 → 强 / 中 / 弱
   - 🎯 **关键发现**：本季度最值得董事会关注的一两个数字
   - ⚡ **风险点**：指标异常或趋势恶化的地方（如某季度应收账款异常升高）
   - 💡 **建议**：基于以上数据的一两条下一步行动建议

**布局与样式：**

- 放在 KPI 卡片正下方、第一个图表上方
- 用浅灰背景卡片 `#f5f7fa` 包裹，与图表卡片视觉区分
- 标题：「📋 总体洞察」或「🔍 仪表盘摘要」
- 每条洞察一行，左侧图标 + 加粗标题，右侧一句话数字/结论
- **必须随筛选变化重新生成**（与单图洞察一样，调用同一个 `generateInsights()` 函数）

**示例输出：**

```
📋 总体洞察 · 2025-Q4

AcmeCloud Inc.（云基础设施，2018 年成立，税率 21%）

📊 健康度 · 良好 — 流动比率 3.95、利息覆盖 38x、D/E 0.39，远超安全阈值
📈 成长性 · 强 — 营收 2 年 CAGR 46.4%，EBITDA 利润率扩张 +15.7pp
🎯 关键发现 — ROE 突破 20.5% 巴菲特阈值，OCF/Rev 达 20.4%（现金转换优秀）
⚡ 风险点 — APAC + LATAM 合计仅 6.7%，单一市场依赖度高
💡 建议 — 1) 加大 APAC 渠道投入  2) 评估是否启动小额分红或回购
```

**SQL 怎么取数：**

```sql
-- 总体洞察不查 SQL，而是基于 salesData JSON 在前端 JS 里计算
-- 因为同一份 JSON 已经被 fetch 进来，复用即可
```

JSON 数据契约里追加一个 `overall` 字段（agent 算好后写入 JSON，HTML 直接读）：

```json
{
  "overall": {
    "company_snapshot": "AcmeCloud Inc.（云基础设施，2018 年成立，税率 21%）",
    "health": {"label": "良好", "summary": "..."},
    "growth": {"label": "强", "summary": "..."},
    "highlights": ["...", "..."],
    "risks": ["..."],
    "suggestions": ["...", "..."]
  }
}
```

---

### 数据获取模式（必选其一）

生成的 HTML 必须支持**实时拉取最新数据**，而不是把数据快照硬编码进文件。两个模式选一个，**默认用模式 A**（禁止只生成静态快照）。

#### 模式 A：Live Fetch（默认 / 必选）

在 HTML 中使用 `fetch()` 调用后端 API，加载完成后再渲染。优点：DB 任何更新打开页面就看到最新；缺点：依赖后端服务可用。

```html
<script>
var DATA_API = "/api/erp/dashboard-data";   // 后端返回 JSON，见下方契约
var salesData = [];
var products = [];
var tiers = [];
var regions = [];
var company = {};

function bootstrap() {
  fetch(DATA_API)
    .then(function(r){ return r.json(); })
    .then(function(payload){
      company   = payload.company;
      salesData = payload.salesData;     // 12 季度
      products  = payload.products;
      tiers     = payload.tiers;
      regions   = payload.regions;
      renderAll(salesData);
    })
    .catch(function(err){
      document.body.insertAdjacentHTML("afterbegin",
        '<div class="err-banner">⚠ 数据加载失败：'+err.message+
        '（确认后端服务 '+DATA_API+' 可用）</div>');
    });
}
bootstrap();
</script>
```

**后端 JSON 契约**（由 skill 自己生成或调用现有 API）：

```json
{
  "company":  {"id": 1, "name": "AcmeCloud Inc.", "currency": "USD", "tax_rate": 0.21},
  "salesData":[
    {"period":"2025-Q4","year":2025,"quarter":"Q4","revenue":24000000,
     "ebitda":6300000,"netIncome":4431900,"roe":20.5,"grossMargin":60.0,
     "ebitdaMargin":26.3,"netMargin":18.5,"currentRatio":3.95,
     "debtToEquity":0.39,"ocf":4900000,"equity":22850000,"liabilities":8950000,
     "cash":12500000,"totalAssets":31800000,"accountsReceivable":8400000,
     "inventory":1800000,"accountsPayable":4400000,"shortTermDebt":1350000,
     "longTermDebt":3100000,"retainedEarnings":9300000,"workingCapital":16950000,
     "ocfToRev":20.4,"roa":14.6,"quickRatio":3.63,"fcf":3000000,"icf":-1900000,
     "cogs":9600000,"opex":8100000,"da":540000,"interest":150000,
     "grossProfit":14400000,"ebit":5760000,"currentAssets":22700000,
     "currentLiabilities":5750000}
  ],
  "products":[{"name":"Cloud VM XL","category":"IaaS","revenue":5843500,"cost":1300000,"grossProfit":4543500,"margin":77.75,"units":6500}],
  "tiers":[{"tier":"enterprise","arr":15800000},{"tier":"mid-market","arr":6950000},{"tier":"smb","arr":1860000}],
  "regions":[{"region":"NA","arr":15315000},{"region":"EU","arr":7630000},{"region":"APAC","arr":1485000},{"region":"LATAM","arr":180000}]
}
```

**生成方式（agent 该怎么做）：**

1. `sqlite_execute` 跑一次 `UNION` / `JOIN` 查询把 IS + BS + CF 三个表的所有度量一次性拉出来（见下方 Few-shot 中的「预聚合查询」）。
2. 用 `python_execute` 算 ROE/ROA/EBITDA/D/E 等派生指标并拼成完整 JSON。
3. **不要把这个 JSON 嵌入 HTML 文件**。把 JSON 写入 `erp_data.json`（同目录下），让后端在 `/api/erp/dashboard-data` 路径返回。
4. HTML 文件只引用 `DATA_API` 常量。

#### 模式 B：Static Embed（仅作回退 / 不推荐）

⚠️ **仅当后端服务不可用、或用户明确要求"独立 HTML 文件"时才使用此模式**。默认必须用模式 A。

直接把 JSON 内嵌进 `<script>`，删除 fetch 调用：

```html
<script>
var company = {...};
var salesData = [...];
// ... 同上，但 bootstrap() 函数替换为：
renderAll(salesData);
</script>
```

**必须**在文件顶部加一行注释说明生成时间：

```html
<!-- Generated: 2026-07-08 | Source: erp_data.db | Mode: static-embed -->
```

并在 HTML 标题后加横幅：

```html
<div class="snapshot-banner">📅 静态快照 · 生成于 2026-07-08 · 数据可能不是最新的</div>
```

### 交叉筛选（Cross-chart filter，必选 · 验收红线）

仪表盘必须支持**点击图表上的数据点聚焦到该季度**，其他所有图表同时高亮该季度，二次点击或双击清除。这是商业智能工具（Tableau / Power BI）的标配交互，**不做视为不合格**。

**核心原则：交互入口是图表本身，不是下拉框。**

- ✅ 用户在 c1 营收趋势图上**点击 2024-Q3 的柱子** → c2/c3/c4/c5/c6 全部聚焦到 2024-Q3
- ❌ **不要**用额外的下拉框 / 按钮组来"选择聚焦季度"——那是冗余交互
- ✅ 下拉框只用于**时间窗口筛选**（全部/2023/2024/最近 4 季），与 cross-filter 是两个独立维度

**实现清单（agent 必须全部实现）：**

| # | 项 | 说明 |
|---|---|---|
| 1 | 全局状态 `selectedPeriod` | 字符串如 `"2025-Q4"`，`null` 表示未选中 |
| 2 | 注册监听器 | c1–c6 全部注册 `plotly_click` + `plotly_doubleclick` |
| 3 | 单击图表 → 聚焦 | 提取 `pt.x` → 设 `selectedPeriod` → `renderAll(getFiltered())` |
| 4 | 同一季度再点 → 取消 | toggle 行为 |
| 5 | 双击 → 强制清空 | 用 `plotly_doubleclick`，配合 250ms 防抖避免与单击冲突 |
| 6 | 视觉强调 | 选中：原色 + marker 放大 3px；其他：`#d1d5db` 灰 + 不透明 0.25 |
| 7 | 顶部状态栏 | `▸ 高亮聚焦: 2025-Q4`，让用户感知选中状态 |
| 8 | 联动总体洞察 | `selectedPeriod` 改变时**也重算总体洞察区块**（不只是图表） |
| 9 | 时间窗口筛选同步 | 切换时间窗口下拉框时必须清空 `selectedPeriod` |
| 10 | 维度图排除 | c7 产品、c8 客户、c9 区域、c10 瀑布**不**注册 click（无 period 维度） |

**规则：**

- 所有以 `period` 为 X 轴的图表（c1–c6 时间序列类）都**必须**注册 `plotly_click` 监听器。
- 点击提取 `pt.x`（即 period 字符串如 `"2025-Q4"`），存到全局 `selectedPeriod`。
- 第二次点击同一 period → 清除（toggle）。
- **双击图表任何位置** → 强制清除（不依赖是否点到点）。用 `plotly_doubleclick` 事件。
- 由于 Plotly 在双击时会先触发 `plotly_click`，需要 250ms 防抖：
  ```js
  var pendingClick = null;
  el.on('plotly_click', function(ev){
    var pt = ev.points && ev.points[0];
    if (!pt) return;
    pendingClick = {period: pt.x, ts: Date.now()};
    setTimeout(function(){
      if (pendingClick && Date.now() - pendingClick.ts >= 250) {
        var p = pendingClick.period;
        selectedPeriod = (selectedPeriod === p) ? null : p;
        renderAll(getFiltered());
        pendingClick = null;
      }
    }, 260);
  });
  el.on('plotly_doubleclick', function(){
    pendingClick = null; // 取消刚排队的单击
    if (selectedPeriod !== null) { selectedPeriod = null; renderAll(getFiltered()); }
  });
  ```
- 视觉强调（让用户看到哪个季度被选中）：
  - 选中季度：保留原色（navy/gold）+ marker 放大 3px + 不透明
  - 其他季度：颜色变成 `#d1d5db`（浅灰）+ 不透明度 0.25 + 折线变灰
  - 用 `perPointColors(periods, baseColor, "#d1d5db")` 之类的辅助函数批量生成
- 顶部信息栏追加：`▸ 高亮聚焦: 2025-Q4`，让用户知道当前选中状态。
- 切换 `filterPeriod` 下拉框或点击"重置"按钮时，**必须同时清空** `selectedPeriod`。
- 非时间序列图表（c7 产品、c8 客户、c9 区域、c10 瀑布）**不要**注册 click 监听（这些是维度图，没有 `period` 维度）。

### 刷新按钮（Refresh Button，必选）

仪表盘**顶部工具栏**（与时间窗口下拉框并列）必须有**刷新按钮**，允许用户主动从后端重新拉取最新数据——而不必刷新整个页面。

**位置与样式：**

```
┌──────────────────────────────────────────────────────────┐
│ [时间窗口: 全部 ▼] [🔄 刷新数据] [▸ 高亮聚焦: 2025-Q4] │
└──────────────────────────────────────────────────────────┘
```

- 按钮文字：`🔄 刷新数据` 或 `Refresh`
- 样式：与下拉框高度一致，使用 navy 主色 `#1e3a8a` 背景 + 白字
- 必须放在筛选下拉框**旁边**（不是隐藏在小菜单里）

**实现逻辑：**

```js
function refreshData() {
  // 1. 显示 loading 状态
  btn.disabled = true;
  btn.textContent = '⏳ 加载中…';

  // 2. 重新 fetch
  fetch(DATA_API + '?t=' + Date.now())   // 防止浏览器缓存
    .then(r => r.json())
    .then(payload => {
      // 3. 替换内存中的数据
      company   = payload.company;
      salesData = payload.salesData;
      products  = payload.products;
      tiers     = payload.tiers;
      regions   = payload.regions;

      // 4. 清掉旧的 cross-filter 状态（数据变了，旧聚焦可能失效）
      selectedPeriod = null;

      // 5. 重新渲染一切
      renderAll(salesData);

      // 6. 显示成功提示
      btn.textContent = '✅ 已更新';
      setTimeout(() => { btn.disabled = false; btn.textContent = '🔄 刷新数据'; }, 1500);
    })
    .catch(err => {
      btn.textContent = '❌ 失败';
      setTimeout(() => { btn.disabled = false; btn.textContent = '🔄 刷新数据'; }, 2000);
    });
}
```

**与 bootstrap 的关系：**

- 页面打开时 `bootstrap()` 自动 fetch 一次（自动模式）
- 用户点击刷新按钮 → `refreshData()`（手动模式）
- 两个函数**底层调用同一个 `fetchAndRender()` 辅助**，避免代码重复

**必须满足的规则：**

1. ✅ 刷新时附加 `?t=<timestamp>` 防缓存
2. ✅ 刷新成功后**清空 `selectedPeriod`**（旧聚焦可能对不上新数据）
3. ✅ 按钮有 loading / 成功 / 失败 三种状态文字反馈
4. ✅ 刷新期间禁用按钮防止重复点击
5. ❌ 不要用 `location.reload()` 整个页面刷新——那会丢失用户当前的筛选状态
6. ❌ 不要用轮询 / 自动刷新——只在用户主动点击时刷新

**视觉反馈（刷新成功后在顶部状态栏追加一行）：**

```
▸ 数据更新于 14:32:15 · 12 个季度（2023-Q1 → 2025-Q4）
```

这样用户能知道当前看到的是哪一刻的数据。

### 预聚合查询（生成 live-fetch JSON 用）

为了减少后端响应次数，agent 应一次性算出所有指标：

```sql
WITH calc AS (
  SELECT is.period,
         is.revenue, is.cogs, is.operating_expenses AS opex,
         is.depreciation_amortization AS da, is.interest_expense AS interest,
         bs.cash, bs.accounts_receivable AS ar, bs.inventory,
         bs.total_assets, bs.accounts_payable AS ap,
         bs.short_term_debt, bs.long_term_debt,
         bs.total_liabilities, bs.shareholders_equity AS equity,
         bs.retained_earnings,
         cf.operating_cash_flow AS ocf,
         cf.investing_cash_flow AS icf
  FROM income_statement is
  JOIN balance_sheet bs ON is.period=bs.period AND is.company_id=bs.company_id
  JOIN cash_flow cf ON cf.period=is.period AND cf.company_id=is.company_id
  WHERE is.company_id = 1
)
SELECT period,
  revenue, cogs, opex, da, interest,
  revenue - cogs AS gross_profit,
  revenue - cogs - opex AS ebitda,
  revenue - cogs - opex - da AS ebit,
  ROUND((revenue - cogs) * 100.0 / revenue, 2) AS gross_margin,
  ROUND((revenue - cogs - opex) * 100.0 / revenue, 2) AS ebitda_margin,
  ROUND(((revenue - cogs - opex - da - interest) * (1 - 0.21)) * 100.0 / revenue, 2) AS net_margin,
  ROUND((revenue - cogs - opex - da) * (1 - 0.21), 2) AS net_income,
  cash, ar, inventory,
  cash + ar + inventory AS current_assets,
  ap + short_term_debt AS current_liabilities,
  ROUND((cash + ar + inventory) * 1.0 / (ap + short_term_debt), 2) AS current_ratio,
  ROUND((cash + ar + inventory - inventory) * 1.0 / (ap + short_term_debt), 2) AS quick_ratio,
  total_assets, total_liabilities, equity,
  ROUND(total_liabilities * 1.0 / equity, 2) AS debt_to_equity,
  ROUND((revenue - cogs - opex - da) * (1 - 0.21) * 100.0 / equity, 2) AS roe,
  ROUND((revenue - cogs - opex - da) * (1 - 0.21) * 100.0 / total_assets, 2) AS roa,
  ocf, icf,
  ocf + icf AS fcf,
  ROUND(ocf * 100.0 / revenue, 2) AS ocf_to_rev
FROM calc ORDER BY period;
```

Python 端再加 `year`/`quarter` 拆分后输出 JSON。

生成 HTML 时遵循以下模式（用 █ 标记的地方需要你根据数据填充）：

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>█ 仪表盘标题 █</title>
  <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
  <style>
    * { box-sizing: border-box; }
    body { margin: 0; padding: 24px; font-family: Arial, sans-serif; background: #f5f7fa; }
    .control-bar { display: flex; gap: 12px; align-items: center; background: #fff; padding: 14px 20px; border-radius: 10px; margin-bottom: 16px; }
    .control-bar select { padding: 6px 12px; border: 1px solid #dce4ec; border-radius: 6px; cursor: pointer; }
    .kpi { background: #fff; padding: 16px; border-radius: 10px; border-left: 4px solid #1f77b4; }
    .kpi .label { font-size: 11px; color: #7f8c8d; text-transform: uppercase; }
    .kpi .value { font-size: 22px; font-weight: 700; }
    .kpi-row { display: grid; grid-template-columns: repeat(█ 自动计算 █, 1fr); gap: 14px; margin-bottom: 16px; }
    .grid { display: grid; grid-template-columns: repeat(█ 自动计算 █, 1fr); gap: 18px; }
    .card { background: #fff; padding: 16px; border-radius: 10px; }
    .chart { width: 100%; height: 380px; }
    .insight-box { background: #fff; padding: 16px; border-radius: 10px; border-left: 4px solid #2ca02c; margin-top: 16px; }
  </style>
</head>
<body>
  <h1>█ 仪表盘标题 █</h1>

  <div class="control-bar">
    <label>期间
      <select id="filterPeriod" onchange="applyFilters()">
        <option value="all">全部</option>
        █ 该列的每个去重值
        <option value="█ 值 █">█ 显示名 █</option>
      </select>
    </label>
    <button onclick="resetFilters()">↺ 重置</button>
  </div>

  <div class="kpi-row">
    █ 4-6 个关键财务指标卡片（Revenue, EBITDA, EBITDA Margin, ROE, Current Ratio, Debt/Equity）
  </div>

  <div class="grid">
    █ 4-6 张图表（收入趋势、毛利率/EBITDA 利润率趋势、ROE 趋势、产品利润对比、客户层级分布、债务权益比）
  </div>

  <div class="insight-box"><h3>关键洞察</h3><ul id="insightList"></ul></div>

  <script>
    // === 模式 A: Live Fetch（推荐）===
    var DATA_API = "/api/erp/dashboard-data";
    var salesData = [];   // 季度时间序列
    var allData   = [];   // 同 salesData 别名，保留以兼容旧代码
    var products  = [];
    var tiers     = [];
    var regions   = [];
    var company   = {};

    function getFiltered() {
      var f = document.getElementById("filterPeriod").value;
      if (f === "all")   return salesData.slice();
      if (f === "last4") return salesData.slice(-4);
      if (f === "last8") return salesData.slice(-8);
      var y = parseInt(f, 10);
      if (!isNaN(y)) return salesData.filter(function(r){ return r.year === y; });
      return salesData.slice();
    }

    function applyFilters() {
      selectedPeriod = null; // 切换过滤时清掉高亮
      renderAll(getFiltered());
    }

    function resetFilters() {
      selectedPeriod = null;
      document.getElementById("filterPeriod").value = "all";
      renderAll(salesData);
    }

    // === 交叉筛选（必选）===
    var selectedPeriod = null;
    var clickableCharts = ["c1","c2","c3","c4","c5","c6"];

    function attachClickFilter(divId) {
      var el = document.getElementById(divId);
      if (!el) return;
      var pendingClick = null;
      el.on('plotly_click', function(ev){
        var pt = ev.points && ev.points[0];
        if (!pt || !pt.x) return;
        pendingClick = { period: pt.x, ts: Date.now() };
        setTimeout(function(){
          if (pendingClick && Date.now() - pendingClick.ts >= 250) {
            var p = pendingClick.period;
            selectedPeriod = (selectedPeriod === p) ? null : p;
            renderAll(getFiltered());
            pendingClick = null;
          }
        }, 260);
      });
      el.on('plotly_doubleclick', function(){
        pendingClick = null;
        if (selectedPeriod !== null) { selectedPeriod = null; renderAll(getFiltered()); }
      });
    }

    function perPointColors(periods, baseColor, dimColor) {
      if (!selectedPeriod) return periods.map(function(){ return baseColor; });
      return periods.map(function(p){ return p === selectedPeriod ? baseColor : dimColor; });
    }
    function perPointOpacities(periods) {
      if (!selectedPeriod) return periods.map(function(){ return 1.0; });
      return periods.map(function(p){ return p === selectedPeriod ? 1.0 : 0.25; });
    }
    function perPointSizes(periods, base) {
      if (!selectedPeriod) return periods.map(function(){ return base; });
      return periods.map(function(p){ return p === selectedPeriod ? base + 3 : base; });
    }

    function renderAll(d) {
      // 更新 KPI 卡片
      // 用 Plotly.react(c1, ...) 重渲染 10 张图表
      clickableCharts.forEach(function(id){ attachClickFilter(id); });
      // 更新底部洞察
    }

    // === Bootstrap: 拉取最新数据再渲染 ===
    function bootstrap() {
      fetch(DATA_API)
        .then(function(r){ return r.json(); })
        .then(function(p){
          company   = p.company   || {};
          salesData = p.salesData || [];
          allData   = salesData;
          products  = p.products  || [];
          tiers     = p.tiers     || [];
          regions   = p.regions   || [];
          renderAll(salesData);
        })
        .catch(function(err){
          document.body.insertAdjacentHTML("afterbegin",
            '<div class="err-banner">⚠ 数据加载失败：'+err.message+'</div>');
        });
    }
    bootstrap();
  </script>
</body>
</html>
```

**重要提示**：HTML 模板中的 █ 标记是让你替换的。你需要：
- 根据实际数据决定筛选栏有几个下拉框
- 根据数据维度决定图表数量和类型
- **不要把数据嵌入 HTML**（除非走模式 B Static Embed 回退）。让 HTML 在 `bootstrap()` 里 `fetch(DATA_API)` 拿最新数据。
- 把 JSON 写到 `erp_data.json`，后端在 `/api/erp/dashboard-data` 路径返回。
- 每次筛选变化时用 `Plotly.react()` 重新渲染图表
- 时间序列图表（c1–c6）必须注册点击 + 双击监听器做交叉筛选

## 第五步：解释结果

生成图表后，用中文告诉用户：
1. 你看到了什么财务数据（具体数字、趋势、变化幅度）
2. 这些数据说明了什么（业务含义、行业对比）
3. 有什么值得注意的地方（异常、风险、机会）
4. 建议进一步分析什么（基于发现的疑问）

---

## 边界情况与常见错误

### 1. 计算平均权益时使用期初权益
❌ 直接用期末权益计算 ROE
✅ 必须用 `LAG()` 取上一期权益，再求平均

### 2. 整数除法导致比率变 0
❌ `gross_profit / revenue`（整数除法 → 0）
✅ `(gross_profit) * 100.0 / revenue`（浮点除法 → 0.7）

### 3. 忘记限定公司
❌ 跨公司查询（多公司场景下）
✅ 始终加 `WHERE company_id = 1`

### 4. 现金流跨表 JOIN 错误
❌ 用 `JOIN cash_flow cf ON cf.period = is.period`（period 唯一但仍要明确）
✅ 同时限定 `company_id`：`ON cf.period = is.period AND cf.company_id = is.company_id`

### 5. 流动比率分子分母混淆
❌ 把 `inventory` 算入 `current_liabilities`
✅ 流动资产 = cash + AR + inventory；流动负债 = AP + short_term_debt

### 6. 分类列有 50+ 个不同值
❌ 饼图有 50 个扇形
✅ 取 TOP-N + "Other" 汇总

### 7. 筛选栏忘记做
❌ 「交互式仪表盘」没有筛选栏 → 不是交互式的
✅ **必须**为 `period` 等分类列生成 `<select>` 下拉框

---

## 行业基准参考

AcmeCloud 属于**云基础设施**行业，参考基准如下：

| 指标 | 基准范围 | 健康值 | 优秀值 |
|---|---|---|---|
| EBITDA Margin | 15-35% | 25% | 35%+ |
| Gross Margin | 50-80% | 65% | 75%+ |
| ROE | 10-25% | 15% | 20%+ |
| ROA | 5-15% | 8% | 12%+ |
| Current Ratio | 1.2-3.0 | 1.5 | 2.0+ |
| Debt/Equity | 0.5-2.0 | 1.0 | <0.5 |
| Interest Coverage | 3.0+ | 5.0 | 10.0+ |
| Asset Turnover | 0.5-1.5 | 0.8 | 1.2+ |

**分析时务必对照这些基准做评判**，并明确指出当前数据是否健康、是否需要关注。
