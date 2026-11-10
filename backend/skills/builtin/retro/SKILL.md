---
name: Retro（复盘）
lang: zh
translated: machine
source: backend/skills/en-originals/retro/SKILL.md
description: 对一次编码会话做复盘。
tags:
- retro
- mattpocock
- requirements
triggers:
- 当被要求做一次**复盘**时
- 当在为编码智能体的运行环境提改进、让以后的运行更好时
allowed_tools:
- read_file
- grep
- glob
- write_file
- edit_file
- bash
- skill
author: mattpocock (MIT), adapted for LangConfig
version: '1.0'
---

## Instructions（指令）

> **来源说明。** 改编自 `mattpocock/skills → skills/engineering/retro`（MIT，原样收录于
> `vendor/upstream-skills/mattpocock/skills/engineering/retro/SKILL.md`）。
> 为本仓库所做的改动：frontmatter 字段（`tags` / `triggers` / `allowed_tools` / `author` /
> `version`）、路径约定（`docs/specs`、`docs/tickets`、`work/<scope>`）、工具名
> （`read_file` / `write_file` / `edit_file` / `bash` / `grep` / `glob` / `task`），以及一节验证底线。
> 上游的 `disable-model-invocation` 在这里没有对应物——每个技能都可以通过 `skill` 工具发现，
> 所以直接去掉，而不做模拟。


用户要求做一次**复盘**。你要为编码智能体的**环境**提出改进，让以后的运行更好。

## 步骤

1. 用 `skill` 工具调用 `writing-for-agents`，取写作风格指南。

2. 读用户指定的那次会话的一手材料。这可能意味着在本机的会话日志里翻找。如果用户没有指定会话，默认用当前这一次。

3. 在下面这些类别里找可改进的候选。

- **导航**：智能体找到正确文件有多容易？文件之间有没有隐藏依赖？一个**导航指针**会不会让它更容易？*什么时候用*：一次会话花了很多时间才找到某条信息。
- **自动化检查**：有没有能抓住智能体所犯错误的自动化检查？lint、类型检查、测试、文件系统 linter？先读仓库自己的检查命令（它的 `package.json` / 构建工具里的 `lint` / `check` 脚本、它的 CI 工作流），这样一个已经存在、却没接上线或悄悄坏掉的检查本身就是发现，而不是重新造一个。一个没有**护栏**的仓库（没有 pre-commit hook，也没有跑它 lint / 类型检查 / 测试命令的 CI 任务）本身就是一条发现：一个没上 lint 的仓库是一处长期错过的机会，不是一个中性的默认状态。*什么时候用*：智能体犯了一个自动化检查本来能抓住的错误，或者仓库根本没有护栏。
- **编码标准**：要不要给**评审智能体**一条新规则去执行？某条既有规则要不要删掉或写清楚？先给违规分类：**机械型**的（固定的语法模式、禁用的 API、导入形状、文件位置规则）就该得到一个确定性检查，没有商量：在仓库自己的 linter 里加一条自定义规则、加一个 pre-commit hook，或加一个 CI 任务，哪个在仓库的语言和既有护栏下最便宜就用哪个。默认是造检查，而不是写规则。`CODING_STANDARDS.md` 只留给真正的**判断性决定**（跨文件一致性、“符合周围的写法”、任何护栏永远替代不了的东西）。*什么时候用*：评审智能体漏抓了一个错误。
- **全局 AGENTS.md**：有没有哪些引导性指令应该挪到编码标准（或自动化检查）里去？*什么时候用*：AGENTS.md 文件特别大——在仓库里或在用户的全局范围。
- **工具经济**：智能体有没有做出本可以精简的昂贵工具调用？有没有哪些定制工具（CLI、MCP）特别费 token？*什么时候用*：智能体做出了一次昂贵的工具调用。
- **空转指令**：在引导文件里找那些不改变智能体行为的指令。*什么时候用*：引导文件又大又笨重。
- **信息通道**：找机会扩大智能体获取信息的途径。用 tee 把开发服务器的日志导出来、对第三方服务开只读访问。*什么时候用*：某条关键信息对智能体不可用。

4. 把这些候选按严重程度排给用户看。

## 参考

### 实现与评审

记住所有工作都走两个阶段：实现与评审。实现智能体的**上下文压力**最大。它负责探索、写代码、调失败。

评审智能体的上下文压力最小——它收到的是 diff，所以不需要探索。它通常也不需要写代码或调试。

这意味着，施加编码标准应该是评审智能体的责任，而不是实现智能体的责任。

### 文件

仓库里有几个文件你可以用：

- `CLAUDE.md` / `AGENTS.md`：这些文件会被推进任何在本仓库工作的智能体的上下文窗口。它们应当极其克制地使用，通常只放指向其他文件的**导航指针**。
- `CODING_STANDARDS.md`：这个文件在评审时读，实现时不读。如果标准文件长过 1,000 行，就加**导航指针**指向 docs 目录。
- 文档：把文档当作参考文件，由别的文件指过去。写新文档之前先找有没有现成的。
- 技能：用技能承载文档（因为它们的 description 会进智能体的上下文窗口），或者承载用户调用的命令。遵循 `writing-for-agents` 技能里的建议。

## 本仓库的底线

- **用真实命令验证**，不要靠眼看：`./scripts/housekeeping_verify.sh`（守卫 + `tsc` + `vite build` +
  一份文档库报告）。后端测试套件加 `--full-suite`。
- **后端套件有 20 个既有的失败。**“不比那个基线更差”是诚实的判据；“测试是绿的”在这里不是一个你能做出的宣称。
  用
  `pytest tests -q --ignore=tests/test_neo4j_document_enrichment.py --ignore=tests/test_pageindex_full_content_loader.py`
  对照，并把 `FAILED` 行与记录的基线做 diff。
- **规格、工单和笔记活在文件里**：`docs/specs/<slug>.md`、`docs/tickets/NNN-<slug>.md`、`work/<scope>/`。
  写在聊天消息里的一句判词，下一轮就丢了。
- **生态层**：智能体代码是 LangGraph 运行时里的 LangChain（`create_agent`），通常由 Deep Agents 框架
  （`deepagents`）包一层。动笔之前先决定这次改动属于哪一层——这就是 `lc-ecosystem-primer` 规则——并优先选
  能胜任的最高层。
