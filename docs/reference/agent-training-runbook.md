# Agent 训练 · 跟随 LangChain Agents 页

> 依据：**<https://docs.langchain.com/oss/python/langchain/agents>**
>
> 一句话：*a model calling tools in a loop until a task is complete, shaped by a harness
> of prompt, tools, and middleware.*

## 开场（页面原文）

> Agent 是一个**在循环里调用工具的模型**，直到给定任务完成为止。
> （*An agent is a model calling tools in a loop until a given task is complete.*）

![核心 agent 循环：request → model → action → tools → observation → model，直到模型给 result](assets/agent-loop.svg)

> Harness 是围绕这个循环的一切：**提示词、工具，以及任何塑造模型行为的中间件。**
> （*A harness is everything around that loop: the prompt, the tools, and any middleware
> that shapes the model's behavior.*）

> **Agent = Model + Harness**
> Harness 的职责：**在正确的时刻，把正确的上下文交给模型。**

## create_agent 就是一个可配置的 harness

> `create_agent` 高度可配置。最简单的用法是这样：

```python
from langchain.agents import create_agent

agent = create_agent(model="deepseek-flash", tools=tools)
```

> 在此基础上，**基础配置就是 `model=`、`tools=`、`system_prompt=` 三个参数**；
> 再往上要加能力，用中间件扩展 harness。

## 核心组件（Core components）

![agent = model + harness：model 在中心，周围是 system prompt、skills、memory、context、tools、subagents](assets/agent-harness.svg)

| 组件 | 页面原话 |
|---|---|
| **Model** | 传一个模型标识字符串（`"provider:model"`），或一个已初始化的模型实例。 |
| **Tools** | 传任何 Python 可调用对象、LangChain 工具或工具字典。 |
| **System prompt** | 塑造 agent 处理任务的方式。接受字符串或 `SystemMessage`。运行时要动态改，用中间件。 |
| **Structured output** | 用 `response_format=` 让 agent 返回**校验过的结构**。 |
| **Agent state** | 每个 agent 都用 `AgentState`（typed dictionary）管理执行上下文。内置字段是 `messages`（只追加）。要加自定义字段，继承它并用 `state_schema=` 传进去。 |

## 在平台上：模型 + 系统提示词 + 工具

三个位置填一次（Temperature 填 `0`）：

| 页面参数 | 平台上 | 填什么 |
|---|---|---|
| `model=` | Overview → Model | `deepseek-flash`（Temperature `0`） |
| `system_prompt=` | Prompt → System Prompt | `You are a helpful assistant` |
| `tools=` | Tools 页签 | 三个：`web_search`、`python_execute`、`pg_query`（写文件用的 `write_file` 平台自带，不用勾） |

## 四个例子

每个例子各开新聊天，先发一句 `hi`。

| 问 | 它用了 | 结果 | 用时 |
|---|---|---|---|
| 上海的天气如何 | `web_search` ×4 | 晴到多云，白天 24–25℃，夜间 15℃ | 8.1s |
| 1,234,567 乘以 891,011 等于多少？ | `python_execute` | 1,100,012,777,237 | 4.8s |
| 用 pg_query 查一下 deep_agent_templates 有多少个 agent | `pg_query` | 63 | 3.3s |
| 把这句话存成一份文档：标题《工具路由测试》 | `ls` → `write_file` | `generated/工具路由测试.md` | 9.1s |

提示词只有 `You are a helpful assistant` 一句，没有一个字提工具，四个例子它都自己挑对了 ——
**挑哪个由工具自己的描述决定**。这就是页面那句 *a model calling tools in a loop*。


---

# 案例 · 改文件前要人批准（Human-in-the-loop）

页面：**<https://docs.langchain.com/oss/python/concepts/human-in-the-loop>**

文档的写法是**中间件**，不是提示词：

