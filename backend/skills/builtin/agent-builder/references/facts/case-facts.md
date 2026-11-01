# 案例事实表 — 12 个教学 agent 的真实配置

收集于 2026-11-01，数据源是 `pg_get_agent`（`### Middleware` 段是当天补上的，补之前有 3 个案例被误判）。
用途：模板从这张表提炼，不凭印象。表改了，模板就要跟着改。

**读这张表的规则**：`native_tools` 不是工具全部。`handoff` 会生成 `transfer_to_<step>`，
`todo_list` 生成 `write_todos`/`read_todos`，`hitl` 不生成工具但会拦调用，`task` 一个工具带所有子代理。

| id | 案例 | run book 意图 | DB 真实（deep / 工具 / 技能 / 子代理 / middleware / mcp） | 冲突与备注 |
|---|---|---|---|---|
| 281 | 1 基础 agent | 三个参数就是一个能用的 agent | normal · 3 工具 `web_search, python_execute, pg_query` · 无技能 · 无子代理 · 无 middleware | `pg_query` 是平台特有工具，教程里的 `calculator`/`weather` 用 `python_execute`/`web_search` 顶替 |
| 159 | 2 工具多到 27 个 | 工具多时还挑得对吗 | normal · **27 工具**（含 `bash`、`python_execute`、`sqlite_*`、`pg_*`、`graphindex_*`、`skill`） · 无技能 · 无子代理 | 提示词 3,426 字是一份中文能力清单；这是「工具全开」的反面教材样本 |
| 326 | 3 文档问答 | 不预载文档，用工具按需读并标来源 | normal · 3 工具 `glob, grep, read_any_file` · 无技能 · 无子代理 | 只读三件套，结构最干净的一个 |
| 323 | 4 个人助理 | supervisor + 两个专家 + 外发前审批 | normal · 1 工具 `task` · 2 子代理（`calendar_expert` 2 工具、`email_expert` 1 工具） · middleware `hitl(5 项)` · **mcp `calendar`** | 2026-11-01 起接了真 Google 日历；`email_expert` 自带 `interrupt_on: write_file` |
| 325 | 5 售后客服 | 一个 agent 三个阶段，用工具集当闸门 | normal · 1 工具 `write_file` · 无子代理 · middleware `handoff(3 步: warranty_collector → issue_classifier → resolution_specialist)` | **主提示词只有 17 字**——真正的提示词在每步的 `system_prompt` 里；描述误写成「案例 7」 |
| 301 | 6 subagents | 主 agent 把专家当工具 | normal · 1 工具 `task` · 2 子代理（`weather_expert` 1、`math_expert` 1） · 无 middleware | 子代理工具各 1 个，是「一个专家一个工具」最纯粹的样本 |
| 314 | 7 handoffs | 把整段对话交给另一个角色 | normal · 2 工具 `web_search, python_execute` · 无子代理 · middleware `handoff(3 步: sales → support → finance)` | 主提示词 18 字，同 325：角色定义在 steps 里 |
| 319 | 8 skills | 知识按需加载 | normal · 2 工具 `skill, python_execute` · **技能 0 个** · 无 middleware | **反例**：演示 skills 的 agent 自己没挂技能，靠工作区 `skills/` 目录读文件 |
| 320 | 9 router | 分派台 + 并行 + 汇总 | normal · 1 工具 `task` · 2 子代理（`weather_desk` 1、`math_desk` 1） · 无 middleware | 与 301 结构同形，差别只在提示词的分派策略 |
| 327 | 10 深度研究 | 给题目不给步骤，文件交付 | **deep** · 5 工具 `tavily_search, web_fetch, think_tool, write_todos, read_todos` · 1 子代理 `research-agent`(3 工具) · middleware `todo_list` | 唯一带交付契约（报告进文件、引用 `[n]`）的案例；`web_fetch` 实测仍超预算（11 次 > 8） |
| 328 | 11 内容创作 | 语气进 AGENTS.md，规格进 SKILL.md | **deep** · 3 工具 `tavily_search, web_fetch, think_tool` · 技能 2 个(`blog-post`,`social-media`) · 3 子代理 · `todo_list` | 子代理里的 `blog-post`/`social-media` 是**0 工具**——它们其实是技能名被当成了子代理 |
| 329 | 12 CSV 问答 | 上传表格 → 建库 → 写 SQL 答 | normal · 6 工具 `glob, read_any_file, read_file, sqlite_load_csv, sqlite_execute, python_execute` · 无 middleware | `python_execute` 对纯 SQL 问答是多余权限 |

## 从这张表直接读出来的六条结构规律

1. **12 个里有 10 个是 `use_deepagents=False`**。normal agent 才是这个平台的主力；deep 只用在需要 harness 文件工具 + 子代理编排的 327/328。默认应该选 normal，除非需要 harness 自带的 `ls/read_file/glob/grep`。
2. **`task` 一个工具就是全部委派面**。301、320、323 都只有 `task` 一个 native tool，子代理能力全由它带出来。
3. **handoff 案例的主提示词几乎为空**（325: 17 字、314: 18 字）。把阶段提示词写进主提示词是常见的错法，会覆盖掉步骤自己的定义。
4. **工具集当闸门**（325）：`resolution_specialist` 那一步才有 `write_file`，前面两步没有——顺序不是靠提示词自觉，是靠工具在不在手里。
5. **skills 与 subagents 容易混**（319 空技能、328 把技能名写成 0 工具子代理）。技能是"按需读的文本"，子代理是"隔离上下文里的执行体"，两者不能互换。
6. **多余权限是普遍现象**（159 的 27 工具、329 的 `python_execute`、281 的 `pg_query`）。模板里要给出"最小够用集合"，而不是照抄满配。

## 实测基线（本轮复测过的才算）

| 案例 | 证据 |
|---|---|
| 1（281） | 3 工具时同题 8.1s；27 工具（159）11.5s —— 工具数带来的延迟差 |
| 4（323） | 日历探针：`calendar_list_calendars` ×1 + `calendar_list_events` ×4 + `task` ×1，44–70s 量级 |
| 10（327） | 深度研究一轮 5 次搜索 + 2 次 `think_tool`，报告落 `generated/research/` |
| 其余 | 未在本轮复测，数字以 run book 各案例「实测」表为准 |

## 维护

- 改了 agent 配置 → 重跑一次收集，更新本表；模板若与本表冲突，以模板为准并记录差异。
- 每个案例的真实配置可随时用 `pg_get_agent(<id>)` 复核，`### Middleware` 段不要漏看。
