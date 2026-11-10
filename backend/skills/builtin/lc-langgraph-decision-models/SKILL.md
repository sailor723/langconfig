---
name: "Langgraph Decision Models（LangGraph 决策模型）"
lang: zh
translated: machine
source: backend/skills/en-originals/lc-langgraph-decision-models/SKILL.md
description: >-
  当你要用决策模型（TypeSafe Jev、SemIf）而不是 LLM 来为 LangGraph 智能体做路由，或要审计一个既有智能体、
  找出那些只为产出一个路由决策而发起的 LLM 调用时，调用本技能。涵盖 langchain-typesafe 的 Noul/Choice/Score、
  答案的正确读法、阈值设计，以及 LangSmith Gateway 的接入。
tags:
  - "langgraph"
  - "decision"
  - "models"
  - "langchain-skills"
  - "skills"
  - "design"
triggers:
  - "被要求处理 <overview> 时"
allowed_tools:
  - "read_file"
  - "grep"
  - "glob"
  - "write_file"
  - "edit_file"
  - "bash"
  - "skill"
author: "langchain-skills (MIT), adapted for LangConfig"
version: "1.0"
---

> **来源说明。** 改编自 `langchain-ai/langchain-skills → config/skills/langgraph-decision-models`（MIT，原样收录于
> `vendor/upstream-skills/langchain-skills/skills/langgraph-decision-models/SKILL.md`）。
> 为本仓库所做的改动：frontmatter 字段（`tags` / `triggers` / `allowed_tools` / `author` /
> `version`）、路径约定（`docs/specs`、`docs/tickets`、`work/<scope>`）、工具名
> （`read_file` / `write_file` / `edit_file` / `bash` / `grep` / `glob` / `task`），以及一节验证底线。
> 上游的 `disable-model-invocation` 在这里没有对应物——每个技能都可以通过 `skill` 工具发现，
> 所以直接去掉，而不做模拟。

## Instructions（指令）

<overview>
**决策模型（decision model）**针对状态提出带类型的问题，返回概率而不是一段文字。它替代了那个常见做法：提示一个 LLM、解析它吐出的文本、再按结果分支。

- **`Noul(instructions=...)`** —— 二元问题，返回“是”的概率
- **`Choice(instructions=..., criteria={...})`** —— 选一个标签，返回完整分布加置信度
- **`Score(instructions=..., criteria=[...])`** —— 按有序的评分档打分，返回期望值加置信度

`TypeSafeClassifier` 是一个 LangChain `Runnable[ClassifierRequest, ClassifierResponse]`，所以它像任何其他可运行对象一样直接放进节点。一次请求最多共享 32 个问题，各问题独立作答——把它们组合起来是你代码的事。

**该动用它的时候**：某个节点生成文字，只是为了让你从中解析出一个决策——路由、分诊、过滤、护栏，或对一批数据逐项分类。

**不要**在节点输出本身就是成品（摘要、草稿、代码）时动用它，也不要在这项判断需要多步推理时动用它。决策模型做的是分类；它不思考。
</overview>

---

## Install and wire（安装与接入）

`langchain-typesafe` 仍是 alpha（`0.0.1a3`），`TypeSafeClassifier` 标着 `@beta`——请锁定版本，并预期它会变。

```bash
uv add langchain-typesafe
```

接入模型有三条路。分类器向 `{base_url}/v1/systemone` 发 POST，带上 `Authorization: Bearer {api_key}`，所以换服务商只是换构造参数：

