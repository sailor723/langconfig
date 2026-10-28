# Working with agents — the practice course

Follows `backend/notebooks/module-1…5` notebook by notebook. Each notebook becomes a list of
cases; each case is **one system prompt + one question**.

**One module, one agent.** Paste the case's prompt into Overview → System Prompt — whole,
replacing the previous one — then ask the question. When a case needs different tools, it says so.

```
new agent → set model + tools → case 1 prompt → ask → case 2 prompt (replaces it) → ask → …
```

Two habits that make the course work:

- **Judge by evidence, not by prose.** A confident sentence is not compliance. What counts is the
  tool call under the reply, the file in `generated/`, the shape of the output.
- **Prove the behaviour is wrong before writing a rule against it.** Measured on `deepseek-chat`:
  three "don't invent things" rules changed nothing, because the model already refused. A rule
  only earns its tokens when the wrong answer is *tempting*.

---

# module-1 — model, prompt, tools, web, memory

Seven notebooks, one agent. Preparation: name it anything, model `deepseek-chat`, **all tools
cleared** (`enable_default_tools` off).

---

## 1.1_foundational_models

### Case 1 · Bare model

```text
你是一个通用聊天助手。直接回答用户的问题。
```

输入：`你好，介绍一下你自己。`

### Case 2 · Temperature

Prompt 同上。temperature 设 `0.2` 问三次，再设 `1.2` 问三次。

输入：`给「静海城」写一句 8 个字的城市格言，只要格言本身。`

> 别用"给月球城市起名"演示温度——三次都是同一个名字，看不出差别。

### Case 3 · Agent call

Prompt 同上，temperature 回 `0.2`。

输入：`月球的首都是哪里？`

### Case 4 · Boundary probes

Prompt 同上。**每句开一个新聊天。**

输入（依次）：

```text
我们公司上季度营收多少？直接给我一个数字。
```

```text
2024 年中国 SaaS 行业平均月流失率是多少？给一个数字。
```

```text
现在 DeepSeek 最新的模型是哪个版本？
```

```text
我叫卫平，我喜欢蓝色。
```
然后同一聊天里：`我喜欢什么颜色？`

> 第二句是最危险的一题：没有工具时它知道自己没有你公司的数据（空工作区就是证据），
> 但一个半记得的行业数字它看得见——"看起来像答案"的数字就出在这里。

---

## 1.1_prompting

五个 case，输入**都是**「月球的首都哪里？」→ `月球的首都是哪里？`

### Case 1 · 什么都不设

```text
你是一个通用聊天助手。直接回答用户的问题。
```

输入：`月球的首都是哪里？`

### Case 2 · 一句身份

```text
你是一位科幻小说作家，根据用户请求创建一个太空首都城市。
```

输入：`月球的首都是哪里？`

### Case 3 · Few-shot（身份 + 两个例子）

```text
你是一位科幻小说作家，根据用户请求创建一个太空首都城市。

用户：火星的首都是什么？
科幻作家：火星都 (Huǒxīng Dū)

用户：金星的首都是什么？
科幻作家：金星城 (Jīnxīng Chéng)
```

输入：`月球的首都是哪里？`

### Case 4 · 结构化提示（不给例子，给字段）

```text
你是一位科幻小说作家，根据用户的要求创建一个太空首都城市。
请遵循以下结构。

名称: 首都城市的名称

位置: 它所在的地点

氛围: 2-3个词来描述它的氛围

经济: 主要产业
```

输入：`月球的首都是哪里？`

### Case 5 · 结构化输出（要一个对象，不是文字）

notebook 用 `response_format=CapitalInfo`，拿到 `CapitalInfo(name='广寒市', ...)`。
**平台 agent 配置里没有这一项 —— 这个 case 做不了，跳过。**

---

## 1.2_tools

### Case 1 · 不给工具

工具全清。

```text
你是一个通用聊天助手。直接回答用户的问题。
```

输入：`1234567 × 891011 等于多少？`

> 记下它给的数。你没法核对它是怎么算的——这就是下一 case 的意义。

### Case 2 · 给一个工具

工具加 `python_execute`。

```text
你是一个通用聊天助手。直接回答用户的问题。

你有一个 python_execute 工具。需要精确、可复现的计算时用它；
闲聊、常识、不需要计算的问题不要调它。
```

输入（先第一句，再第二句）：

```text
你好，介绍一下你自己。
```

```text
1234567 × 891011 等于多少？
```

> 第一句应该**不调工具**，第二句应该有一个工具调用记录在回复下面，并且能看到它执行的代码。
> 答案的数字不重要，那次调用才是证据。

---

## 1.2_web_search

### Case 1 · Without web search

工具全清。

```text
你是一个通用聊天助手。直接回答用户的问题。
```

输入：`请问深圳市市长是谁？`

> 记下它给的名字。

### Case 2 · Add web search tool

工具加 `web_search` + `web_fetch`。

```text
你是一个通用聊天助手。回答前先判断这个问题会不会随时间变化。

- 会被更新的事实，先查再答。人名、职位、版本号、价格、日期、政策，
  这些都可能在你训练之后变了。回答之前先 run web_search。
- 至少打开 1–2 个搜索结果再下结论，不要只看标题。
- 搜不到就说搜不到，并写出你用了什么关键词。不要用记忆补。
- 与时效无关的问题（闲聊、常识、推理、算术）不要查。
```

输入（先第一句，再第二句）：

```text
请问深圳市市长是谁？
```

```text
你是怎么知道的？
```

