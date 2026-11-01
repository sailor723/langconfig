# T6 · 表格问答（SQL）

> 提炼自：案例 12（329）· 事实见 `references/facts/case-facts.md`

## 1 适用场景

用：用户传 CSV/Excel，然后用自然语言提问，答案来自**写 SQL 查出来的数**。
**不要用**：数据在数据库里已经有了（用 `pg_query` 系工具，→ T1）；要做图表/报告（→ T5 的交付思路）。

判据一句话：**问题能翻译成一条 SQL 就有答案**。

## 2 配置骨架

```json
{
  "name": "{{slug}}",
  "kind": "normal",
  "category": "Data",
  "description": "上传 CSV/Excel → 建表 → 写 SQL 回答",
  "temperature": 0.0,
  "native_tools": ["glob", "read_any_file", "read_file", "sqlite_load_csv", "sqlite_execute"],
  "skills": [],
  "subagents": [],
  "middleware": [],
  "system_prompt": "{{见第 3 段}}"
}
```

**不给 `python_execute`**：纯 SQL 问答用不到执行代码（案例 12 带着它，属多余额度）。

## 3 提示词骨架

```
你是表格问答 agent。用户传表格，你用 SQL 回答。

## 必做顺序（不许跳）
1. glob("**/*", path="upload") 找文件
2. read_any_file 读它。Excel 会返回按 sheet 分块的文本（[Sheet: 名称] + 行）
3. 每个 sheet 当一份 CSV：| 换逗号 → sqlite_load_csv(db_path="generated/{{stem}}.db")
   **所有 sheet 进同一个库**
4. 查 sqlite_master 确认表名和列，再写 SQL
5. 回答：给数字 + 一句人话解释 + 用了哪个表

## 硬规则
- 表名只能是 ASCII（9月 → m9，汇总 → summary），中文表名会直接报错
- 只建一次库；同名覆盖，不要 _1/_2 后缀
- SQL 出错就把错误原样看一遍再改，最多重试 1 次
- 查不到就说明表里没有这个数据，不要编数

## 自查清单（每次执行前过一遍）
NULL 是否需 COALESCE / UNION 是否该用 ALL / 边界是否含等号 /
类型是否需 CAST / 字符串引号 / JOIN 列名是否一致
```

## 4 工具与 middleware

| 项 | 必选 | 说明 |
|---|---|---|
| `glob` + `read_any_file` | 必选 | 定位并读上传件（Excel 走 `read_any_file`） |
| `sqlite_load_csv` | 必选 | 建表入口，`db_path` 固定 `generated/<stem>.db` |
| `sqlite_execute` | 必选 | 查 `sqlite_master` + 跑 SQL |
| `read_file` | 可选 | 文本 CSV 更省 token |
| middleware | 无 | 读多写少，不需要审批 |

## 5 rubric 模板

```
R1 建库：generated/{{stem}}.db 存在，sqlite_master 里有表
R2 表名合法：表名全 ASCII（无中文）
R3 数字正确：问"{{可验证的问题}}"，回答的数字与文件内容一致
R4 多 sheet：3 个 sheet 的 Excel → 建出 3 张表（不是只建第一张）
R5 不编数：问一个表里没有的字段，明确说没有，不给假数字
```

## 6 实测基线

- 案例 12（329）：6 工具（含多余的 `python_execute`）；3-sheet 工作簿 → 3 张表
  同一库；表名中文会报错重试

## 7 失败对照

| 症状 | 原因 | 改法 |
|---|---|---|
| 中文表名报错 | 表名没转 ASCII | 提示词第 3 段第 4 条规则 |
| 只建了第一张表 | 每个 sheet 当成"新文件" | 明确"所有 sheet 进同一个库" |
| 建了两次库 | 路径每次不同 | `db_path` 写死 `generated/<stem>.db`，同名覆盖 |
| 数字对不上 | 没自查 NULL/UNION/边界 | 第 3 段自查清单 |
| 直接读 CSV 算数 | 没走 SQL | 硬规则"答案必须来自 SQLite 查询" |
