---
name: "Triage（分诊）"
lang: zh
translated: machine
source: backend/skills/en-originals/triage/SKILL.md
description: >-
  推动工单与外部拉取请求走过一条由分诊角色组成的小状态机：分类、核实、必要时 grill，然后写出
  智能体可以直接开工的简报。
tags:
  - "triage"
  - "mattpocock"
triggers:
  - "当被要求把项目 `docs/tickets/` 里的工单推进一条由分诊角色组成的小状态机时"
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

> **来源说明。** 改编自 `mattpocock/skills → skills/engineering/triage`（MIT，原样收录于
> `vendor/upstream-skills/mattpocock/skills/engineering/triage/SKILL.md`）。
> 为本仓库所做的改动：frontmatter 字段（`tags` / `triggers` / `allowed_tools` / `author` /
> `version`）、路径约定（`docs/specs`、`docs/tickets`、`work/<scope>`）、工具名
> （`read_file` / `write_file` / `edit_file` / `bash` / `grep` / `glob` / `task`），以及一节验证底线。
> 上游的 `disable-model-invocation` 在这里没有对应物——每个技能都可以通过 `skill` 工具发现，
> 所以直接去掉，而不做模拟。


# 分诊

推动 `docs/tickets/` 里的工单，走完一条由若干分诊角色组成的小状态机。

如果本仓库把外部拉取请求也当作一种请求入口（见工单追踪器配置），分诊同样覆盖它们：**一个拉取请求就是带着代码的工单**，同一批角色、同一批状态、同一台机器，只有下文标注“对拉取请求而言”的几处差异。一个裸的 `#42` 按追踪器配置解析成工单还是拉取请求。

分诊期间投到 `docs/tickets/` 的每条评论或工单，**必须**以这段免责声明开头：

```
> *本内容由 AI 在分诊过程中生成。*
```

## 参考文档

- [AGENT-BRIEF.md](AGENT-BRIEF.md)：如何写出能长期存活的智能体简报
- [OUT-OF-SCOPE.md](OUT-OF-SCOPE.md)：`.out-of-scope/` 知识库如何运作

## 角色

两个**分类**角色：

- `bug`：某处坏了
- `enhancement`：新功能或改进

五个**状态**角色：

- `needs-triage`：等维护者评估
- `needs-info`：等报告人补充信息
- `ready-for-agent`：规格已完备，可以交给一个 AFK 智能体
- `ready-for-human`：需要人来实现
- `wontfix`：不会处理

对拉取请求而言，同一批状态是针对所附的代码来读的：`ready-for-agent` 表示已附上一份简报、该由智能体在 diff 上走下一步；`ready-for-human` 表示已准备好由人来合并。

每个分诊过的工单都应恰好带一个分类角色和一个状态角色。如果状态角色互相冲突，先标记出来并问维护者，再做别的事。

这些是规范的角色名。`docs/tickets/` 里实际使用的标签字符串可能不同。标签映射放在 `docs/tickets/` 里；如果工单上没有任何标签，先问清映射关系，再分诊任何东西。

状态流转：没有标签的工单通常先进 `needs-triage`；从那里再走向 `needs-info`、`ready-for-agent`、`ready-for-human` 或 `wontfix`。报告人一回复，`needs-info` 就回到 `needs-triage`。维护者随时可以覆盖；遇到看着异常的状态流转，先标记出来再问，不要往下走。

## 调用

维护者调用 `triage` 技能，用自然语言描述他们想要什么。理解这个请求并照做。例如：

- “把需要我关注的东西都列出来”
- “我们看看 #42”（工单或拉取请求）
- “把 #42 移到 ready-for-agent”
- “有什么已经可以交给智能体了？”

## 展示需要注意的事项

查询 `docs/tickets/`，按三个桶展示，最旧的排前面：

1. **无标签**：从未分诊过。
2. **`needs-triage`**：评估进行中。
3. **`needs-info`，且上次分诊笔记之后报告人有过动静**：需要重新评估。

