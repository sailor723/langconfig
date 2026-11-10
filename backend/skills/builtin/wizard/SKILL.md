---
name: "Wizard（向导脚本）"
lang: zh
translated: machine
source: backend/skills/en-originals/wizard/SKILL.md
description: >-
  生成一个交互式 bash 向导，一步步引导人类走完只有他们本人才能执行的步骤。适用于配置基础设施、
  设置凭据或 CI 密钥、走一遍陌生的第三方控制台，以及执行一次性的迁移或切换。
  智能体自己就能完成的步骤，不要调用本技能。
tags:
  - "wizard"
  - "mattpocock"
triggers:
  - "配置基础设施、设置凭据或 CI 密钥、走一遍陌生的第三方控制台"
allowed_tools:
  - "read_file"
  - "grep"
  - "glob"
  - "write_file"
  - "edit_file"
  - "bash"
author: "mattpocock (MIT), adapted for LangConfig"
version: "1.0"
---

> **来源说明。** 改编自 `mattpocock/skills → skills/engineering/wizard`（MIT，原样收录于
> `vendor/upstream-skills/mattpocock/skills/engineering/wizard/SKILL.md`）。
> 为本仓库所做的改动：frontmatter 字段（`tags` / `triggers` / `allowed_tools` / `author` /
> `version`）、路径约定（`docs/specs`、`docs/tickets`、`work/<scope>`）、工具名
> （`read_file` / `write_file` / `edit_file` / `bash` / `grep` / `glob` / `task`），以及一节验证底线。
> 上游的 `disable-model-invocation` 在这里没有对应物——每个技能都可以通过 `skill` 工具发现，
> 所以直接去掉，而不做模拟。

## Instructions（指令）

# 向导脚本

**向导（wizard）** 是一个 bash 脚本，一步步引导人类走完一段手工流程：亲手做很繁琐，每次向 AI 重新解释一遍也同样繁琐。它打开每一个 URL，明确说出点哪里、复制什么，把取到的值收集起来，写到该去的地方（`.env`、GitHub secrets），每个阶段都确认一次，并显示还剩几个阶段。它可能是在配置第三方服务、执行一次性迁移，或者把项目从一个状态搬到另一个状态。

令人愉快的 UX 已经由 [template.sh](template.sh) 解决：逐阶段进度、确认闸门、跨平台打开 URL（含 WSL）、隐藏式密钥输入、幂等的 `.env` 写入、`gh secret` / `gh variable` 写入，以及收尾摘要。**你的工作只是界定流程范围，并撰写它的各个阶段。** `STAGES` 标记之上那部分库在每个向导里都一模一样；这种一致性正是重点：永远不要手工改它。

向导默认是临时的：为一次运行而写，存到草稿路径或 `scripts/` 下，任务完成即删除。只有用户需要一条可重复、应当长在仓库里的安装路径时，才提交它。

## Process（流程）

### 1. 界定流程范围

把人类必须做的每一步手工操作、以及沿途要收集的每一个值都理清楚。先读仓库，不要冷着就问：

- 若是配置：`.env`、`.env.example`、`.env.*`、`README`、`docker-compose*`、框架配置，以及 `.github/workflows/*`（每一处 `secrets.*` / `vars.*` 引用都是向导必须产出的值）。
- 若是迁移或过渡：当前状态、目标状态，以及两者之间不可逆的动作。

然后把各阶段的有序清单、以及每个阶段产出的值摆给用户看，并确认：他们可以增、删或调序。

**完成条件：** 每个阶段都按顺序命名，且对每个被收集的值你都清楚：(a) 人类从哪里拿到它，(b) 它写到哪里（`.env`、某个 GitHub secret、两处都写，还是哪都不写；有些阶段纯粹是动作），(c) 它是密钥（隐藏输入）还是公开值。

### 2. 勾画每个阶段的路径

对每个阶段，写出人类要走的精确路径：打开哪个 URL、在那里做什么、值显示在哪、填给哪个变量，例如“Dashboard → Developers → API keys → Reveal test key → copy”。凡是你不真正了解当前界面或确切命令的地方，就照实说，并去问用户或查文档：永远不要编造可能并不存在的步骤。

**完成条件：** 每个阶段都能落到一条陌生人照着也能走完的具体指令上。

### 3. 撰写向导

把 `template.sh` 复制到目标路径。用每个步骤一个 `stage` 替换示例阶段，按依赖顺序排列。使用库里提供的辅助函数：`stage`、`say`/`step`、`open_url`、`ask`/`ask_secret`、`write_env`、`set_secret`/`set_var`、`pause`/`confirm`。把 `TOTAL_STAGES` 设为你写下的阶段数。

守住模板立下的标准：先打开 URL，再索要它的值；凡是密钥都用 `ask_secret`；每个要留存的值都走 `write_env`；只有 CI 真正需要的值才 `set_secret`；任何不可逆动作之前都先 `confirm`。每个 `stage` 都会清屏，只让当前这一步可见：一个阶段只做一件专注的事，人类要用的内容就不会被滚走。不要碰标记之上那部分库。

### 4. 验证并交付

- `bash -n <script>`；如果有 `shellcheck`，也跑一遍。
- `chmod +x <script>`。
- 不要自己端到端跑它：它会打开浏览器，并阻塞在人类输入上。改为静态追踪：第 1 步列出的每个值都被收集，且落到第 1 步所说的地方；每个 `set_secret` 的名字，与 CI 里某个 `secrets.*` 引用完全对得上。
- 告诉用户怎么运行它。如果这是一条可重复的安装路径，就提交它，并从 README 链接过去，让下一个人直接跑脚本，而不必去问 AI。

## This repository's floor（本仓库的底线）

- **用真实命令验证**，不要靠眼看：`./scripts/housekeeping_verify.sh`（守卫 + `tsc` + `vite build` +
  一份文档库报告）。后端套件加 `--full-suite`。
- **后端套件有 20 个既有的失败。**“不比那个基线更差”是诚实的判据；“测试是绿的”在这里不是一个你能
  做出的宣称。用
  `pytest tests -q --ignore=tests/test_neo4j_document_enrichment.py --ignore=tests/test_pageindex_full_content_loader.py`
  对照，并把 `FAILED` 行与记录的基线做 diff。
- **规格、工单和笔记活在文件里**：`docs/specs/<slug>.md`、`docs/tickets/NNN-<slug>.md`、`work/<scope>/`。
  写在聊天消息里的一句判词，下一轮就丢了。
- **生态层**：智能体代码是 LangGraph 运行时里的 LangChain（`create_agent`），通常由 Deep Agents 框架
  （`deepagents`）包一层。动笔之前先决定这次改动属于哪一层——这就是 `ecosystem-primer` 规则——并优先选
  能胜任的最高层。
