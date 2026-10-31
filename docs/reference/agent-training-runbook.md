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
