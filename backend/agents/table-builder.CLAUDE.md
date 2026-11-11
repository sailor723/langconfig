# 表格建库智能体 — CLAUDE.md

镜像 AGENTS.md。要点：两段式建库（方案 → 用户确认 → confirm=true）、对账 PASS 才报数、`db_review` 先报后建。

## Quick reference

- 找文件 `glob("**/*", path="upload")`；读文件 `read_any_file("upload/x.xlsx")`
- 方案 `db_plan_from_file` → 建库 `db_build_from_file(confirm=true)` → 对账 `db_verify_against_file`
- 体检 `db_review` → 查询 `db_query(db_name=..., sql="SELECT …")`
- 明细口径：`Σ(order_lines.qty × products.price)`；订单头口径：`orders.amount`（含折扣/运费）

- 报告必须给连接串（`postgresql://<user>@<host>:<port>/<db>`），默认库服务器是平台自己的那个。

