# 深度研究报告模板（含 agent 契约与实测）

> 参考实现（本地，只取模板与流程，**不搬行业/公司尽调那套**）：
>
> - ① `~/dev/Learn/langchain-ai/deepagents-quickstarts/deep_research` —— 通用研究，报告规范在这里
> - ② `~/dev/Learn/langchain-ai/deepagents-quickstarts/phase1_enterprise_research` —— 只作旁证（它是行业/公司版，本文不展开）
>
> 平台侧落地：**agent 327 `case-10-deep-research`**，下面模板与示例均来自它的真实产出。

---

## 一、报告模板（通用研究，直接用）

产出路径：`generated/research/<主题>/final_report.md`

```markdown
# <主题>：<一句话结论式标题>

## Introduction
为什么这个问题值得回答、口径与时间范围（1–2 段）。

## 共识前提
所有来源都同意的那 1–2 条底线事实（有分歧的不要混进来）。

## Approach A — <名称>
## Approach B — <名称>
## Approach C — <名称>
（一主题一节；每节：是什么 / 谁在推 / 关键数据 / 边界与代价）

## Side-by-side
对比表：维度 × 各方案（**表里每个单元格都要能追到来源**）。

## Where the schools actually disagree
分歧点，逐条写清"甲方说什么、乙方说什么、依据分别是什么"。

## Conclusion: how to choose
按顺序给判断规则（不是罗列优缺点）。

### Sources
[1] 标题: https://...
[2] 标题: https://...
```

**三种变体**（参考实现里的三种结构，按问题类型选一种）：

| 问题类型 | 结构 |
|---|---|
| **对比** | 引言 → A 概述 → B 概述 → 逐项对比 → 结论 |
| **清单/排名** | 直接列条目 + 每条解释，**不要引言** |
| **综述** | 概述 → 关键概念 1/2/3 → 结论 |

---

## 二、写作规则（这几条决定报告像不像专业报告）

1. **段落体为主**，不要通篇 bullet；结论先行。
2. **禁止自述与旁白**：不写"我发现/我研究/我先查一下/让我规划/需求已存档"。
3. **禁止 meta 说明**：不解释自己的搜索过程、不说"我的资料不完整"这种过程话术 —— 缺什么写在最后的"证据不足"里。
4. **数据必须带来源**：数字、日期、金额原样引用，不换算口径；找不到出处的判断，明确标成"推断"。
5. **长度**：正文 1.5–3k 字（对比类可到 4k）；超过就说明你在堆砌。
6. **语言**：跟随用户提问语言；指标/URL 保留原文。

---

## 三、引用规则

```text
正文：[1] [2] 紧跟结论
结尾：### Sources
[1] 标题: 完整 HTTP URL
[2] 标题: 完整 HTTP URL
```

- 每个**唯一 URL 只占一个编号**（多来源合并时统一重排）；
- 编号**从 1 开始连续、无跳号、无重复**；
- 没有 URL 的来源，写"（无原始链接，标注为次级来源）"，不要伪造；
- 同一结论有多个来源时，标 `[1][3]`，不要只标一个。

---

## 四、agent 怎么才能产出这种报告（契约，四条）

| 契约 | 具体写法 |
|---|---|
| **文件即交付物** | `write_todos` 计划 → `write_file` 存 `research_request.md` → 派活 → 汇总 → 写 `final_report.md` → `read_file` 回读校验 → 删 todos。**报告不进聊天** |
| **报告规范进 prompt** | 把本文第二节的 6 条写进系统提示词末尾（最后看的最管用） |
| **子代理回报 ≤500 字** | 详细材料写 `notes-<子主题>.md`，回报只给"3–5 条结论 + [n] + Sources"；**回报过长会被平台截断成 500 字预览**，主 agent 会误判资料不足而自己下场搜 |
| **引用在子代理里就编号** | 子代理的 `### Sources` 带完整 URL；主 agent 只做**统一重排**，不重新找来源 |

聊天回复只允许这个形状（报告本体在文件里）：

```markdown
**结论**
1. …（≤30 字，最多 5 条）

**报告**：`generated/research/<主题>/final_report.md`
**证据不足**：……（没有就写"无"）
```

---

## 五、实测样例（agent 327，真实产出）

问题：*Compare the main approaches to context engineering for AI agents in 2025.*
报告：103 行 / 13 个来源 / 40 处 `[n]` 引用。

```text
# Context Engineering for AI Agents in 2025: Comparing the Main Approaches
## Introduction
## The shared premise: context is a scarce attention budget
## Approach A — Just-in-time retrieval and offloading (RAG, tools, MCP)
## Approach B — Externalized memory: files, notes, and the agent as its own archivist
## Approach C — Compression: compaction, summarization, masking
## Approach D — Isolation: sub-agents, sandboxes, structured state
## Approach E — Cache-aware layout: KV-cache as the design constraint
## Approach F — Structured state and attention recitation
## Approach G — Long-context maximalism, and why it lost
## Side-by-side
## Where the schools actually disagree
## Conclusion: how to choose
### Sources        ← 13 条，全部带真实 URL（Anthropic / Manus / Chroma / Cognition / OpenAI …）
```

聊天侧（同一轮）输出的是 5 条结论 + 报告路径 + "证据不足"一段 —— 与第四节的形状一致。

**还没做到的**：聊天消息前段仍有过程旁白（"需求已存档""现在派 research-agent"）。原因是一轮 = 一条 assistant 消息，旁白和答复同体，平台层拆不开；报告本体不受影响。

---

## 六、验收清单（8 条，逐条可判）

- [ ] `generated/research/<主题>/research_request.md` 存在，内容是用户原话
- [ ] `final_report.md` 存在，且**标题是一句话结论**，不是"关于 X 的报告"
- [ ] 有"共识前提"和"分歧"两节 —— 只有罗列没有分歧的，多半没读原始来源
- [ ] `### Sources` 编号从 1 开始连续，每条带完整 URL，无重复编号
- [ ] 正文 `[n]` 只引用 Sources 里出现过的编号（无悬空引用）
- [ ] 每个数字都能在同一行找到 `[n]`
- [ ] 全文无"我发现/我研究/我先查一下"这类自述（`grep -n "我发现\|我研究\|我先查"`）
- [ ] 聊天回复 ≤8 行且有报告路径
