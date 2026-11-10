---
name: "Setup Matt Pocock Skills（配置 Matt Pocock 技能）"
lang: zh
translated: machine
source: backend/skills/en-originals/setup-matt-pocock-skills/SKILL.md
description: >-
  为工程类技能配置本仓库：搭好它的工单追踪器、分诊标签词表，以及领域文档的布局。在第一次使用其他工程技能之前运行一次。
tags:
  - "setup"
  - "matt"
  - "pocock"
  - "skills"
  - "mattpocock"
triggers:
  - "当被要求搭起工程类技能所假定的那套按仓库配置时："
allowed_tools:
  - "read_file"
  - "grep"
  - "glob"
  - "write_file"
  - "edit_file"
  - "bash"
  - "skill"
author: "mattpocock (MIT), adapted for LangConfig"
version: "1.0"
---

## Instructions（指令）

> **来源说明。** 改编自 `mattpocock/skills → skills/engineering/setup-matt-pocock-skills`（MIT，原样收录于
> `vendor/upstream-skills/mattpocock/skills/engineering/setup-matt-pocock-skills/SKILL.md`）。
> 为本仓库所做的改动：frontmatter 字段（`tags` / `triggers` / `allowed_tools` / `author` /
> `version`）、路径约定（`docs/specs`、`docs/tickets`、`work/<scope>`）、工具名
> （`read_file` / `write_file` / `edit_file` / `bash` / `grep` / `glob` / `task`），以及一节验证底线。
> 上游的 `disable-model-invocation` 在这里没有对应物——每个技能都可以通过 `skill` 工具发现，
> 所以直接去掉，而不做模拟。


# 配置 Matt Pocock 的技能

为工程类技能所假定的那套按仓库配置搭起骨架：

- **工单追踪器**：issue 住在哪里（默认 GitHub；本地 markdown 也开箱即用）
- **分诊标签（triage labels）**：五个标准分诊角色所用的字符串
- **领域文档**：`GLOSSARY.md` 和 ADR 住在哪里，以及读取它们的消费方规则

这是一个由提示词驱动的技能，不是确定性脚本。先探查，把你发现的东西呈现出来，和用户确认，然后才写。

## Process

### 1. 探查

看当前仓库，弄清它的起点状态。存在什么就读什么，不要假设：

- `git remote -v` 和 `.git/config`：这是一个 GitHub 仓库吗？是哪一个？
- 仓库根目录的 `AGENTS.md` 和 `CLAUDE.md`：哪几个存在？其中是否已经有 `## Agent skills` 小节？
- 仓库根目录的 `GLOSSARY.md` 和 `GLOSSARY-MAP.md`，以及旧的 `CONTEXT.md` / `CONTEXT-MAP.md`。如果存在旧文件，
  主动提出用 `git mv` 把它改成 `GLOSSARY` 的名字，并在 `docs/agents/domain.md` 里把这些名字改写过来。
- `docs/adr/` 以及任何 `src/*/docs/adr/` 目录
- `docs/agents/`：本技能之前的产出是否已经存在？
- `.scratch/`：这是本地 markdown 版 `docs/tickets/` 约定已经在用的迹象
- `triage` 技能装了吗？（本技能旁边有没有一个 `triage` 技能文件夹，或你的可用技能里有没有 `triage`。）
  这决定了 B 节到底跑不跑。
- 单体仓库（monorepo）信号：一个 `pnpm-workspace.yaml`、`package.json` 里的 `workspaces` 字段，或者已经堆满
  内容、各自带 `src/` 的 `packages/*`。这些只出现在真正大型的多包仓库里；它们缺席就意味着单上下文
  （single-context），而几乎所有仓库都是这样。

### 2. 呈现发现并提问

总结哪些东西在、哪些东西缺。然后按节依次进行。一节一个答案，再进下一节。

每节都先给出推荐答案，这样用户一个字就能接受它。只有当这个选择真的分叉时，才给一行解释；如果探查已经把它
定了（`triage` 没装时的 B 节、没有单体仓库时的 C 节），就整节跳过。

**A 节：工单追踪器。**

> 解释：“`docs/tickets/`”就是本仓库里 issue 住的地方。`to-tickets`、`triage`、`to-spec` 这类技能从它读、往它写。
> 它们需要知道该调 `gh issue create`、在 `.scratch/` 下写一个 markdown 文件，还是走你描述的别的什么工作流。
> 选你在这个仓库里真正追踪工作的地方。

默认姿态：这些技能是为 GitHub 设计的。如果某个 `git remote` 指向 GitHub，就提议它。如果某个 `git remote`
指向 GitLab（`gitlab.com` 或自建的主机），就提议 GitLab。否则（或者用户更愿意），提供：