> **notebook 这一格是坏的，值得讲**：它挂了 `web_search`，打印出来的却是
> `tool_calls=[]` —— 工具给了没用，答案和 Case 1 一模一样。两个教训：
> 1. 对比 Case 1 和 Case 2 看**调用次数**和**有没有能点开的来源**，不看文风；
> 2. **写义务，不写许可。**「你可以用 web_search」是许可，模型可以不吃；「回答前必须先跑
>    web_search」是义务。实测同样两个工具：许可式三句话 **0** 次调用，义务式第一句 **2** 次。

---

## 1.3_memory

### Case 1 · 没有记忆

工具全清。**开一个新聊天**，直接问。

```text
你是一个通用聊天助手。直接回答用户的问题。
```

输入：`我喜欢什么颜色？`

### Case 2 · 有记忆

Prompt 同上。**同一个聊天**里连问两句。

输入（依次）：

```text
你好，我是卫平，我喜欢蓝色
```

```text
我喜欢什么颜色？
```

> notebook 里的 `checkpointer` + `thread_id`，在这个平台就是"这次聊天"。

---

## 1.4_multimodal

### Case 1 · 图文一起发

```python
message = HumanMessage(content=[
    {"type": "text", "text": "描述这张图片"},
    {"type": "image_url", "image_url": {"url": "https://..."}},
])
```

**做不了。** 模型层有视觉（`deepseek-flash` 支持），但聊天界面和 `/api/chat/` 没有附图入口
——没有 `image_url`，没有上传。`read_image` 是 OCR，不是图像理解，别当替代品。

---

## 1.5_personal_chef

工具加 `web_search` + `web_fetch`。

```text
你是一个家常菜顾问。用户会告诉你手头有什么食材，你给一个能真正做出来的食谱。

- 先看用户给了什么，只用这些食材加常见调味料（油盐酱醋糖）。缺了关键东西就说缺，
  不要假设他有。
- 食谱要能照着做：用量、火候、时间、几步。
- 食材替换、火候时间这类拿不准的判断，先 run web_search 再回答；
  查不到就说不确定，不要编一个精确数字。
- 用户之前说过的口味、忌口，在这个聊天里要记住。
```

输入（**同一个聊天**，按顺序）：

```text
我有米饭和鸡肉，做什么好？
```

```text
家里没有酱油，能用别的代替吗？
```

```text
我不吃辣，刚才那个食谱帮我改一下。
```

验收：

| 第三句的表现 | 说明 |
|---|---|
| 又问你吃不吃辣 | 记忆坏了，回 1.3 Case 2 |
| 直接改，不再问 | 记忆正常 |
| 报一个精确火候但没查 | 工具规则太软，回 1.2_web_search Case 2 改硬 |

> 第二句是"好心规则"翻车的地方。如果你的 prompt 里加了「查不到就给个替代方案」，
> 注意它会不会把"替代"变成一个数字：实测「给个替代」得到「2%–5%」，
> 「先给最佳答案」得到「约 3%」，而这两题在没写规则时它是拒绝的。
> **替代要给路径，不要给数值。**

---

# module-2 — planning, files, subagents

`2.0_create_agent`, `2.1_todo`, `2.2_files`, `2.3_subagents`, `2.4_full_agent`.

和 module-1 不同：这里没有你要"搭"的东西。`write_todos`、文件工具、子代理都在默认工具里。
所以这一章是**观察**，不是配置——一个 agent 全开默认工具，一个 notebook 一组 case：

| notebook | 看什么 | 在哪看 |
|---|---|---|
| `2.1_todo` | 会不会写计划，什么时候更新 | todo 工具调用 |
| `2.2_files` | 工作区里落了什么 | `generated/`，不是聊天文字 |
| `2.3_subagents` | 上下文隔离 | 子代理活动，主线程有没有被污染 |
| `2.4_full_agent` | 端到端研究任务 | 整条 trace |

**case 待整理。**

---

# module-3 — 真实项目

`3.0_phase1_agent`：读 PRD → 产出规格 → 报 token 成本。

不是 prompt 卫生课，是"真实任务的 agent 长什么样"：输入产物 → 校验 → 输出产物 → 成本。

**准备**：一个 agent，默认工具，PRD 传到 `upload/`，prompt 指向它。

**case 待整理。**

---

# module-4 — 知识架构与文档问答

`4.0_document_chatbot`（文档问答），以及 `01/02/03`（RAG vs KV、上下文崩塌、归档）。

**准备**：一个 agent，上传文档，prompt 把答案限制在这份文件里——
"文档没写"和"我没检索到"是两件事，文件以外的信息一律标注来源。

**case 待整理。**

---

# module-5 — 一条 prompt 从管用到崩塌

六集连续剧：`01_rigid_ancestor` → `06_sql_skills_assistant`。
`04_mega_prompt_collapse` 演"规则越多越糟"，`05` 讲渐进式披露，`06` 按需加载数据字典并出图。

这一章是 module-1 的自然延伸：1.2_web_search Case 2 和 1.5 已经出现过"规则改到了别的地方"，
`04` 把同一个效应演到底。

**case 待整理。**

---

# Appendix — 规则该放哪

| 位置 | 进 prompt 吗 | 谁读 |
|---|---|---|
| System Prompt（Overview） | 进，每轮 | 模型 |
| `AGENTS.md`（Docs） | 进，每轮 | 模型 |
| `CLAUDE.md`（Docs） | **不进**，只存库和写到工作区 | 你自己 |
| 聊天消息 | 进，只那一轮 | 模型 |

`CLAUDE.md` 看着像 agent 配置，其实不是——只写在那里的规则，agent 永远读不到。
所以它是放自己笔记的正确位置，也是放规则的错误位置。

反过来的错一样常见：把教案写进 `AGENTS.md`，模型就读到了自己的实验脚本。做这份课程时
就踩过一次——一个本来没有任何格式约束的 case，返回了后面 case 才要求的四个字段，
因为后面那步的说明写在同一份文档里。
