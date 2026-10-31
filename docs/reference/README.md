# 参考文档索引

两类东西，别混着读：

## A. 培训材料（给学员，按顺序读）

| # | 文件 | 讲什么 | 什么时候看 |
|---|---|---|---|
| 1 | **`agent-training-runbook.md`** | 主线教材：12 个案例，从 `create_agent` 到深度研究/内容创作/CSV·Excel 分析，每个案例都有实测证据 | 上课、复建、验收 |
| 2 | `deep-research-agents.md` | 深度研究的**报告模板**：骨架、写作规则、引用规范、agent 契约 | 写案例 10 时对照 |


> `agent-practice.md`（八课实践）已从工作区删除；需要时 `git checkout docs/reference/agent-practice.md` 可以取回。

生成物：`agent-training-runbook.html`（`scripts/build_training_html.py` 从 md 构建，别手改）。

## B. 平台参考（给维护者，培训时不讲）

| 文件 | 讲什么 |
|---|---|
| `agents-audit.md` | 全部 agent 的体检结论 |
| `tools-audit.md` / `tools-refactor.md` | 工具目录审计与重构 |
| `storage-map.md` | 数据都落在哪（工作区、DB、vault） |
| `data-taxonomy.md` | 数据类型与归属 |
| `settings-refactor.md` | 设置页重构 |
| `skill-authoring.md` | 怎么写一个 SKILL.md |
| `deepagent-vs-dsh.md` | Deep Agent 与 DSH 的差别 |
| `deepagents-study.md` | deepagents 库的学习笔记 |
| `deepseek-vision-model.md` | DeepSeek 视觉模型（能读图，不能画图） |
| `multitenancy.md` | 多租户设计 |
| `lan-access.md` | 局域网访问/登录门 |
| `sunhing-dashboards.md` | Sun Hing 看板生成 |
| `GOOGLE_OAUTH_SETUP.md` | Google OAuth（仅 Slides/Drive 导出用） |

本地专用（未纳入版本管理）：`OKF_MINIMAL_PROFILE.md`、`PAGEINDEX_OKF_DESIGN.md`、
`carrier_studio.md`、`ontology_architecture.md`、`langchain-agent-intro.md`。