```python
from langchain.agents import create_agent
from langchain.agents.middleware import HumanInTheLoopMiddleware
from langgraph.checkpoint.memory import InMemorySaver

agent = create_agent(
    model="gpt-5.5",
    tools=[write_file, execute_sql, read_data],
    middleware=[
        HumanInTheLoopMiddleware(
            interrupt_on={
                "write_file": True,                                   # 四种决策都允许
                "execute_sql": {"allowed_decisions": ["approve", "reject"]},
                "read_data": False,                                   # 显式放行
            },
            description_prefix="Tool execution pending approval",
        ),
    ],
    checkpointer=InMemorySaver(),   # 打断要靠它持久化；平台聊天本来就有
)
```

平台上就是 **Middleware 页签** → 勾工具 → 选“每条都批 / 只批会改东西的”，保存后**开新聊天**。

## 实测（deep agent，`bash` 设成 `bash_may_mutate`）

| 步骤 | 看到什么 |
|---|---|
| 发 `hi`，它自己 `cd … && ls -la … 2>/dev/null` 扫工作区 | **没有打断**（只读命令不批） |
| 发「用 bash 执行：`echo approved > …/generated/approved.txt`」 | 输入框变成审批卡，显示工具名和整条命令 |
| 点 **批准这一次** | 命令执行，`approved.txt` 出现，内容是 `approved` |
| 再点一次批准 | **409**：没有待批的东西了（批准只对那一次有效） |
| 15 分钟不点 | 按**拒绝**处理，并告诉模型“工具没执行” |
| agent 配 `approval_policy: "never"` | 直接拒绝，不等人 |

## 两个必须讲的判断

1. **这是“人在环里”，不是“让模型小心点”。** 提示词里写“重要操作前先问我”，模型可以不听；
   中间件是**循环停下来**，等人。页面的四种决策里，平台只给 approve / reject 两个按钮 ——
   `edit`（改参数再执行）会让模型重新规划，实测批准后它常会再试一次。
2. **拦“调用”，不拦“工具”。** deep agent 用同一个 `bash` 干自己的活（扫目录、写临时文件）。
   按工具名拦，拦到的几乎都是它的簿记；所以要配谓词：只读命令放行、写文件只拦交付物
   （`other/`、`skills/` 里的不拦）。这就是 `InterruptOnConfig` 的 `when`。

> 每次决策都会在 `audit_logs` 留痕（`HitlApproval`）：谁批的、审的是哪些工具、什么决定。

---

# 案例 · 主 agent 把专家当工具（Subagents）

页面：**<https://docs.langchain.com/oss/python/langchain/multi-agent/index>**、
**<https://docs.langchain.com/oss/python/langchain/multi-agent/subagents>**

文档原句：*a central main agent coordinates subagents by **calling them as tools**.*
主 agent 决定调谁、给什么输入、怎么合并结果；**所有路由都经过主 agent**。

```python
from langchain.tools import tool
from langchain.agents import create_agent

subagent = create_agent(model="google_genai:gemini-3.6-flash", tools=[...])

@tool("research", description="Research a topic and return findings")
def call_research_agent(query: str):
    result = subagent.invoke({"messages": [{"role": "user", "content": query}]})
    return result["messages"][-1].content

main_agent = create_agent(model="...", tools=[call_research_agent])
```

平台上是**单分发工具**（文档里的 *single dispatch tool*）：agent 的 JSON 加一段

```json
"subagents": [
  {"name": "weather_expert", "description": "查询某个城市的实时天气（温度、天气状况）。",
   "type": "dictionary", "system_prompt": "你是天气助手，用 web_search 查实时天气。",
   "tools": ["web_search"]},
  {"name": "math_expert", "description": "做精确的算术计算。",
   "type": "dictionary", "system_prompt": "你是计算助手，所有计算都用 python_execute。",
   "tools": ["python_execute"]}
]
```

Tools 页签勾上 **`task`**，保存后开新聊天。

