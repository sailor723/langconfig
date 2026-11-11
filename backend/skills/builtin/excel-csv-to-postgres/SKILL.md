---
name: "excel-csv-to-postgres（表格建库）"
description: >-
  用户给一个 Excel 或 CSV，要「能问问题」时：先把它读成结构，再建成一个真的 PostgreSQL 库（一个 sheet/文件
  一张表、列类型按值推断、主键外键按数据判定），然后才写 SQL 回答。含类型推断的两个陷阱（金额别建成整数、布尔别建成
  文本）、相对路径被沙箱拒绝、`:memory:` 装载成功但查询为空、以及"值能对上 ≠ 是外键"。
  当用户说「上传了一个表，帮我看看数据」「把这些数据建成库」「我要按城/按月汇总」时使用。
tags: [excel, csv, postgres, etl, schema, sql, analysis]
triggers:
  - "当用户上传 Excel 或 CSV，并说要「分析」「查」「汇总」「建模」时"
  - "当用户说「把这个表建成数据库」或「能不能用 SQL 查这个文件」时"
  - "当用户要跨 sheet / 跨文件对比，而手工核对不现实时"
  - "当数据要被反复查询（同一份数据问超过两个问题时）"
allowed_tools: [read_any_file, glob, read_file, db_build_from_file, db_review, db_query, write_file, skill]
author: LangConfig
version: "1.0"
---

你的任务：**把一张表变成一个人和 SQL 都能核对的数据源**。输出是一个库 + 一份体检报告，不是"我读取了文件"。

先记住一条判断：**只在心里读取的表格不是数据源**。用户问第三个问题时，你要能对同一份数据重新查一遍而不重新猜列名。

## 第 0 步——先摸清手里是什么（不猜）

```bash
ls -la <工作区>/upload/                     # 谁真的在
python3 - <<'PY'
from openpyxl import load_workbook
wb = load_workbook("<路径>", read_only=True, data_only=True)
for ws in wb.worksheets:
    rows = ws.iter_rows(values_only=True, max_row=3)
    print(ws.title, ws.max_row, ws.max_column, list(rows)[:2])
PY
```

要拿到的是：**几个 sheet、每个多少行多少列、第一行是不是表头**。合并单元格、标题行在表头之上、多 sheet 口径不同
——这三件事只要差一处，后面所有 SQL 都是错的。

**别用 `read_file` 读 `.xlsx`**（它读不到），用 `read_any_file`：它按 `[Sheet: <名>]` 分块给你，块内用 ` | ` 分隔。

## 第 1 步——决定表名和列名的规则，先说给人听

- 表名 = sheet 名 / 文件名 stem，清洗成 ASCII 小写蛇形：`9月` → `m9`，`Order Lines` → `order_lines`，
  中文列名没有可靠的转写就落到 `c1`、`c2`……**关键是稳定且可预测**，不是"好看"。
- 列名同理。重复的加后缀（`name`、`name_2`）。
- 把这张「原表名 → 表名 → 列名」对照表在回答里贴出来。用户要凭它写自己的查询。

## 第 2 步——类型按值推断，但有两个必须加的例外

纯看值会错两次，两次都是静默的：

| 现象 | 纯看值的结果 | 为什错 | 正确做法 |
|---|---|---|---|
| `price` 列全是 `120 / 80 / 180` | `BIGINT` | 金额第一次出现 `99.5` 就炸；样例数据常常是整数 | 列名命中 `price\|amount\|total\|cost\|revenue\|fee\|balance` → `NUMERIC` |
| `ok` 列是 `TRUE/FALSE` | `TEXT`（Excel 给的是 Python `bool`，它既不是数字也不是字符串） | 库里变成字符串 `"True"/"False"`，`where ok` 永远假 | 显式判 `BOOLEAN` |

其余照常推断：整数 → `BIGINT`，小数 → `NUMERIC`，ISO 时间串 → `TIMESTAMPTZ`，全是 JSON 对象/数组 → `JSONB`，
混合 → `TEXT`。**推断结果逐列打印出来**——猜错了要能被人一眼看见。

## 第 3 步——先出方案，用户确认后才建（**这一步不许自动过**）

`db_build_from_file(file=..., db_name=...)` **默认只出方案，不建任何东西**。它返回：sheet → 表名、每一列的推断类型、
行数、两行样例，以及**只有人能拍板的问题**（表头缺失、表头重复、某列一半以上为空、"金额"的推断、0/1 被读成布尔）。

**把这些原样交给用户，等他明确说"可以/建吧"再继续。** 不要自己替他决定，也不要"先建了不好再删"——
库建错的代价不是 DDL，而是他已经在上面问过问题、数字已经进了报告。

