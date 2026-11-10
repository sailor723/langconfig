---
name: "Tdd（测试驱动开发）"
lang: zh
translated: machine
source: backend/skills/en-originals/tdd/SKILL.md
description: >-
  测试驱动开发。当用户想以测试先行的方式构建功能或修 bug、提到“red-green-refactor”，或想要集成测试时使用。
tags:
  - "tdd"
  - "mattpocock"
  - "testing"
  - "debugging"
triggers:
  - "用户想以测试先行的方式构建功能或修 bug、提到“red-green-refactor”，或想要集成测试"
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

> **来源说明。** 改编自 `mattpocock/skills → skills/engineering/tdd`（MIT，原样收录于
> `vendor/upstream-skills/mattpocock/skills/engineering/tdd/SKILL.md`）。
> 为本仓库所做的改动：frontmatter 字段（`tags` / `triggers` / `allowed_tools` / `author` /
> `version`）、路径约定（`docs/specs`、`docs/tickets`、`work/<scope>`）、工具名
> （`read_file` / `write_file` / `edit_file` / `bash` / `grep` / `glob` / `task`），以及一节验证底线。
> 上游的 `disable-model-invocation` 在这里没有对应物——每个技能都可以通过 `skill` 工具发现，
> 所以直接去掉，而不做模拟。

## Instructions（指令）

# 测试驱动开发

TDD 就是红 → 绿这个循环。这个技能是让那个循环产出值得留下的测试的参考：什么是好测试、测试放在哪、有哪些反模式，以及循环本身的规则。每一节在每个循环里都适用：在循环之前和循环之中都要查阅它们，不是等到之后。

探索代码库时，读 `GLOSSARY.md`（如果存在），让测试名和接口用词与项目的领域语言对齐；并尊重你正在触碰的区域里的 ADR。

## 什么样的测试算好测试

测试通过公开接口验证行为，而不是实现细节。代码可以整个换掉，测试不该动。好测试读起来像一份规格：“用户用有效的购物车可以结账”精确说出了存在哪种能力，而且它扛得住重构，因为它不关心内部结构。

例子见 [tests.md](tests.md)，mock 的守则见 [mocking.md](mocking.md)。

## 接缝：测试放在哪

**接缝（seam）**是你测试时所站的公开边界：你在那里观察行为，而不必伸手进去。测试活在接缝上，绝不针对内部。

**只在事先约定好的接缝上测试。** 写任何测试之前，先把待测的接缝写下来，并和用户确认。不在未确认的接缝上写测试。你不可能什么都测，所以事先谈定接缝，正是把测试精力落在关键路径和复杂逻辑上、而不是每个边角上的办法。

要问：“公开接口是什么，我们应该测哪些接缝？”给每个提议的接缝写一行备注，说明它抓得住什么、抓不住什么。

当这个接口本身的形状还有疑问时（模块有多深、接缝该在哪、接口该暴露什么），用 `skill` 工具阅读技能（id：`codebase-design`）取词汇。它是模块、接口、深度、接缝、适配器、杠杆和局部性这些术语的共享来源；它是一份用来查阅的参考，不是一次要跑的会话。

## 反模式

- **耦合实现**：mock 内部协作者、测私有方法，或透过侧信道验证（直接查数据库而不用接口）。症状是：你一重构测试就坏，而行为并没有变。
- **同义反复**：断言用和代码相同的方式把期望值重算一遍（`expect(add(a, b)).toBe(a + b)`、用同样方式手推出来的快照、把一个常量断言成等于它自己），于是它按构造就通过，永远不可能和代码不一致。期望值必须来自独立的真值来源：一个已知正确的字面量、一个算好的例子、规格。
- **横向切片**：先把所有测试写完，再写所有实现。批量测试验证的是*想象出来的*行为：你测的是东西的*形状*而不是面向用户的行为，测试对真实改动变得不敏感，而你在理解实现之前就把测试结构钉死了。改用**纵向切片**：一个测试 → 一段实现 → 重复；每个测试都是一颗**曳光弹**，回应上一个循环教会你的东西。

## 循环的规则

- **先红后绿。** 先写失败的测试，然后只写足够让它通过的那点代码。不要预判未来的测试，也不要加投机性的功能。
- **一次一片。** 每个循环：一个接缝、一个测试、一段最小实现。
- **重构不属于这个循环。** 它属于评审阶段（见 `code-review` 技能），不属于红 → 绿这段实现循环。

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
  （`deepagents`）包一层。动笔之前先决定这次改动属于哪一层——这就是 `ecosystem-primer` 规则——并优先选
  能胜任的最高层。