## 实测（`case-2-subagents`，`deepseek-flash`，temperature 0）

问一句：**「上海今天的天气怎么样？另外算一下 1234567 乘以 891011。」**

| 顺序 | 发生了什么 |
|---|---|
| 1 | 主 agent 一轮里发出**两个** `task`：`weather_expert`（查天气）、`math_expert`（算乘法） |
| 2 | 子代理内部各自调用工具：`web_search` ×3、`python_execute` ×1 |
| 3 | 结果回到主 agent，主 agent 汇总成一条回答 |
| 4 | 落库：`tool_calls` 5 条、`subagent_spawns` 2 条（`{subagent, task, status:"completed"}`） |

## 三个必须讲的判断

1. **描述决定委派。** `task` 工具的描述就是子代理清单——
   `Available agents for delegation are: - weather_expert: … - math_expert: …`。
   模型照它挑人。这和工具路由、技能触发是**同一个机制**：写清“什么时候该找我”。
2. **上下文隔离是真的。** 让子代理在自己的 prompt 里复述“你收到的全部信息”，它答的是
   `我收到的信息：计算 1234567 × 891011` —— 它**不知道**父对话里说过的“我叫卫平、我住在上海”。
   所以要在子代理身上生效的约束（用中文、别用表情、输出格式）**必须写进子代理的 system prompt**，
   写在不进它上下文的地方就等于没写。
3. **子代理不直接面对用户。** 它只把结果交回主 agent；用户看到的是主 agent 那一句总结。
   页面把“直接交互”标成一星，就是这个意思。

> 同步执行：主 agent 会**等**子代理返回才继续（文档的 *Synchronous (default)*）。
> 文档里还有一种 *Asynchronous*（后台跑、不阻塞），这一版平台没有。

## 对照实验：改描述，委派会变吗？

同一个问题、同一套工具，只动子代理的 `description`，问三次：

| 实验 | 配置 | 结果 |
|---|---|---|
| ① 描述匹配 | `weather_expert`：「查询某个城市的实时天气」 | 委派给 `weather_expert` ✅ |
| ② 描述改成无关 | 同一个子代理，描述改成「整理会议纪要并输出要点」 | **仍然委派给它** —— 没变 |
| ③ 两个候选都说得通 | `data_expert`：「查询【实时】天气…」和 `archive_expert`：「查询【历史】气候统计…」 | 「现在气温多少」→ `data_expert`；「往年 10 月平均气温」→ `archive_expert` ✅ |

**结论要如实讲**：路由不是只看描述 —— 任务文本、子代理名字、以及**候选有几个**都在参与。
② 之所以没变，是因为只有两个候选、任务里又出现了“天气”这个词，模型顺着**名字**也能找对。
描述真正的威力在 ③：**当两个候选都说得通时，只有描述能把它们分开。**

> 这一组数据可以直接从 `chat_sessions.subagent_spawns` 读出来（谁被派了、派的是什么任务），
> 比看回答文本可靠。

---

# 案例 · 把对话交给另一个角色（Handoffs）

页面：**<https://docs.langchain.com/oss/python/langchain/multi-agent/index>**、
**<https://docs.langchain.com/oss/python/langchain/multi-agent/handoffs>**

文档原句：*Tool calls update a state variable that triggers routing or configuration
changes, switching agents or adjusting the current agent's tools and prompt.*

一个 handoff 工具**不改答案，改状态**：

```python
@tool
def transfer_to_specialist(runtime: ToolRuntime) -> Command:
    """Transfer to the specialist agent."""
    return Command(
        update={
            "messages": [ToolMessage(content="Transferred to specialist",
                                     tool_call_id=runtime.tool_call_id)],
            "current_step": "specialist",      # 触发行为变化
        }
    )
```

平台上是 **Middleware 页签 →「转交（handoff）」**：定义角色，再定义**谁 → 谁**。