<ex-wiring>
<python>
```python
import os
from langchain_typesafe import TypeSafeClassifier

# 1. TypeSafe directly (Jev). Reads TYPESAFE_API_KEY when api_key is omitted.
classifier = TypeSafeClassifier(model="jev-latest")

# 2. SemIf, hosted on the LangSmith Gateway. Note: LangSmith key, not a TypeSafe key.
classifier = TypeSafeClassifier(
    model="semif-qwen3.5-4b",
    api_key=os.environ["LANGSMITH_API_KEY"],
    base_url="https://gateway.smith.langchain.com",
)

# 3. Jev through the Gateway (BYOK). The `typesafe/` prefix routes to a
# TYPESAFE_API_KEY stored in LangSmith workspace secrets. Without that secret
# every `typesafe/*` id returns 424 Failed Dependency -- before the model name is
# even validated, so a 424 does not confirm the id is real.
classifier = TypeSafeClassifier(
    model="typesafe/jev-1.13.0",
    api_key=os.environ["LANGSMITH_API_KEY"],
    base_url="https://gateway.smith.langchain.com",
)
```
</python>
</ex-wiring>

---

## The conversion pattern（转换模式）

把关于一个页面／一个条目的所有问题放进**一次**请求，把带类型的响应放进状态，再让一个普通函数据此路由。路由就是普通的 Python——不碰网络也能测。

<ex-classify-and-route>
<python>
```python
from typing import TypedDict
from langchain_typesafe import ClassifierResponse, Noul, Score, TypeSafeClassifier
from langgraph.graph import StateGraph, START, END

QUESTIONS = {
    "relevant": Score(
        instructions="How relevant is this ticket to a billing problem?",
        criteria=["Unrelated.", "Possibly related.", "Directly about billing."],
    ),
    "angry": Noul(instructions="Is the customer expressing anger?"),
}

class State(TypedDict):
    text: str
    answers: ClassifierResponse
    route: str

classifier = TypeSafeClassifier(model="jev-latest")

def classify(state: State) -> dict:
    # One request, every question. They are answered independently.
    return {"answers": classifier.invoke(
        {"state": state["text"], "questions": QUESTIONS}
    )}

def route(state: State) -> str:
    a = state["answers"]
    if a.nouls["angry"].noul > 0.7:
        return "escalate"
    if a.scores["relevant"].score < 0.5:
        return "close"
    return "handle"
```
</python>
</ex-classify-and-route>

读答案：`response.nouls[id].noul`、`response.choices[id].choice`、`response.scores[id].score`。每个视图都以你给的问题 id 为键；`response.answers` 把它们全都装着。

---

## Three traps when reading answers（读答案时的三个坑）

这些坑造成的是静默的错误路由，而不是异常。

**1. `Score.score` 是期望值，不是档位。** 它是对评分档的概率加权平均，常常是个小数。`score == 0` 几乎永远不成立——一个“无关”的条目会落在 `0.07`，不是 `0`。永远拿它跟一个区间比。

```python
if a.scores["relevant"].score < 0.5:   # correct
if a.scores["relevant"].score == 0:    # WRONG -- nearly never true
```

**2. 置信度衡量的是分布形状，不是正确性。** 在 `Score` 上，置信度报告的是评分档分布有多*集中*。一个干净地落在两个档位之间的条目，置信度会很低，哪怕模型对它其实一清二楚。所以一条“只要 `confidence < X` 就升级”的一刀切规则，会把模型已经判定的条目也升级出去。只在模糊的中间地带用置信度设闸：

```python
if score < NOT_RELEVANT:                          # decisive -- trust it
    return "close"
if score < RELEVANT or confidence < MIN_CONF:     # ambiguous -- escalate
    return "human_review"
return "handle"
```

**3. 阈值不跨模型通用。** 校准是模型的一部分。同一套策略跑同一批条目，在 Jev、SemIf 和一个 LLM 适配器上会路由出不同结果。只要换模型就重新调阈值，并且把模型 id 固定住。

---

## Question wording dominates accuracy（问题措辞决定准确率）

问题问得松，得到的就是自信的错答案，而且没有任何阈值能救回来。用 `criteria` 说清每种结果的含义，包括什么*不该*算在内。

在一个实测案例里，“这是不是一份与律师之间的保密通信？”给一份例行财务备忘录打了 **0.798**。改写成点名真正的检验标准——由律师撰写或写给律师，并对财务与会计内容显式排除——同一页就落到 **0.005**，而一份真正受特权保护的文件稳在 **0.991**。

```python
Noul(
    instructions=(
        "Was this written by or to a lawyer, or does it convey a lawyer's legal "
        "advice? Answer no for ordinary business or accounting discussion, even "
        "when the subject is litigation-sensitive."
    ),
    criteria=NoulCriteria(
        true="A named attorney is author or recipient, or it relays legal advice.",
        false="Business or accounting content with no attorney involved.",
    ),
)
```

在责怪模型之前，先改写问题，再重测。

---

## Auditing an existing agent（审计一个既有智能体）

要找出决策模型该落在哪里，就在代码库里找下面这些信号——完整走查见 `references/conversion-playbook.md`。

| 信号 | 该找什么 |
|---|---|
| 先生成再解析 | 一次 LLM 调用的输出立刻被 regex、`json.loads` 或字符串匹配送进某个分支 |
| 提示出来的分类器 | 提示词里写着“从以下选项里选一个回答”“回答是或否”“按 1 到 5 打分” |
| 为省钱而抽样 | 注释或配置显示只检查前 N 个条目，因为全查太贵 |
| 脆弱的规则 | 用关键词表或正则代替语义判断 |
| 反复重读上下文 | 同一份文档为每个独立问题都重新发给模型一遍 |

最后两条最要紧：便宜的语义判断改变的是*你能建什么*，不只是账单。如果逐个条目评一遍变得负担得起，你会停止抽样哪些东西？

---

## Expectations（预期）

在一个 24 条目的批次上实测，LangGraph 图与路由策略完全相同，只换分类器：

| | 每条耗时 | tokens（6 条） | 备注 |
|---|---|---|---|
| Jev 1.13.0 | 0.27s | 3,648 in / 318 out | 会上报用量 |
| SemIf 4B | 0.49s | 未上报 | 托管在 Gateway 上 |
| Claude Sonnet 5 | 2.87s | 7,930 in / 864 out | 走结构化输出 |

各引擎在 6 个条目中的 4–5 个上路由一致；分歧集中在真正处于边界上的条目。请把这些当作形状、而不是基准——在你自己的工作负载上量。

**如果你要和 LLM 基线做对比**，用 `method="json_schema"`，这样对比才公平。LangChain 的 `with_structured_output` 默认是 `method="function_calling"`，它会给每个请求注入一份工具 schema——在同一个单字段探针上，是 556/35 tokens 对原生 `output_config.format` 路径的 228/12。

---

## Batching with Send（用 Send 批处理）

分类是逐条目且彼此独立的，所以用 `Send` 扇出，让每个条目各自路由。

<ex-fan-out>
<python>
```python
from langgraph.types import Send

def fan_out(state):
    return [Send("classify_item", {"text": t}) for t in state["items"]]

builder.add_conditional_edges(START, fan_out, ["classify_item"])
```
</python>
</ex-fan-out>

扇出掩盖了延迟，所以它最抬举慢的分类器：在上面那次运行里，Sonnet 靠并发拿到 8 倍提升，Jev 只有 1.4 倍——可先跑完的仍然是 Jev。比吞吐量，别比加速倍数。

---

## Related skills（相关技能）

- **langgraph-fundamentals** —— StateGraph、`Send`、`Command`、条件边
- **langgraph-human-in-the-loop** —— 上面那条升级分支用的 `interrupt()`
- **langchain-middleware** —— 当你需要的是 LLM、而不是分类器时，看结构化输出

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