- **GitHub**：issue 住在仓库的 GitHub Issues 里（用 `gh` CLI）
- **GitLab**：issue 住在仓库的 GitLab Issues 里（用 [`glab`](https://gitlab.com/gitlab-org/cli) CLI）
- **本地 markdown**：issue 作为文件住在本仓库的 `.scratch/<feature>/` 下（适合个人项目或没有远端的仓库）
- **其他**（Jira、Linear 等）：请用户用一段话描述工作流；技能会把它记为自由散文

把选择记到 `docs/agents/issue-tracker.md`。GitHub 和 GitLab 模板带一个“PRs as a request surface”开关，默认
**关**。保持关闭，也不要提它：想在分诊队列里看到外部 PR 的用户，之后可以在文件里自己打开。

GitHub 或 GitLab 追踪器需要一个可达的仓库。用户选了其中一种、却没有 `git remote` 指向那个主机时，向他们要
仓库 URL 并把它接好（必要时 `git init`、`git remote add origin <url>`），然后再往下走。完成的标准是：在这个
目录里执行 `gh repo view` / `glab repo view` 能打印出该项目；如果做不到，就停下，告诉用户缺什么。

**B 节：分诊标签词表。** 如果 `triage` 技能没装（探查已经告诉你），就整节跳过，因为没装的技能不需要标签。

装了就只问一个问题：

> 你想保留默认的分诊标签吗？（推荐：**是**）

默认值就是五个标准角色，每个标签字符串等于它自己的名字：`needs-triage`、`needs-info`、`ready-for-agent`、
`ready-for-human`、`wontfix`。选**是**，就照原样写。只有用户说不要——通常是因为他们的追踪器已经在用别的
名字（例如 `needs-triage` 用 `bug:triage`）——才收集这些覆盖值，好让 `triage` 套用已有的标签，而不是
创建重复的。

**C 节：领域文档。** 默认用**单上下文**（仓库根目录一个 `GLOSSARY.md` + `docs/adr/`）。这适合几乎所有仓库；
直接写，不用问。

只有探查发现了单体仓库信号时，才提出**多上下文**（一个根 `GLOSSARY-MAP.md` 指向各上下文自己的
`GLOSSARY.md`）。然后和他们确认要哪种布局。

### 3. 确认并编辑

给用户看一份草稿：

- 要加进 `CLAUDE.md` / `AGENTS.md` 中被编辑的那一个的 `## Agent skills` 块（选择规则见第 4 步）
- `docs/agents/issue-tracker.md`、`docs/agents/domain.md` 和 `docs/agents/triage-labels.md` 的内容
  （最后一个只在 `triage` 装了时才给）

写之前先让他们改。

### 4. 写

**选要编辑的文件：**

- 如果 `CLAUDE.md` 存在，编辑它。
- 否则如果 `AGENTS.md` 存在，编辑它。
- 如果两个都不存在，问用户要创建哪一个；不要替他们选。

`CLAUDE.md` 已经存在时，绝不创建 `AGENTS.md`（反过来也一样）；永远编辑已经在那里的那一个。

如果选中的文件里已经有 `## Agent skills` 块，就地更新它的内容，而不是追加一个重复的。不要覆盖用户对周边
小节的修改。

这个块：

```markdown
## Agent skills

### Issue tracker

[one-line summary of where issues are tracked]. See `docs/agents/issue-tracker.md`.

### Triage labels

[one-line summary of the label vocabulary]. See `docs/agents/triage-labels.md`.

### Domain docs

[one-line summary of layout: "single-context" or "multi-context"]. See `docs/agents/domain.md`.
```

只有 `triage` 装了、且 B 节跑过时，才包含 `### Triage labels` 子块并写 `docs/agents/triage-labels.md`。
没装的话，两者都省略。

B 节在 GitHub 或 GitLab 上跑过时，把追踪器缺的每一个已配置标签创建出来（`gh label create` /
`glab label create`）。

然后用本技能文件夹里的种子模板作起点，写那几个文档文件：

- [issue-tracker-github.md](./issue-tracker-github.md)：GitHub 版 `docs/tickets/`
- [issue-tracker-gitlab.md](./issue-tracker-gitlab.md)：GitLab 版 `docs/tickets/`
- [issue-tracker-local.md](./issue-tracker-local.md)：本地 markdown 版 `docs/tickets/`
- [triage-labels.md](./triage-labels.md)：标签映射（仅在 `triage` 已安装时）
- [domain.md](./domain.md)：领域文档的消费方规则 + 布局

对于“其他”`docs/tickets/` 目录，按用户描述的内容从零写 `docs/agents/issue-tracker.md`。

### 5. 完成

告诉用户配置已经完成，以及哪些工程技能从现在起会读这些文件。提一句他们之后可以直接编辑
`docs/agents/*.md`；只有想更换 `docs/tickets/` 追踪器或从头重来时，才需要重跑本技能。

## This repository's floor（本仓库的底线）

- **用真实命令验证**，不要靠眼看：`./scripts/housekeeping_verify.sh`（守卫 + `tsc` + `vite build` +
  一份文档库报告）。后端测试套件加 `--full-suite`。
- **后端套件有 20 个既有的失败。**“不比那个基线更差”是诚实的判据；“测试是绿的”在这里不是一个你能做出的断言。
  用
  `pytest tests -q --ignore=tests/test_neo4j_document_enrichment.py --ignore=tests/test_pageindex_full_content_loader.py`
  对照，并把 `FAILED` 行与记录的基线做 diff。
- **规格、工单和笔记活在文件里**：`docs/specs/<slug>.md`、`docs/tickets/NNN-<slug>.md`、`work/<scope>/`。
  写在聊天消息里的一句结论，下一轮就丢了。
- **生态层**：智能体代码是 LangGraph 运行时里的 LangChain（`create_agent`），通常由 Deep Agents 脚手架
  （`deepagents`）包一层。动笔之前先决定这次改动属于哪一层——这就是 `lc-ecosystem-primer` 规则——并优先选
  能胜任的最高层。