```json
"middleware": [{"type": "handoff", "enabled": true, "config": {
  "default_step": "sales",
  "steps": {
    "sales":   {"label": "售前", "system_prompt": "…", "tools": ["web_search"],
                "transfers": [{"to": "support", "description": "技术故障交给售后"}]},
    "support": {"label": "售后", "system_prompt": "…", "tools": ["web_search","python_execute"],
                "transfers": [{"to": "finance", "description": "发票、账务问题转财务"}]},
    "finance": {"label": "财务", "system_prompt": "…", "tools": []}
  }}}]
```

**一条转交关系 = 一个自动生成的工具** `transfer_to_<目标>`（只有 `reason` 参数）。
不需要去 Tools 页签勾它们，也不允许手写 —— 目标写在工具名里，模型编不出不存在的角色。

## 实测（`case-3-handoff`，三个角色，CLI 验收）

| 轮次 | 用户说 | 发生什么 | 谁回答 |
|---|---|---|---|
| 1 | 我有发票问题 | `transfer_to_support` → `transfer_to_finance` | **财务**（「你好，我是财务专员…」）|
| 2 | 另外，我有 500 错误 | `transfer_to_support` | **售后**（「500 属于服务端内部错误…」）|

每跳都留下痕迹，且**刷新后仍在**：`session.messages` 里是一条

```json
{"role": "handoff", "to": "finance", "reason": "…", "content": "转交给「财务」 · …"}
```

聊天里渲染成琥珀色卡片：`转交给「finance」· 用户咨询发票开错如何处理…`

## 四个要讲的判断

1. **转交是中间件的活，不是提示词的活。** 提示词写“遇到技术问题请转给售后”，模型可以不听；
   中间件是**换提示词、换工具**，由状态决定，不靠模型自觉。
2. **目标必须写在工具里，不能写在参数里。** 我们第一版是 `handoff(to="…")`，模型填了个
   `technical_support`（不存在的角色）→ 静默失效。改成 `transfer_to_finance` 之后，
   这类错误在结构上不可能发生 —— 和 subagents 的“一个子代理一个工具”是同一个道理。
3. **转交即交棒。** 平台给每个角色自动附加规则：“不属于你的直接转，不要先回答”。
   否则会出现“财务先答 500、再转给售后、售后没开口”的一轮两个嘴。
4. **这和 Subagents 正相反 —— 上下文是共享的。** 子代理只拿到那一句 `description`；
   handoff 是**同一段对话**换个角色继续说，前面的历史都在。所以：
   **要隔离用 subagents，要接力用 handoffs。**

> 页面还给了第二种实现（多个 agent 子图 + `Command(goto=…, graph=Command.PARENT)`），
> 那是把每个角色做成图节点；平台这一版实现的是第一种（单 agent + 中间件），
> 对“少角色、强接力”的场景够用。

---

# 案例 · 需要时才加载知识（Skills）

页面：**<https://docs.langchain.com/oss/python/langchain/multi-agent/skills>**

文档原句：*Skills are primarily prompt-driven specializations that an agent can invoke
**on-demand** —— progressive disclosure of specialized prompts and domain knowledge.*

文档的实现是一个“加载技能”的工具：

```python
@tool
def load_skill(skill_name: str) -> str:
    """Load a specialized skill prompt.

    Available skills:
    - write_sql: SQL query writing expert
    - review_legal_doc: Legal document reviewer
    """
```

平台上是 **Skills 页签 + 内置 `skill` 工具**：技能内容存在库里，agent 需要时按 id 取。

## 实测（`case-4-skills`，只有 `skill` + `python_execute` 两个工具）

| 问题 | 是否加载技能 | 结果 |
|---|---|---|
| 帮我把这句话改得更简洁：今天天气不错 | **0 次** | 直接改（7 字 → 5 字） |
| 帮我 review 这段 Python 代码：`def f(x): return x/0` | **`skill(skill_id="code-review")`** | 先加载技能，再作答 |

