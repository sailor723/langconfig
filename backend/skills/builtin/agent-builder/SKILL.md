---
name: "Agent Builder（智能体构建器）"
lang: zh
translated: machine
source: backend/skills/en-originals/agent-builder/SKILL.md
description: >-
  构建智能体的规程与六种结构模板。用户要"做一个智能体""把这个活做成智能体"，或问"智能体建得对不对"时读本技能：
  先选 T1–T6 模板，写 rubric，填空建出来，跑探针逐条判定，最后给证据。
version: 1.0.0
author: langconfig
tags:
- agent-building
- templates
- rubric
- verification
triggers:
- 用户要新建一个智能体
- 用户问某个智能体的结构对不对
- 需要把需求变成智能体配置
allowed_tools:
- create_agent
- update_agent
- test_agent
- pg_list_custom_tools
- pg_get_agent
- skill
---

# Agent Builder —— 如何建出一个真的能用的智能体

在调用 `create_agent` 之前先读本文。这里是长版本，短版本在你的系统提示词里。

## 先选模板，再动手想

到目前为止我们建过的东西，六种结构全都覆盖了。读最匹配的那一种，然后填它的 JSON 骨架——不要从零发明结构。

| 模板 | 结构 | 选用时机 |
|---|---|---|
| `references/templates/T1-single-agent.md` | 一个智能体，2–4 个工具，无中间件 | 单一任务、单一工具集，产出答案或文件 |
| `references/templates/T2-supervisor-experts.md` | 只有 `task` + N 个专家 | 工作横跨互不相同的领域，每个专家用约 3 行作答 |
| `references/templates/T3-handoff-machine.md` | 一个智能体 + `handoff` 中间件，每步各自的提示词/工具 | 一段对话、多个阶段，流程中途换角色 |
| `references/templates/T4-skills-driven.md` | 智能体 + `skills` 列表 + `skill` 工具 | 长期存在、很少用到、又必须保持可编辑的知识 |
| `references/templates/T5-research-pipeline.md` | deep agent + `todo_list` + 研究子智能体 | 开放性问题，交付物是一份带引用的文件 |
| `references/templates/T6-data-qa.md` | 上传 → sqlite → SQL | 一张表放进去，问题随后才来 |

每个模板都同样有七节：何时使用、JSON 骨架（含 `{{placeholders}}`）、提示词骨架、工具/中间件、rubric 模板、
实测基线、失败对照表。照抄骨架，替换占位符，然后逐个拿工具 id 去 `pg_list_custom_tools` 核对。

`references/facts/case-facts.md` 记录十二个训练智能体的事实真相——它们实际是什么，以及哪些地方与运行手册
不符。模板与真实智能体冲突时读它；把冲突引出来，而不是藏起来。

## 顺序不可协商

```
rubric  →  build  →  test  →  judge  →  (fix ≤2)  →  deliver
```

建完再写的 rubric 是事后合理化，不是标准。先写 rubric，拿给对方看，等他点头同意再动手建。

### Rubric 的规矩

- 3–5 条标准。每条都必须看一眼测试运行就能判定。
- Bad: 「回答质量好」 · Good: 「调用 web_search 取到当天天气，且温度数字来自工具返回」
- Bad: 「能处理 CSV」 · Good: 「上传 3 行 CSV 后，回答里的行数与文件一致」
- 每条标准配一个探针。像 `hi` 这样的探针什么都测不出来——要写出真实用户为这条标准会发的那句话。
- 存下来：`generated/<slug>.rubric.md`，一条标准一行，编号（`R1`–`R5`）。

## 选 kind

| kind | harness 提供 | 你必须补上 | 选用时机 |
|---|---|---|---|
| `deep` | `ls`、`read_file`、`write_file`、`edit_file`、`glob`、`grep`、`execute`；子智能体；技能；MCP | 文件之外的工具，想要 HITL 就加中间件 | 多步工作、产出是文件、需要专家分工 |
| `normal` | 平台装配的提示词（护栏 + 工具强制）；**没有文件工具** | 需要存文件时显式加 `write_file` | 单一任务、规则应交由平台替你执行 |

除非对方要求平台强制执行的规则，否则默认用 `deep`。

## 查目录——绝不猜工具 id

```
pg_list_custom_tools()      # the real 66 ids with descriptions
search_skills("weather")    # skill search by intent
pg_list_skills()            # everything
skill("<skill-id>")         # full text of one skill
pg_list_agents()            # what already exists, so you do not duplicate
pg_get_agent(<id>)          # the full config of one agent, before you update it
```

提示词里写了目录中并不存在的工具名，会静默失败——智能体干脆永远不会去调用它。这是"看着挺像那么回事、实际
什么都没做"最常见的一种成因。

## 子智能体

只有分工是真的，才加子智能体：

- 子问题需要**另一套工具集**（安全分析师只读代码、不写代码），或者
- 子问题的产出是**一份摘要**，而不是一个文件。

如果一切都用同一套工具、同一份上下文，一个智能体更好。每个子智能体都要付一次交接成本，而它的结果是以文本
形式回来的。

子智能体上的 `interrupt_on` 只拦它自己的工具；父级的策略**进不去**（2026-11-01 实测：父级的审批清单已经设
好，事件仍然在 `task` 内部被创建出来）。

## MCP 服务器