用户确认后，用**同样的参数**再调一次，带 `confirm=true`：

```
db_build_from_file(file="upload/orders.xlsx", db_name="orders_xlsx", confirm=true)
```

它会跳过导出工具的元数据 sheet（`00_index`、`catalog`），逐表建并回报行数。**行数必须和工作簿一致**，不一致就停。

用户说"某几列不对"或"跳过某个 sheet"时：先改映射（改文件、或让他确认丢列），**不要**先建再 ALTER。

**两个实测过的坑，别重复踩：**

1. **相对路径会被沙箱拒绝。** `sqlite_load_csv(..., db_path="generated/x.db")` 会回
   `Path 'generated/x.db' is outside the allowed workspace` —— 相对路径按**服务进程的 cwd** 解析，不是你的工作区。
   要写文件就给**能落到沙箱根里的路径**（`outputs/users/<id>/...` 或绝对路径），先在回答里说清写到哪。
2. **`:memory:` 是陷阱，不是默认值。** 装载进内存会 `✅ Loaded N rows`，随后查询是**另一个**内存库 →
   `No rows returned (empty result)`。"装载成功 + 查询为空"这个组合，八成是库没共享，不是数据没有。

## 第 4 步——体检：主键和外键从数据里判出来，不是凭列名

```
db_review(db_name="orders_xlsx")               # 只报告：行数/空值/主键候选/外键候选
db_review(db_name="orders_xlsx", apply=true)   # 用户确认后再建约束
```

**主键外键同样是"先报后建"**：报告里会写"我打算选哪一列当主键、哪几条算外键"，用户点头再 `apply=true`。

三个判据（第一版都做错过）：

- **唯一 ≠ 主键。** 4 行数据里 `amount`、`placed_at` 也都是唯一的；谁当主键要看名字（`id` → `<表>_id` → 其它 `*_id`），
  金额和时间戳排最后，因为那是"碰巧唯一"。
- **值能对上 ≠ 外键。** `customer_id` 的 4 个值恰好都出现在 `order_lines.id` 里，但它指的是 `customers`。
  引用是「列名 + 取值」两件事，只有列名能说清指向哪张表。
- **名字承若的是时间、取值却是小整数** → 命名 bug（例如 `sold_at` 其实存的是门店 id）。**报告，不要硬建外键**，
  建议改名后再补。

建完立刻跑一遍空值/孤儿检查，把 `0` 贴出来；建不上就说明为什么，不要沉默。

## 第 5 步——回答用 SQL，并说明口径

用 `db_query(db_name=..., sql="SELECT …")` 查这个库（`pg_query` 只能查平台自己的库，查不到你刚建的）。


- 先给表名/列名对照（第 1 步那张），再给结论表，数字带单位与千分位。
- **同一个指标若有两种算法，先摊开**：实测过的例子是 `orders.amount` 与 `Σ(order_lines.qty × products.price)`
  四单里三单不一致（+300 / +70 / −140.5）。这说明 `amount` 还含了折扣/运费之类，**不是明细合计**。
  这种时候必须选一个口径并写下"以明细为准"或"以订单头为准"，否则两个答案都能自称正确。
- 表里的遥测/日志表（`*_events`、`audit_*`）不要当业务表用；它们通常比业务数据大两个数量级，
  会诱导你去查"操作记录"回答业务问题。

## 第 6 步——交付

三件事一起给：**库名与连接串**、**表/列对照 + 行数**、**这次查询用到的口径**。用户下次要自己查，凭这三样就够。

## 拒绝清单（硬契约）

- **不在用户确认方案之前建库、加约束**——"先建了不好再删"是本技能禁止的做法；
- 不把「读了文件」当成「建好了库」；
- 不在没核对行数的情况下宣布装载完成；
- 不因为 `✅ Loaded` 就相信查询能读到（见 `:memory:` 坑）；
- 不用"唯一的列"当主键、不因为"取值能对上"就建外键；
- 不把含折扣/运费的订单金额当成明细合计，也不隐瞒两种口径的差；
- 不把遥测表当业务表回答业务问题。

## 与其它技能的接线

- 数据要出图/看板 → 交给 `sql-analyst`（它面向 SQLite/CSV，口径用本技能第 5 步的结论）；
- 已经有钱库、只是写错 SQL → 不用本技能，走 `sql-analyst` 的自检清单（NULL、`UNION ALL`、边界、类型、引号、JOIN 列）；
- 交付前要自证 → `evidence-first-delivery`（行数、孤儿数、口径差都属于"要贴出来的证据"）。