> 修之前两次都**不加载**：`skill` 工具的说明里没有列任何技能 id，模型不知道有
> `code-review` 这个东西。把技能清单写进工具描述（名称 + 一句话）之后才会调 ——
> 和 `task` 列子代理、`transfer_to_*` 把目标写进工具名，是**同一个机制**。

## 三个要讲的判断

1. **技能不增加能力，只改变“什么时候知道”。** 内容不变，变的是它什么时候进入上下文 —— 这就是
   *progressive disclosure*（渐进披露）。
2. **触发靠描述，不靠“存在”。** 工具描述里不写“有哪些、什么时候用”，技能就等于不存在。
   这一条和工具路由（1.2）、子代理委派、转交目标**完全同源**。
3. **技能 vs 子代理**：技能是“给同一个 agent 加知识”，上下文不断、不隔离；子代理是“另开一个
   上下文干活再回来”。知识多而任务单一 → 技能；任务长且要隔离 → 子代理。

---

# 案例 · 分派台 + 专家并行 + 汇总（Router）

页面：**<https://docs.langchain.com/oss/python/langchain/multi-agent/router>**

文档原句：*A routing step classifies input and directs it to specialized agents …
Zero or more specialized agents are invoked in parallel. Results are synthesized
into a coherent response.*

文档的两种实现：`Command` 路由到**单个**专家；`Send` 做**并行 fan-out** 到多个专家，再汇总。

**平台上没有 `Send`**（没有图/节点层），能落地的是“**分派台 agent + 子代理 + 主 agent 汇总**”
—— 也就是用 Subagents 那个机制，按 router 的写法用：先分类、再一轮并行派出、最后合并。

```json
"system_prompt": "你是一个分派台。判断问题涉及哪些领域，把每一部分并行交给对应专家
                  （一次发出多个 task 调用），再把结果合并成一条回答。你自己不查资料、不算数。",
"native_tools": ["task"],
"subagents": [
  {"name": "weather_desk", "description": "查询某个城市的实时天气与短期预报。", "tools": ["web_search"]},
  {"name": "math_desk",    "description": "做精确计算（算术、单位换算、百分比）。", "tools": ["python_execute"]}
]
```

## 实测（`case-5-router`）

问：**「上海今天天气怎么样？顺便算一下 1280 的 15% 是多少。」**

| 观察点 | 实测 |
|---|---|
| 分派内容 | 一轮里发出**两个** `task`：`weather_desk`（查天气）、`math_desk`（算百分比） |
| 专家各自干活 | 子代理内部 `web_search` ×2、`python_execute` ×1 |
| 汇总 | 同一条回答里既有 `192` 也有上海 19.9℃ / 湿度 68% |
| 记账 | `subagent_spawns` 2 条（两个都 completed）、`tool_calls` 5 条 |

## 三个要讲的判断

1. **Router 和 Subagents 是同一个机制，两种用法。** 区别只在 prompt：Subagents 是“需要时才叫一个
   专家”，Router 是“先分类，再把每一部分都派出去”。平台的差别不是能力，是**分派策略**。
2. **分类是模型做的，不是确定性的。** 这是和“真 router”（一次分类 → 固定分支）最大的差异：
   同一句话，模型可能派 0 个、1 个或多个专家。要确定性分类，得把分类拿去做成独立的工具/节点。
3. **汇总质量取决于专家返回的形态。** 实测这条回答里数字和天气挨在一起，读起来不整齐 ——
   因为子代理各说各的。要让汇总好看，得**在子代理的 system prompt 里约定输出格式**，
   而不是在分派台的 prompt 里补救（分派台看不到子代理的内部过程）。

> 平台没有 `Send` 的多路 fan-out（那是图层的概念）。所以“并行”在这里指的是
> **一轮里多个 `task` 工具调用** —— 模型一次发出，框架并发执行；不是图上的并行分支。