`mcp_servers={"calendar": {"url": "http://127.0.0.1:3000"}}`——建的时候工具就以
`calendar_list_events`、`calendar_create_event`、……的名字到位。挂掉的服务器会被跳过并给一条警告；智能体照常
运行。这些工具的审批来自智能体自己的 HITL 策略，并在每个工具内部执行。

## 技能目录格式（LangChain 文档遵循的规格）

```
<skills-root>/<skill-id>/
├── SKILL.md            # YAML frontmatter (name, description) + instructions
├── references/         # docs the instructions point at
├── scripts/            # runnable helpers
└── assets/             # files used in output (templates, images)
```

- `name` **等于目录名**（kebab-case 的 id）。给人看的名字属于正文标题和数据库那一行，不属于 frontmatter。
- 只有 `references/`、`scripts/`、`assets/` 是规格目录。`templates/` 或 `facts/` 下的文件，对遵循规格的读取方
  是不可见的——`create_skill` 会拒绝这些路径，并说明原因。
- 指令必须**点名每一个支撑文件**，并说清何时去读它。没人提到的文件，就是没人加载的文件（渐进披露第 3 层）。
- 加载顺序是固定的：启动时元数据（name + description）→ 调用时完整的 `SKILL.md` → 只有指令要求时才读支撑
  文件。

## 磁盘与数据库漂移

磁盘上的 `SKILL.md` 是同事编辑并提交的源；数据库那一行才是 `skill()` 提供出去的内容。只改文件到不了智能体
那里——跑 `sync_skills()`（先 dry-run）把更新的文件拉进数据库。反方向一直是通的：`create_skill` 与
`update_skill` 两边都写。

## 创建技能

这个平台上的一个技能是两样东西：`skills` 表里的一行，以及 `backend/skills/personal/<owner>/<skill_id>/` 下
一个纳入 git 的 `SKILL.md`。`create_skill` 两样都写，并返回路径；`update_skill` 把文件写回去。绝不要只写那一
行——没有自己文件夹的技能既没有支撑文件，也没有任何途径到达同事手里。

`create_skill(files={...})` 在同一次调用里写支撑文件——`references/`、`scripts/`、`assets/`，也就是 Agent
Skills 规格定义的那几个目录。路径会被检查：任何逃出技能文件夹的东西都会被拒绝并报告出来。它们按需用
`skill("<id>", file="<relative path>")` 读取，永远不与指令一起加载。

工具的回复是一份**磁盘清单加字节数**（`SKILL.md (4.0 KB)`、`references/checklist.md (… B)`），因为你自己
`ls` 不到那个文件夹——它在 `backend/skills/` 下，在你的工作区之外。汇报你建了什么时，把这份清单引出来；不要
在没有它的情况下声称某个文件存在。

## 测试

`test_agent(agent_id, probe)` 返回：工具序列、耗时、答案文本、超时标志。用证据判定：

```
R1 PASS — 工具序列里有 web_search；回答「上海 24–25℃」与工具返回一致
R2 FAIL — 没有写文件；工具序列只有 web_search、ls
```

每轮只修一件事，然后用同一批探针重测。同一个失败连着出现两轮 = 带证据报告 blocked，不要继续死循环。

## 命名与交付

- 名字：课程材料用 `case-N-<topic>`，其余用 `<topic>-assistant`。小写，连字符，不含空格。
- 交付三个文件：`generated/<slug>.rubric.md`、`<slug>.config.json`（原样的 create_agent 输入）、
  `<slug>.test.md`（探针、工具、耗时、R# 判词）。
- 聊天回复 ≤15 行：id、kind、工具/技能数量、rubric 通过条数、三个路径。

## 值得认出来的失败模式

| 症状 | 可能原因 | 修法 |
|---|---|---|
| 不调用任何工具就作答 | 工具 id 拼错，或提示词从没说清产出必须包含什么 | 重新查目录；在提示词里写明交付物 |
| 调了正确的工具却无视结果 | 两个工具的描述互相重叠 | 删掉较弱的那一个 |
| normal 智能体存不了文件 | `native_tools` 里没有 `write_file` | 加上它，或改用 `deep` |
| 测试里能用，实际一用就坏 | 探针比真实输入窄 | 把探针放宽 |
| 审批卡始终不出现 | 调用发生在子智能体内部 | 在工具层拦截，或去掉子智能体 |
| rubric 里点名了某个具体的读取工具 | 那个工具在这类智能体的目录里可能合法地不存在——`read_file` 在一个 deep agent 里有、在另一个里没有 | 显式选上 `read_any_file`，或把标准写成"用任意读取工具读回来并引用" |

## 模板在不在你的磁盘上？

它们就在本文件旁边的 `references/` 下（`references/templates/`、`references/facts/`）。如果某个 deep agent 的
工作区里 `skills/agent-builder/` 只剩下 `SKILL.md`，说明暂存那一步没有拷支撑文件——那就如实说出来、去要这些
文件，而不是只凭索引表把结构凭空发明出来。（2026-11-01 见过一次：builder 自己的 `skills/` 被暂存成空的，于是
它照着库里的某个智能体重建了 T2，而没用模板。）

## 模板与现实冲突时

`references/facts/case-facts.md` 是刻意记录了已知的坏例子的（智能体 319 是那个技能案例，却一个技能都没有；
智能体 328 把技能名列成零工具的子智能体；智能体 159 背了 27 个工具）。不要照抄它们。说清真实智能体破坏了哪
一条模板规则，然后建修正后的版本。