当拉取请求在范围内时，把这些外部拉取请求也放进这几个桶，并给每行打上 `[PR]` 或 `[issue]` 标记。发现环节只暴露*外部*的拉取请求（追踪器配置定义了谁算外部），所以一位协作者正在进行的拉取请求不算分诊工作。这个过滤只用于发现；被点名的拉取请求无论作者是谁都要分诊。

给出数量，以及每一条的一行摘要。让维护者来挑。

## 分诊一张具体的工单或拉取请求

1. **收集上下文。** 读完整个工单或拉取请求（正文、评论、标签、作者、日期；拉取请求还要读 diff）。解析已有的分诊笔记，避免重复问已经解决的问题。用项目的领域术语表去探索代码库，尊重该领域的 ADR。对代码库跑两项检查：(a) **重复**：按领域概念（不只按请求里的措辞）搜一下所请求的行为是否已有实现，并报告你搜过哪里。找到了，这就是一个“已实现”的 `wontfix`（第 5 步）。(b) **曾被拒绝**：读 `.out-of-scope/*.md`，把任何与本次请求相似的文件摆出来。

2. **给建议。** 把你的分类与状态建议连同理由告诉维护者，另附一份与请求相关的简短代码库摘要（包括它是否已被实现）。等指示。

3. **核实那个声明。** 在 grill 之前，先确认那个声明站得住。对 bug，按报告人的步骤复现它。对拉取请求，确认 diff 做了它声称做的事：把代码取到本地，跑相关的测试或命令。报告发生了什么：已确认（带代码路径）、没站住，或细节不足（一个很强的 `needs-info` 信号）。一次被确认的核实，会让智能体简报强得多。

4. **grill（如果需要）。** 如果请求还需要推敲成形，调用 `skill` 工具两次，分别取“grilling”和“domain-modeling”，一轮问题一轮问题地 grill 到它成形，磨利领域术语，并在决定落地时同步更新 `GLOSSARY.md` / ADR。

5. **落定结果：**
   - `ready-for-agent`：投一条智能体简报评论（[AGENT-BRIEF.md](AGENT-BRIEF.md)）。
   - `ready-for-human`：结构与智能体简报相同，但要说明它为什么不能委派（判断性决定、外部访问、设计决定、人工测试）。
   - `needs-info`：投分诊笔记（模板见下）。
   - `wontfix` 的情况，关掉工单，评论取决于*为什么*：
     - **已实现**：这次改动在代码库里已经存在。指出它在哪；**不要**写进 `.out-of-scope/`（那个知识库是给*被拒绝*的请求用的，不是给做完了的）。
     - **拒绝（bug）**：给一段礼貌的解释，然后关掉。
     - **拒绝（enhancement）**：写进 `.out-of-scope/`，从评论里链过去，然后关掉（[OUT-OF-SCOPE.md](OUT-OF-SCOPE.md)）。
   - `needs-triage`：打上这个角色。若已有部分进展，评论可选。

## 快速改状态

如果维护者说“把 #42 移到 ready-for-agent”，相信他们，直接打上这个角色。先确认你打算做什么（角色变更、评论、关闭），然后动手。跳过 grill。如果在没有 grill 会话的情况下移到 `ready-for-agent`，问一句他们是否要写一份智能体简报。

## needs-info 模板

```markdown
## 分诊笔记

**到目前为止已经确定的事：**

- 要点 1
- 要点 2

**还需要你（@reporter）补充的：**

- 问题 1
- 问题 2
```

grill 期间解决掉的一切都记在“到目前为止已经确定的事”下面，这样工作不会丢。问题必须具体、可执行，不能写成“请提供更多信息”。

## 接续上一轮会话

如果工单或拉取请求上已有早先的分诊笔记，读它们，检查报告人是否回答了任何悬着的问题，并在继续之前给出更新后的整体画面。不要重复问已经解决的问题。

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