---

# 案例 6 · 个人助理（Supervisor + 专家 + 外发审批）

教程：**<https://docs.langchain.com/oss/python/langchain/multi-agent/subagents-personal-assistant>**

## 教程在讲什么（照它的顺序）

> *The supervisor pattern is a multi-agent architecture where a central supervisor agent
> coordinates specialized worker agents.*

它建两个专家：**calendar agent**（排期、查空闲、建事件）和 **email agent**（起草、发送），
再由一个 **supervisor** 协调。教程还特意加入 **HITL**：外发邮件前由人**批准 / 编辑 / 拒绝**。

**为什么要把工具切开用 supervisor**（教程原话）：

> 一个 agent 如果同时握着日历和邮件两套 API，就要在**很多相似的**工具里挑、还要记住每套 API 的
> 格式、同时处理两个领域。"*If performance degrades, it may be helpful to separate related tools
> and associated prompts into logical groups.*"

教程的四个步骤：

| 步骤 | 教程做了什么 |
|---|---|
| 1. 定义工具 | 三个 stub：`create_calendar_event`（要 ISO 时间）、`send_email`、`get_available_time_slots` |
| 2. 建专家 | calendar agent（**把「下周二下午 2 点」解析成 ISO**）、email agent（推断收件人、写主题正文） |
| 3. **包装成工具** | `schedule_event(request)`、`manage_email(request)` — **supervisor 只看到这两个高层工具，看不到 `create_calendar_event`** |
| 4. supervisor | 按领域分派；一句话涉及两件事时，**一轮里同时调两个工具** |
| 5. 两个例子 | ①「安排明天 9 点站会」→ 只调 `schedule_event`；②「下周二 2 点跟设计团队开会，并发邮件提醒」→ 同时调度两个 |

## 平台上怎么还原（三步）

**① 建 agent**：Agents → New Agent → 名字 `case-6-assistant`，Model `deepseek-flash`，Temperature `0`。

**② Tools 页签**：**只勾 `Task (Subagent)`** —— supervisor 只该看到“派人”这一件事，
具体 API 由专家自己拿（这正是教程说的分层）。

**③ JSON 页签**：把两个专家写进 `subagents`：

```json
"subagents": [
  {
    "name": "calendar_expert",
    "description": "日程助手：把「下周二下午 2 点」这类说法换成具体时间，并生成日程文件（.ics）。",
    "type": "dictionary",
    "system_prompt": "你是日程助手。把自然语言时间解析成具体日期与时间（今天是 2026-10-31，周六）；需要算日期或时长时用 python_execute；确定后用 write_file 生成 generated/<标题>.ics（含 DTSTART/DTEND/SUMMARY）。最后用一句话确认安排了什么。",
    "tools": ["python_execute", "write_file"]
  },
  {
    "name": "email_expert",
    "description": "邮件助手：起草并发出邮件（写出 .eml 到 outbox）。",
    "type": "dictionary",
    "system_prompt": "你是邮件助手。根据要求写一封邮件，用 write_file 写到 generated/outbox/<收件人>-<主题>.eml，内容包含 To / Subject / 正文。发出前会有人工审批，你只需写好文件。",
    "tools": ["write_file"],
    "interrupt_on": {"write_file": {"allowed_decisions": ["approve", "reject"], "when": "writes_deliverable"}}
  }
]
```

`interrupt_on` 写在**专家身上**（不是 supervisor 上）：supervisor 的中间件只看得到 `task`，
看不到专家手里的 `write_file` —— 教程要的“外发前批准”只能在专家这一层拦。

**supervisor 的 system prompt**（Prompt 页签）：

```text
你是一个个人助理。日程问题交给 calendar_expert，邮件问题交给 email_expert；
你自己不写文件、不算日期。一个请求涉及两件事时，分别派给两个专家并汇总结果。
```

