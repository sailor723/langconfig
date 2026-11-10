---
name: "Domain Modeling（领域建模）"
lang: zh
translated: machine
source: backend/skills/en-originals/domain-modeling/SKILL.md
description: "构建并磨快一个项目的领域模型。讨论代码库术语、编写或编辑 GLOSSARY.md，或记录、编辑 ADR 时使用。"
tags:
  - "domain"
  - "modeling"
  - "mattpocock"
triggers:
  - "讨论代码库术语、编写或编辑术语表时"
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

> **来源说明。** 改编自 `mattpocock/skills → skills/engineering/domain-modeling`（MIT，原样收录于
> `vendor/upstream-skills/mattpocock/skills/engineering/domain-modeling/SKILL.md`）。
> 为本仓库所做的改动：frontmatter 字段（`tags` / `triggers` / `allowed_tools` / `author` /
> `version`）、路径约定（`docs/specs`、`docs/tickets`、`work/<scope>`）、工具名
> （`read_file` / `write_file` / `edit_file` / `bash` / `grep` / `glob` / `task`），以及一节验证底线。
> 上游的 `disable-model-invocation` 在这里没有对应物——每个技能都可以通过 `skill` 工具发现，
> 所以直接去掉，而不做模拟。


# 领域建模

设计的同时主动构建并磨快项目的领域模型。这是一门*主动*的纪律：挑战用词、造出边界情况场景，并且在术语和决定一旦成形的当下就把术语表与决定写下来。（仅仅为了取词去*读* `GLOSSARY.md` 不算本技能——那是一个任何技能都能顺手做的一行习惯。本技能用在你要改这个模型的时候，而不只是消费它的时候。）

## File structure（文件结构）

大多数仓库只有一个上下文：

```
/
├── GLOSSARY.md
├── docs/
│   └── adr/
│       ├── 0001-event-sourced-orders.md
│       └── 0002-postgres-for-write-model.md
└── src/
```

如果根目录下有一份 `GLOSSARY-MAP.md`，说明这个仓库有多个上下文。这张图指出每一个上下文住在哪里：

```
/
├── GLOSSARY-MAP.md
├── docs/
│   └── adr/                          ← system-wide decisions
├── src/
│   ├── ordering/
│   │   ├── GLOSSARY.md
│   │   └── docs/adr/                 ← context-specific decisions
│   └── billing/
│       ├── GLOSSARY.md
│       └── docs/adr/
```

文件要惰性创建：只在你确实有东西要写的时候才建。没有 `GLOSSARY.md` 时，等第一个术语敲定了再建一份。没有 `docs/adr/` 时，等第一个 ADR 需要了再建。

## During the session（会话进行中）

### 拿术语表来对质

用户用的词如果与 `GLOSSARY.md` 里既有的语言冲突，立刻指出来。"你的术语表把 'cancellation' 定义成 X，但你说的好像是 Y。到底是哪个？"

### 磨快含混的语言

用户用的词含混或多义时，提出一个精确的规范术语。"你说的是 'account'：你指的是 Customer 还是 User？这是两样不同的东西。"

### 讨论具体场景

讨论领域关系时，用具体场景去压测它。自己造场景，探到边界情况上，逼用户把概念之间的界限说准。

### 与代码交叉印证

用户说出某个东西是怎么运作的，就去查代码是否同意。发现矛盾就摊出来："你的代码是取消整张 Order，但你刚才说部分取消是可能的。哪个才对？"

### 就地更新 GLOSSARY.md

一个术语敲定时，当场更新 `GLOSSARY.md`。不要攒着批量处理：发生了就记下来。格式见 [GLOSSARY-FORMAT.md](./GLOSSARY-FORMAT.md)。

`GLOSSARY.md` 应当完全不含实现细节。不要把 `GLOSSARY.md` 当成规格、草稿纸，或实现决定的仓库。它就是一份术语表，仅此而已。

### 谨慎地提议 ADR

只有下面三条同时成立时，才提议写一份 ADR：

1. **难以撤回**：日后改主意的代价是实打实的
2. **脱离上下文会觉得奇怪**：将来的读者会纳闷"他们当初为什么这么做？"
3. **是真实取舍的结果**：确实存在别的选项，而你出于具体理由选了这一个

三条缺任何一条，就跳过 ADR。格式见 [ADR-FORMAT.md](./ADR-FORMAT.md)。

## This repository's floor（本仓库的底线）

- **用真实命令验证**，不要靠眼看：`./scripts/housekeeping_verify.sh`（守卫 + `tsc` + `vite build` +
  一份文档库报告）。后端测试套件加 `--full-suite`。
- **后端套件有 20 个既有的失败。**“不比那个基线更差”是诚实的判据；“测试是绿的”在这里不是一个你能做出的宣称。
  用
  `pytest tests -q --ignore=tests/test_neo4j_document_enrichment.py --ignore=tests/test_pageindex_full_content_loader.py`
  对照，并把 `FAILED` 行与记录的基线做 diff。
- **规格、工单和笔记活在文件里**：`docs/specs/<slug>.md`、`docs/tickets/NNN-<slug>.md`、`work/<scope>/`。
  写在聊天消息里的一句判词，下一轮就丢了。
- **生态层**：智能体代码是 LangGraph 运行时里的 LangChain（`create_agent`），通常由 Deep Agents 框架
  （`deepagents`）包一层。动笔之前先决定这次改动属于哪一层——这就是 `ecosystem-primer` 规则——并优先选
  能胜任的最高层。
