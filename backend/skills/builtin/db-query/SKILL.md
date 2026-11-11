---
name: "db-query（数据库查询）"
description: >-
  对 PostgreSQL 提问、要数字、要看结构时的操作手册：三条路径怎么选（自然语言 / 精确 SQL / 结构）、
  表名靠查不靠猜、只读优先、以及 `psql` 兜底时必须守的纪律。含实测反面例子（猜表名 `agents`，真名
  `deep_agent_templates`，白跑三轮）。
  当用户说「查一下库里」「有多少条」「按天统计」「这个库有哪些表」「SQL 报错了」时使用。
tags: [sql, postgres, database, query, read-only, evidence]
triggers:
  - "当用户要一个数字、一次统计、或「库里有没有…」时"
  - "当用户问「这个库/这张表有哪些字段」时"
  - "当用户在跟一个已经建好的库对话（而不是要建库）时"
  - "当 SQL 报错、或你不确定表名/列名时"
allowed_tools: [sql_agent_tool, db_query, db_review, list_files, read_file, skill]
author: LangConfig
version: "1.0"
---

你的任务是**把问题变成一条能重跑的查询**，而不是说一段听起来合理的答案。

## 第 0 步——先分清要走哪条路

| 用户的问法 | 走这条路 | 为什么 |
|---|---|---|
| 「有多少客户」「按城市算收入」——**自然语言** | `sql_agent_tool(question=..., database="<库名>")` | 它内部是一条 LangGraph 管线：列表 → 读结构 → 生成 SQL → **校验** → 只读执行。表名/列名它自己去查 |
| 「跑这条 SQL」「我要精确控制」——**已知 SQL** | `db_query(db_name="<库名>", sql="SELECT …")` | 单条 SELECT、有行数上限、只读会话；结果以 markdown 表格返回 |
| 「这个库长什么样」——**结构** | `db_review(db_name="<库名>")` | 行数 / 空值 / 主键候选 / 外键候选，一次给全 |

**库名从哪来**：用户说过就用；没说就问，或看会话里之前建过的库名。**不要猜**一个库名就开跑。

## 第 1 步——表名和列名：查，不要猜

实测过的反面：一个 agent 直接 `select id, name from agents`，报 `relation "agents" does not exist`；
真实表名是 `deep_agent_templates`。它又换了两三种猜法，白跑三轮才去查目录。

正确顺序：

1. `db_review(db_name=…)` 或 `sql_agent_tool`（它自己会先列表/读结构）；
2. 需要精确的列类型/约束时，查目录：
   ```sql
   select table_name, column_name, data_type
     from information_schema.columns
    where table_schema = 'public'
    order by table_name, ordinal_position;
   ```
3. 拿到真名再写查询。

## 第 2 步——只读优先，`psql` 是兜底不是首选

平台的工具会替你守纪律（`db_query` 只允许单条 SELECT、有行数上限；`sql_agent_tool` 用只读事务）。
`bash` 里的 `psql` **没有这些保护**，所以只有在前两条都不行时才用，并且必须：

- 只写 `SELECT`；要改数据就停下来说明"这需要写入，请确认"；
- 先 `\d <table>` 看清结构，再写查询；
- 一定带 `LIMIT`（否则 288 行的日志表能刷满上下文）；
- 不把 DSN / 密码打进输出（用 `.env` 或已有连接，不打印值）。

## 第 3 步——数字要说清口径

- **同一个指标可能有两种算法**：实测过 `orders.amount`（订单头）与 `Σ(order_lines.qty × products.price)`
  四单里三单不一致（+300 / +70 / −140.5）。**报数时必须说明用的是哪个口径**，否则两个答案都能自称正确。
- 遥测/日志表（`*_events`、`audit_*`）通常比业务数据大两个数量级，**不要拿它们回答业务问题**。
- 样本太小就先说样本小：「4 笔的环比是噪音，能看方向，不能定目标」。

## 第 4 步——交付

一段话 + 一张表 + 一条可重跑的 SQL。数字旁边写清：库名、口径、行数。
回答"共有 N 条"这种问题，**顺手说一句 `select count(*)` 的结果**，让人能对上。

## 拒绝清单（硬契约）

- 不猜表名/列名就写 SQL；
- 不在没跑过查询的情况下把数字写进回答；
- 不用 `psql` 做写操作，也不在输出里打印凭据；
- 不把遥测表当业务表；
- 不在口径不明时给出"总额/增长"这类比较，也不隐瞒两种口径的差。
