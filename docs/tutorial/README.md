# 培训材料

给学员读的东西都在这个目录，按顺序：

| # | 文件 | 讲什么 | 什么时候看 |
|---|---|---|---|
| 1 | **`agent-training-runbook.md`** | 主线教材：12 个案例，从 `create_agent` 到深度研究/内容创作/CSV·Excel 分析，每个案例都有实测证据 | 上课、复建、验收 |
| 2 | `deep-research-agents.md` | 深度研究的**报告模板**：骨架、写作规则、引用规范、agent 契约 | 写案例 10 时对照 |

生成物：`agent-training-runbook.html`（由 `scripts/build_training_html.py` 从 md 构建，图内联，**别手改**）。

```bash
backend/.venv/bin/python scripts/build_training_html.py   # → docs/tutorial/agent-training-runbook.html
```

其它文档的归属：

| 目录 | 放什么 |
|---|---|
| `docs/system-architecture/` | 系统怎么搭的：架构、存储、数据分类、审计、多租户、Deep Agent 研究等 |
| `docs/installation/` | 安装、更新、Google OAuth、局域网访问 |
| `docs/assets/` | 教材用的图（`.dot` 源文件 + 渲染出的 `.svg/.png/.pdf`） |
| `docs/usage.md` | 平台使用手册（面向普通用户） |
