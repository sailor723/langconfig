---
name: "Writing Fragments（写作·片段）"
lang: zh
translated: machine
source: backend/skills/en-originals/writing-fragments/SKILL.md
description: >-
  写作·探索：开采原始片段，先不碰结构。
tags:
  - "writing"
  - "fragments"
  - "mattpocock"
triggers:
  - "要开采原始片段、先不碰结构时"
  - "还没想好结构，素材需要先过一遍时"
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

> **来源说明。** 改编自 `mattpocock/skills → skills/in-progress/writing-fragments`（MIT，原样收录于
> `vendor/upstream-skills/mattpocock/skills/in-progress/writing-fragments/SKILL.md`）。
> 为本仓库所做的改动：frontmatter 字段（`tags` / `triggers` / `allowed_tools` / `author` /
> `version`）、路径约定（`docs/specs`、`docs/tickets`、`work/<scope>`）、工具名
> （`read_file` / `write_file` / `edit_file` / `bash` / `grep` / `glob` / `task`），以及一节验证底线。
> 上游的 `disable-model-invocation` 在这里没有对应物——每个技能都可以通过 `skill` 工具发现，
> 所以直接去掉，不做仿真。


<what-to-do>

这是纯粹的**探索**（explore）：把"可能写成什么"的空间撑大，不向结构做任何承诺。承诺是*利用*（exploit）的事，是另一个技能的活。主持一场产出片段的追问会，就用户想写的任何东西不依不饶地追问。排阶段、列大纲、定文章结构，在这里都在范围之外。

片段从对话的任何一边冒出来，就追加到同一个 markdown 文件里。

用户没给出路径，就问一次文档存到哪儿，然后在这次会话余下时间里记住它。

从用户说的第一句话起就开始捕获片段，包括最初那条提示词。

第一次写入时，在顶部放一个 H1 作暂定标题（之后还能改），别的什么都不要：不要元数据、不要目录、不要日期。

</what-to-do>

<supporting-info>

## 什么是片段

片段是任何一段有可能活到最终文章里的文字。它必须*作者自己能读*（作者能看出它是什么意思），但不需要定义自己的术语，也不需要让一个毫无背景的读者看懂。门槛是"这是一段好文字吗？"，不是"这是一段自足的论证吗？"

片段彼此刻意不同质。可能是片段的东西，比如：

- 一句锋利的话，你想在某个地方派上用场，但还不知道在哪儿。
- 一个断言，带一行论证。
- 一则情景速写：发生过的一件事、一段代码、一个场景、一个类比。
- 半截想法："大概是 X 用起来像 Y 这样的意思，以后再理清楚。"
- 一段引文、一句对白、一句偶然听见的话。
- 一串相关的观察，靠手感凑在一起。
- 一句抱怨、一句自白、一个包袱。
- 一个**引导词**：一个紧凑的比喻或自造词，整篇东西可以挂在它上面（用一个词命名这个想法，就像 *tracer bullets*（曳光弹）或 *fog of war*（战争迷雾）命名了一整套模式）。

这些里面，引导词是最值钱的一块要落下的片段。它是**结构性的**（load-bearing）：在探索阶段把它命名对了，它后面会塑造结构、过渡和标题，在整个利用阶段一路分红。对话围着某个反复出现的想法打转时，就推着去为它造一个词。

小说家的日记就是范本：多年里没有结构的观察记录，后来被开采成原始素材。片段就是观察记录。

## 文件格式

```markdown
# Working title

A first fragment lives here.

It can be multiple paragraphs. It can include lists, code, quotes: whatever
shape the fragment naturally takes.

---

A second fragment.

---

> A quoted line that the user wants to keep around.

A reaction to it.

---

- A cluster of related observations
- That hang together by feel
- And want to be near each other
```

片段之间用一条水平分割线（`\n---\n`）隔开。正文里不放标题。不打标签。除了加入的先后顺序，不排别的顺序。

## 写作节奏

悄悄追加。不要为每一块片段都申请许可。顺口提一句你加了什么（"这条加上了"），但不要用保存对话框打断对话。

每次写之前：从磁盘重新读一遍文件。用户可能在你两轮之间改过、重排过、删过片段，所以要保住他们的改动。绝不覆盖文件；只追加（或者，用户要求时，在原处改某一块片段）。

用户随时可以说"把最后那条砍掉""那条改得更锋利些""那两条合并"。把这些当成头等指令。

</supporting-info>

## This repository's floor（本仓库的底线）

- **用真命令验证**，不靠肉眼：`./scripts/housekeeping_verify.sh`（守卫 + `tsc` + `vite build` + 一份文档库报告）。加 `--full-suite` 跑后端套件。
- **后端套件有 20 个既有失败。**"不比那个基线更差"才是诚实的判据；"测试是绿的"这句话在这里你说不出口。用 `pytest tests -q --ignore=tests/test_neo4j_document_enrichment.py --ignore=tests/test_pageindex_full_content_loader.py` 做对比，把 `FAILED` 行和记录的基线做 diff。
- **规格、工单和笔记都落在文件里**：`docs/specs/<slug>.md`、`docs/tickets/NNN-<slug>.md`、`work/<scope>/`。一条写在聊天消息里的裁决，下一轮就丢了。
- **生态层**：智能体代码是 LangGraph 运行时里的 LangChain（`create_agent`），通常外面套着一层 Deep Agents 骨架（`deepagents`）。动手之前先定下这处改动属于哪一层——`lc-ecosystem-primer` 规则——并优先选能干成这件事的最高层。
