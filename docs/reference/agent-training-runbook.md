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