## 实测（`case-6-assistant`，id 323）

**例 1（教程的 Example 1：单域）** 问：`安排下周二下午 2 点跟 Alice 开 1 小时的会`

```
task(calendar_expert) → ls → python_execute(算日期) → write_file → read_file → edit_file
回答：「2026-11-03 周二 14:00–15:00，与 Alice 开会」
文件：generated/与Alice开会.ics        ← 日期换算由专家自己算的
```

**例 2（教程的 Example 2：跨域）** 问：`安排下周二下午 2 点跟 Alice 开 1 小时的会，然后给 alice@example.com 发封确认邮件`

```
task(calendar_expert) → task(email_expert) → …
interrupt: True
  待批：write_file('…/generated/outbox/alice@example.com-会议确认….eml')
点「批准这一次」→ 200 → outbox: ['alice@example.com-会议确认：11月3日（周二）14:00–15:00 UTC.eml']
```

## 和教程的差异（要如实讲）

| 教程 | 平台 | 原因 |
|---|---|---|
| 三个 stub 工具（`create_calendar_event` / `send_email` / `get_available_time_slots`） | **不新增工具**：日历用 `python_execute` 算 + `write_file` 存 `.ics`；邮件用 `write_file` 存 `.eml` | 平台不鼓励为了演示造 stub；“发出去”用“写进 outbox 目录”代表，副作用仍然可观测 |
| 每个专家包成**一个工具**（`schedule_event` / `manage_email`） | 用内置的 `task(description, subagent_type)` 单分发工具 | 机制等价：supervisor 一样只看得到“派人”，看不到专家的工具；差别只是工具的粒度 |
| API 真发送（SendGrid / Google Calendar） | 写文件 | 教程**自己也没接**：原文 *"In real applications, these would call actual APIs (Google Calendar, SendGrid, etc.). For this tutorial, you'll use stubs"*，三个工具里只有 `# Stub: In practice, this would call Google Calendar API…` 这样的注释，没有日历/邮箱界面。平台这边没有真发信、真日历通道，“发出去/排上了”就用写进 `generated/` 的文件代表 |
| `edit`（改参数后再执行） | 界面只给 批准 / 拒绝，`edit` 留 API | 改参数会让模型重新规划，实测反而更乱 |

## 四个要讲的判断

1. **分层是为了“少选项”，不是为了“多角色”。** supervisor 只面对 1 个工具（`task`），
   每个专家只面对自己那 2 个 —— 模型选错的概率下降。这和第 0 步“工具太多时路由变差”是同一件事。
2. **supervisor 与专家之间存在信息差。** 它不知道 `write_file` 存在、不知道 `.ics` 怎么写；
   它只知道“有个日程专家”。这种信息差是**设计出来的**，不是 bug —— 但也意味着
   **约束必须写在专家身上**（比如“时间用 UTC”“邮件要含主题”）。
3. **审批要放在“有副作用的那一层”。** 放 supervisor 只能拦“派活”，拦不到“发信”；
   放邮件专家才是教程要的“外发前批准”。
4. **专家需要自己的中间件。** 实测坑：子代理原来既没有 `interrupt_on` 也没有文件系统，
   让它写 `.ics` 只能退回 `python_execute`、文件根本没落盘。平台已修（专家现在有独立工作区
   与自己的审批策略）—— 讲课时可以拿它说明“中间件是按层配的，不是全局开关”。

---

# 附录 · 复建自检清单（案例 6 · 个人助理）

照着做，每步都有**可观察的判据**。任一步判据不成立，先修这一步再往下走 —— 后面的现象都会失真。

## A. 建 agent

- [ ] Agents → **New Agent**，名字填 `case-6-assistant`
- [ ] Overview → Model 选 `deepseek-flash`，Temperature 填 `0`
- [ ] Prompt 页签 → System Prompt 填：
      `你是一个个人助理。日程问题交给 calendar_expert，邮件问题交给 email_expert；你自己不写文件、不算日期。一个请求涉及两件事时，分别派给两个专家并汇总结果。`
