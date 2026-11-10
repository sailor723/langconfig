---
name: To Questionnaire（转成问卷）
lang: zh
translated: machine
source: backend/skills/en-originals/to-questionnaire/SKILL.md
description: 把一件你自己答不完的事，转成一份交给别人填写的问卷。
tags:
- to
- questionnaire
- mattpocock
triggers:
- 当被要求把用户无法独自回答的事情转成一份**问卷**时
- 当答案必须由一个人异步填写一份 Markdown 文档给出时
allowed_tools:
- read_file
- grep
- glob
- write_file
- edit_file
author: mattpocock (MIT), adapted for LangConfig
version: '1.0'
---

## Instructions（指令）

> **来源说明。** 改编自 `mattpocock/skills → skills/productivity/to-questionnaire`（MIT，原样收录于
> `vendor/upstream-skills/mattpocock/skills/productivity/to-questionnaire/SKILL.md`）。
> 为本仓库所做的改动：frontmatter 字段（`tags` / `triggers` / `allowed_tools` / `author` /
> `version`）、路径约定（`docs/specs`、`docs/tickets`、`work/<scope>`）、工具名
> （`read_file` / `write_file` / `edit_file` / `bash` / `grep` / `glob` / `task`），以及一节验证底线。
> 上游的 `disable-model-invocation` 在这里没有对应物——每个技能都可以通过 `skill` 工具发现，
> 所以直接去掉，而不做模拟。


把用户无法独自回答的事情，转成一份**问卷**：一份 Markdown 文档，用户把它交给一个人异步填写，或者在一场会议里一起填写。接收方握着用户缺的知识；问卷要把它取出来。

**grill 的是“这一次发送”，不是主题。** 只就*发送*这件事访谈用户，因为它总是答得上来：给谁，以及需要拿回什么。文档里的问题随后对准**缺口**——接收方知道什么，而用户需要什么。


1. **这份问卷发给谁？** 用一轮问答问清接收方的角色、专长，以及与用户的关系。这决定了问卷的语气，以及它必须自带多少上下文。当你知道接收方是谁、他们知道哪些用户不知道的东西时，这一步就完成了。

2. **你需要拿回什么？** 用一轮问答问清用户独自解决不了、必须从这个人那里得到的具体决定或事实。当你手里有一份具体清单，说清用户走的时候必须能做什么、能定什么时，这一步就完成了。

3. **写这份问卷。** 针对第 1–2 步定下的那个缺口起草问题，遵循下面的文档结构。写到当前目录下的 `to-questionnaire-<slug>.md`（slug 取自主题），并报告路径。当文件存在、且用户在第 2 步点名的每一项都被一个问题覆盖时，这一步就完成了。

## 文档结构

把文档框成一份**发现式问卷**：用户缺上下文，接收方有上下文。问题按重要性从高到低排，因为异步意味着你可能只拿到一遍；一旦问题超过一小把，就用 `##` 标题按主题分组。用下面的模板来写。

<questionnaire-template>

# <问卷标题>

**目的：** 这份问卷为什么存在，以及压在它上面的是哪个决定。

**来自：** <用户>，**致：** <接收方>，**你的回答将被如何使用：** <它们会去哪里>

## 上下文

一段话，为一位不在用户脑子里的接收方做定位。够他答得好，不是一整页。

## 怎么回答

截止时间，以及大概要花多少力气。部分回答和“我不知道”都有用：不确定的地方标出来，不要跳过。

## <主题标题>

每个主题一个 `##` 区。每个区下面是它的问题，最重要的先。每个问题只装一个想法，绝不复合，正下方留一个作答位；只有在该问题可能被读歪、或可能招来随口一答的地方，才加一行*为什么这很重要*。

<question-example>
### 上线时系统预计要扛多少负载？

*为什么这很重要：它决定了我们是现在就为突发流量做容量，还是往后放。*

>
</question-example>

## 还有别的吗？

一个收尾的兜底问题：有没有我们没问、但我们应该知道的事？

</questionnaire-template>

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
