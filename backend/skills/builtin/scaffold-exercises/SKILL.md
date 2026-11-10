---
name: "Scaffold Exercises（练习脚手架）"
lang: zh
translated: machine
source: backend/skills/en-originals/scaffold-exercises/SKILL.md
description: "创建能通过 lint 的练习目录结构，含小节、题目、答案与讲解。用户想搭练习脚手架、建练习桩，或开一个新的课程小节时使用。"
tags:
  - "scaffold"
  - "exercises"
  - "mattpocock"
triggers:
  - "用户想搭练习脚手架、建练习桩，或开一个新的课程小节"
allowed_tools:
  - "read_file"
  - "grep"
  - "glob"
  - "bash"
  - "skill"
author: "mattpocock (MIT), adapted for LangConfig"
version: "1.0"
---

## Instructions（指令）

> **来源说明。** 改编自 `mattpocock/skills → skills/misc/scaffold-exercises`（MIT，原样收录于 `vendor/upstream-skills/mattpocock/skills/misc/scaffold-exercises/SKILL.md`）。
> 为本仓库所做的改动：frontmatter 字段（`tags` / `triggers` / `allowed_tools` / `author` /
> `version`）、路径约定（`docs/specs`、`docs/tickets`、`work/<scope>`）、工具名
> （`read_file` / `write_file` / `edit_file` / `bash` / `grep` / `glob` / `task`），以及一节验证底线。
> 上游的 `disable-model-invocation` 在这里没有对应物——每个技能都可以通过 `skill` 工具发现，
> 所以直接去掉，而不做模拟。


# 练习脚手架

创建能通过 `pnpm ai-hero-cli internal lint` 的练习目录结构，然后用 `git commit` 提交。

## 目录命名

- **小节**：`exercises/` 里的 `XX-section-name/`（例如 `01-retrieval-skill-building`）
- **练习**：小节里的 `XX.YY-exercise-name/`（例如 `01.03-retrieval-with-bm25`）
- 小节编号 = `XX`，练习编号 = `XX.YY`
- 名字用连字符小写（dash-case）

## 练习变体

每个练习至少要有下面这些子目录之一：

- `problem/` - 带 TODO 的学员工作区
- `solution/` - 参考实现
- `explainer/` - 概念材料，没有 TODO

搭桩时默认用 `explainer/`，除非计划另有规定。

## 必需文件

每个子目录（`problem/`、`solution/`、`explainer/`）都需要一个 `readme.md`，它要：

- **不为空**（必须有真实内容，哪怕只有一行标题也行）
- 没有坏链

搭桩时，建一个只含标题和描述的极简 readme：

```md
# Exercise Title

Description here
```

如果子目录里有代码，它还需要一个 `main.ts`（超过 1 行）。不过搭桩阶段，只有 readme 的练习是可以的。

## 工作流

1. **解析计划** —— 抽出小节名、练习名和变体类型
2. **创建目录** —— 每个路径 `mkdir -p`
3. **创建桩 readme** —— 每个变体目录一个带标题的 `readme.md`
4. **跑 lint** —— 用 `pnpm ai-hero-cli internal lint` 校验
5. **修掉所有错误** —— 反复迭代，直到 lint 通过

## Lint 规则概要

linter（`pnpm ai-hero-cli internal lint`）检查：

- 每个练习都有子目录（`problem/`、`solution/`、`explainer/`）
- `problem/`、`explainer/`、`explainer.1/` 至少存在一个
- 主目录里的 `readme.md` 存在且不为空
- 没有 `.gitkeep` 文件
- 没有 `speaker-notes.md` 文件
- readme 里没有坏链
- readme 里没有 `pnpm run exercise` 命令
- 每个子目录都需要 `main.ts`，除非只有 readme

## 移动与重命名练习

重新编号或移动练习时：

1. 用 `git mv`（不是 `mv`）重命名目录——这样能保住 git 历史
2. 更新数字前缀，维持顺序
3. 移动之后重跑 lint

例如：

```bash
git mv exercises/01-retrieval/01.03-embeddings exercises/01-retrieval/01.04-embeddings
```

## 示例：从计划搭桩

给定这样一份计划：

```
Section 05: Memory Skill Building
- 05.01 Introduction to Memory
- 05.02 Short-term Memory (explainer + problem + solution)
- 05.03 Long-term Memory
```

创建：

```bash
mkdir -p exercises/05-memory-skill-building/05.01-introduction-to-memory/explainer
mkdir -p exercises/05-memory-skill-building/05.02-short-term-memory/{explainer,problem,solution}
mkdir -p exercises/05-memory-skill-building/05.03-long-term-memory/explainer
```

然后创建 readme 桩：

```
exercises/05-memory-skill-building/05.01-introduction-to-memory/explainer/readme.md -> "# Introduction to Memory"
exercises/05-memory-skill-building/05.02-short-term-memory/explainer/readme.md -> "# Short-term Memory"
exercises/05-memory-skill-building/05.02-short-term-memory/problem/readme.md -> "# Short-term Memory"
exercises/05-memory-skill-building/05.02-short-term-memory/solution/readme.md -> "# Short-term Memory"
exercises/05-memory-skill-building/05.03-long-term-memory/explainer/readme.md -> "# Long-term Memory"
```

## 本仓库的底线

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