- [ ] **Save**（判据：顶部出现保存成功，工具条 `ID:` 变成一个数字）

## B. 工具

- [ ] Tools 页签 → **只勾 `Task (Subagent)`**
- [ ] 判据：面板显示 **`1/N selected`**；勾其他工具会破坏这个案例的分层

## C. 两个专家

- [ ] JSON 页签 → 找到 `"subagents": []`，替换成文档里那段（calendar_expert / email_expert）
- [ ] 判据：`"subagents"` 里两个对象，各含 `name` / `description` / `system_prompt` / `tools`
- [ ] 判据：**`email_expert` 的 `interrupt_on` 在自己的对象里**（不是写在 agent 顶层的 `middleware`）
- [ ] **Save**

## D. 开新聊天（这一步最容易漏）

- [ ] 关掉编辑器的旧聊天，**开一个新聊天**
- [ ] 先发 `hi`（首轮会带平台开场白，别拿它当结果）
- [ ] 判据：回复里出现 `case-6-assistant` 或你的 agent 名、以及工作区路径

## E. 例 1 · 单域

- [ ] 发：`安排下周二下午 2 点跟 Alice 开 1 小时的会`
- [ ] 判据 1：工具记录里有 **`task`**，且子代理是 `calendar_expert`
- [ ] 判据 2：子代理内部出现 `python_execute`（算日期）
- [ ] 判据 3：出现 **`write_file`**，Files 面板里多出 `与…开会.ics`
- [ ] 判据 4：回复里有具体日期（例：2026-11-03）与 14:00–15:00

## F. 例 2 · 跨域 + 审批

- [ ] **再开一个新聊天** → `hi`
- [ ] 发：`安排下周二下午 2 点跟 Alice 开 1 小时的会，然后给 alice@example.com 发封确认邮件`
- [ ] 判据 1：一轮里出现**两个 `task`**（calendar_expert + email_expert）
- [ ] 判据 2：**输入框变成审批卡**，待批的是 `write_file`，路径含 `generated/outbox/`
- [ ] 判据 3：点 **批准这一次** → Files 面板出现 `outbox/…eml`
- [ ] 判据 4：再点一次批准 → **409**（批准只对那一次有效）

## G. 反证（可选，但很值得做）

- [ ] 重跑例 2，这次点 **拒绝** → 判据：`outbox/` 里**没有**新文件，且答复里说明没发出去
- [ ] 把 `email_expert` 的 `interrupt_on` 删掉 → Save → 新聊天重跑 → 判据：**不再打断**
      （反向证明这次审批确实来自那一段配置）

## H. 常见失败对照

| 现象 | 大概率原因 | 修法 |
|---|---|---|
| 完全不派活，supervisor 自己答 | supervisor 的 system prompt 没写清“交给谁”，或 Tools 里没勾 `task` | 补 prompt / 勾 `task` |
| 派了但**没有文件** | 专家的 `tools` 里没写 `write_file`（或该环境没有工作区） | 在专家的 `tools` 里补 `write_file` |
| 例 2 **不打断** | `interrupt_on` 写到了 agent 顶层 `middleware`，而不是专家对象里 | 移到 `email_expert.intrrupt_on`（注意拼写：`interrupt_on`） |
| 打断后批准了但没文件 | `when: writes_deliverable` 把该路径当成了草稿（`other/`、`skills/` 不拦也不落地） | 让文件写到 `generated/` |
| 刷新后转交/审批痕迹不见了 | 用的是旧会话 | 开新聊天重跑（历史记录已落库，但当前回合别复用旧上下文） |

> 整份清单跑完约 3–5 分钟。跑通后，这套配置就是“教程里的 supervisor + 专家 + 外发审批”
> 在本平台的完整对应物。
