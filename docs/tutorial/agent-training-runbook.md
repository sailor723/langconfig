# Agent 训练 · 跟随 LangChain 官方文档

> 依据三个页面（其余内容都是它们的延伸，不是另起一套说法）：
>
> | 页面 | 取什么 |
> |---|---|
> | [langchain/agents](https://docs.langchain.com/oss/python/langchain/agents) | agent 的定义、`create_agent` 三要素、harness 与中间件 |
> | [deepagents/overview](https://docs.langchain.com/oss/python/deepagents/overview) | deep agent 的定义、四类内置能力 |
> | [langchain/multi-agent](https://docs.langchain.com/oss/python/langchain/multi-agent) | subagents / handoffs / skills / router 四种编排 |
>
> 每个案例都在平台上真实搭过、跑过；表格里的数字是实测值，不是示意。

**全书三条线**

| 段落 | 讲什么 | 案例 |
|---|---|---|
| 第 1 类 · 能直接用的 agent | 从最小可用到业务可用 | 1 基础 · 2 全工具 · 3 文档问答 · 4 个人助理 · 5 售后客服 |
| 第 2 类 · 机制演示 | 一个机制一个最小例子 | HITL · 6 subagents · 7 handoffs · 8 skills · 9 router |
| 案例 10–12 · 重活 agent | 多轮研究、内容生产、数据分析 | 10 深度研究 · 11 内容创作 · 12 CSV/Excel 分析 |

## 目录

| 章节 |
|---|
| [第 1 类 · 能直接用的 agent（案例 1–5）](#第-1-类-能直接用的-agent-案例-1-5) |
| [案例 1 · 第一个 agent：三个参数就是一个能用的 agent（`case-1-basic-agent`，id 281）](#案例-1-第一个-agent-三个参数就是一个能用的-agent-case-1-basic-agent-id-281) |
| [案例 2 · 工具多到 27 个，还挑得对吗（`case-2-all-tools`，id 159）](#案例-2-工具多到-27-个-还挑得对吗-case-2-all-tools-id-159) |
| [案例 3 · 文档问答：上传附件 → 读 → 标来源（`case-3-doc-chat`，id 326）](#案例-3-文档问答-上传附件-读-标来源-case-3-doc-chat-id-326) |
| [案例 4 · 个人助理：supervisor + 两个专家（`case-4-assistant`，id 323）](#案例-4-个人助理-supervisor-两个专家-case-4-assistant-id-323) |
| [案例 5 · 售后客服：一个 agent 三步配置（`case-5-support`，id 325）](#案例-5-售后客服-一个-agent-三步配置-case-5-support-id-325) |
| [第 2 类 · 机制演示（机制一项 + 四个模式）](#第-2-类-机制演示-机制一项-四个模式) |
| [机制 · 改文件前要人批准（HITL，`acc-hitl`，id 321）](#机制-改文件前要人批准-hitl-acc-hitl-id-321) |
| [案例 6 · 主 agent 把专家当工具（`case-6-subagents`，id 301）](#案例-6-主-agent-把专家当工具-case-6-subagents-id-301) |
| [案例 7 · 把对话交给另一个角色（`case-7-handoff`，id 314）](#案例-7-把对话交给另一个角色-case-7-handoff-id-314) |
| [案例 8 · 需要时才加载知识（`case-8-skills`，id 319）](#案例-8-需要时才加载知识-case-8-skills-id-319) |
| [案例 9 · 分派台 + 专家并行 + 汇总（`case-9-router`，id 320）](#案例-9-分派台-专家并行-汇总-case-9-router-id-320) |
| [案例 10 · 深度研究：文件即交付物（`case-10-deep-research`，id 327）](#案例-10-深度研究-文件即交付物-case-10-deep-research-id-327) |
| [案例 11 · 内容创作：品牌语气 + 技能 + 研究子代理（`case-11-content-builder`，id 328）](#案例-11-内容创作-品牌语气-技能-研究子代理-case-11-content-builder-id-328) |
| [案例 12 · CSV / Excel 数据分析（`case-12-csv-chat`，id 329）](#案例-12-csv-excel-数据分析-case-12-csv-chat-id-329) |
| [附录 · 复建自检清单（照案例 4 复建一遍）](#附录-复建自检清单-照案例-4-复建一遍) |
## 0 · 先分清两个词：agent 和 deep agent

课上最常混的就是这两个词。先花两分钟说清，后面每个案例就都顺了。

### 0.1 agent 是什么

LangChain 官方的定义很短（[agents 页](https://docs.langchain.com/oss/python/langchain/agents)）：

> 一个 agent，就是**一个在循环里调用工具的模型**，直到把这件事做完。

循环本身很简单：模型想一想 → 调一个工具 → 看到结果 → 再想一想。模型不调工具了，就说明它答完了。

![agent = model + harness：model 在中间，四周是 system prompt、skills、memory、context、tools、subagents](../assets/agent-harness.svg)

循环外面还包着一层东西，官方叫 **harness**，中文可以理解成「装配」：
提示词、工具清单，以及任何能改变模型行为的中间件。`create_agent` 就是把这层装配开放成参数：

```python
from langchain.agents import create_agent

agent = create_agent(model="deepseek-flash", tools=tools, system_prompt="...")
```

**记住一件事就够了：循环是固定的，能改的是装配。** 想让它更强，无非三种做法——
多给工具、加中间件、把提示词写清楚。

### 0.2 deep agent 又是什么

deep agent 用的还是同一个循环，区别在于**装配已经提前装好了**
（[deepagents overview](https://docs.langchain.com/oss/python/deepagents/overview)）：

> 在 LangChain 和 LangGraph 之上，直接内置了计划、虚拟文件系统、子代理和长期记忆。

官方把这些能力分成四组。对上课来说，你只需要知道每组「给你什么」：

| 这组能力 | 你拿到什么 | 在平台上对应 |
|---|---|---|
| 执行环境 | 能读能写文件、能跑代码 | 工具注册表、工作区、文件系统中间件 |
| 上下文管理 | 技能、记忆（`AGENTS.md`）、摘要压缩 | 技能库、`MemoryMiddleware`、摘要中间件 |
| 任务分工 | 可以派子代理干活，也可以先列待办 | subagents、`todo_list` 中间件 |
| 人机协作 | 关键动作停下来等人批准 | HITL 中间件 |

有两个细节容易踩：**列待办（计划）从 v0.7 起要自己挂**，不是默认就有；
**子代理是一次性的**，派出去、拿回一份报告就结束，不能来回对话。

### 0.3 两者的差别（上课就讲这张表）

| | agent | deep agent |
|---|---|---|
| 循环 | 一样 | 一样（内部仍调 `create_agent`） |
| 提示词 | 你写的 + 平台自动补的规则 | 只认你写的那段 |
| 自带工具 | 你勾选的那些 | 另外自带读写文件、`glob`/`grep`、`task` 等 |
| 文件系统 | 有（工作区隔离） | 有，还能换存储后端、设权限 |
| 子代理 | 支持 | 支持，且能给子代理单独指定模型 |
| 待办计划 | 要手动挂中间件 | 同样要手动挂 |
| `AGENTS.md` | 不读进提示词 | 每次运行都读进提示词 |
| 技能 | 用 `skill` 工具按需加载 | 先自动编目，再按需读全文 |
| HITL / RAG / 结构化输出 | 平台中间件提供 | 能配，但默认不带 |

### 0.4 在平台上怎么选

每个 agent 面板上都有一个 `use_deepagents` 开关，默认是关的。**它决定装配怎么装，并不改变模型本身的能力。**

当前这台机器上：63 个 agent，41 个是普通 agent、22 个是 deep（案例 1–9 是普通，10–12 是 deep）。

两个提醒：

1. **改了开关要开新聊天。** 旧会话不会迁移，因为提示词和工具集都变了。
2. **deep agent 的工具箱不等于配置里勾的那些。** 读写文件、`ls`、`task` 是 SDK 自带的，
   在配置里看不到，但运行时确实有 —— 别以为它们在别的页面被关掉了。

# 第 1 类 · 能直接用的 agent（案例 1–5）

> 按"从最小到完整"排：基础 → 全工具 → 文档问答 → 个人助理 → 售后客服。
> 第 2 类是机制演示（HITL + 四个模式），用到时再查；案例 10–12 是三个重活 agent。

## 工作区约定：上传的文件和产出的文件，都留在 agent 自己的目录里

每个 agent 有一个自己的工作目录：

```
outputs/users/<用户>/agents/agent_<id>/           普通会话
outputs/users/<用户>/<vault>/agents/agent_<id>/   绑定了 vault 的会话
```

里面分四个文件夹，各放各的：

| 文件夹 | 放什么 |
|---|---|
| `upload/` | 用户上传的 CSV、Excel、PDF、图片 |
| `generated/` | agent 做出来的东西：报告、`.ics`、`.eml`、dashboard、数据库 |
| `skills/` | 这个 agent 自己的技能 |
| `other/` | 中间文件 |

**这条规矩一定要守住：上传和产出都必须落在工作区里。**
原因很实际 —— Files 面板就是按这个目录列文件的，放在别处，用户在界面上既看不见、也删不掉。

之前有两处没守住，现在都改了：

- **数据分析**（上传 CSV 自动出 dashboard）原来把数据库和 HTML 写进公共目录 `data/analysis_dbs/`，
  所以常有人问「我传的文件去哪了」。现在写进 `<工作区>/generated/analysis/`，同名覆盖。
- **Excel 上传**原来不在「复制进工作区」的名单里，agent 在自己的目录里根本看不到文件。
  `.xlsx`、`.xlsm`、`.xls` 已经补进去。

**想清空工作区**：在 Files 面板点右上角的 🗑，确认一次即可。
它会删掉 `upload/`、`generated/`、`other/`、`skills/` 里的文件，保留说明文档和目录结构，
同时把数据库里这份会话的文件记录一起清掉 —— 否则列表里还挂着旧文件名。

# 案例 1 · 第一个 agent：三个参数就是一个能用的 agent（`case-1-basic-agent`，id 281）

依据：[langchain/agents](https://docs.langchain.com/oss/python/langchain/agents)。

第 0 节讲过：agent 就是「模型在循环里调工具」，外面包一层装配。这一节就把那层装配填到最简 ——
**只填三个参数，看它能不能干活。**

![核心循环：request → model → action → tools → observation → model，直到给出结果](../assets/agent-loop.svg)

```python
from langchain.agents import create_agent

agent = create_agent(
    model="deepseek-flash",        # 用哪个模型
    tools=[weather, calculator],   # 手里有哪些工具
    system_prompt="You are a helpful assistant",   # 一句话说明它是谁
)
```

三个参数之外什么都不给，它就自己能跑了。想再加强，才需要动中间件。

## 这三个参数在平台上填在哪

打开 Agents → New Agent，三样东西分别落在三个地方（Temperature 记得填 `0`）：

| 代码里的参数 | 平台上填在哪 | 我们填什么 |
|---|---|---|
| `model=` | Overview → Model | `deepseek-flash` |
| `system_prompt=` | Prompt → System Prompt | `You are a helpful assistant` |
| `tools=` | Tools 页签 | 勾三个：`web_search`、`python_execute`、`pg_query`（写文件用的 `write_file` 平台自带，不用勾） |

保存后开新聊天，先发一句 `hi` 把开场白用掉，再问下面四个问题。

## 实测：四个例子

| 问 | 它挑了哪个工具 | 结果 | 用时 |
|---|---|---|---|
| 上海的天气如何 | `web_search` ×4 | 晴到多云，白天 24–25℃，夜间 15℃ | 8.1s |
| 1,234,567 乘以 891,011 等于多少？ | `python_execute` | 1,100,012,777,237 | 4.8s |
| 用 pg_query 查一下 deep_agent_templates 有多少个 agent | `pg_query` | 63 | 3.3s |
| 把这句话存成一份文档：标题《工具路由测试》 | `ls` → `write_file` | `generated/工具路由测试.md` | 9.1s |

## 两条要讲的判断

1. **挑哪个工具由工具描述决定，不由提示词列举决定。** 提示词只有 `You are a helpful assistant` 一句，
   没有一个字提工具，四个例子都挑对了 —— 这就是页面那句 *a model calling tools in a loop*。
2. **harness 只有三件东西就能工作**：模型、工具、一句提示词。后面所有案例都是在往这三样上叠中间件。

---

# 案例 2 · 工具多到 27 个，还挑得对吗（`case-2-all-tools`，id 159）

依据：**同案例 1 的 [agents 页](https://docs.langchain.com/oss/python/langchain/agents)**（工具也是 harness 的一部分）。

案例 1 只有 3 个工具。这一节把同一个问题推到 27 个工具：**工具一多，模型还会挑对吗？**

`case-2-all-tools`：`deepseek-flash`、Temperature `0`、**27 个工具**（`web_search`/`tavily_search`/`web_fetch`、
`pg_query`/`pg_list_tables`/`pg_describe_table`、`python_execute`/`sqlite_execute`、
`memory_store`/`memory_recall`、`think_tool`/`reasoning_chain`、`write_todos`/`read_todos`、
`bash`、`write_file`…），提示词是一份**中文能力清单**（"你可以搜索信息、查数据库、写文件…"）。

## 实测

| 问 | 它挑了 | 结果 | 用时 |
|---|---|---|---|
| `上海今天天气怎么样？` | `web_fetch` → `web_search` ×2 | 19℃ 实况 + 今日温度区间 | 11.5s |
| `把这句存成文件：hello world。` | `write_file` | `generated/hello_world.txt` | 6.1s |
| `用 pg_query 查一下 deep_agent_templates 有多少个 agent。` | `pg_query` | 69 | 5.9s |
| `上海今天天气怎么样？`（案例 1 的同题） | 案例 1：`web_search` ×4 | 同样的答案 | 8.1s |

## 两条要讲的判断

1. **工具数量不是主要矛盾，名字和描述才是。** 27 个工具里，模型按"名字 + 一句描述"挑，每次都挑到最具体的那一个
   （写文件用 `write_file`、查库用 `pg_query`、天气用 `web_search`）—— 和案例 1 的 3 工具表现一致。
2. **提示词里的能力清单是"索引"，不是"路由表"。** 中文那段只说了"你能干什么"，没有一条"天气 → 用 web_search"的规则；
   真正决定挑哪个的是工具自身描述。这也解释了为什么**加工具比加规则更省事**，以及为什么工具描述写得含糊会直接掉准确率。
3. 代价是**选错的空间变大、延迟变高**（同题 11.5s vs 8.1s）。「工具太多要不要拆」的答案在案例 4/9：
   拆成专家（subagents）或分派台（router）。

---

# 案例 3 · 文档问答：上传附件 → 读 → 标来源（`case-3-doc-chat`，id 326）

依据：**[knowledge/doc-chat 实现](https://docs.langchain.com/oss/python/langchain/tools)**（工具的读写与引用规则）+
平台自身的 `api/knowledge/doc_chat.py`（提示词规则来源）。

平台原本的「知识库对话」是**把整个文件夹的内容塞进提示词**（`api/knowledge/doc_chat.py`）。
这个案例把它做成一个 **normal agent**：不预载文档，改用工具按需读 —— 上传什么、读什么、答什么，且每条结论标来源。

`case-3-doc-chat`：`deepseek-flash`、温度 `0`、**只有 3 个只读工具**：`glob`（列附件）、`grep`（大文件里定位）、
`read_any_file`（文本 / PDF / 扫描件 / Word / PowerPoint / Excel 统一读取入口）。

## 三条规则（抄自 `doc_chat.py` 的 RULES）

| 参考实现 | agent 版 |
|---|---|
| 每条结论标 `[Source: filename.ext]` | 同样格式，去掉文件名前的 8 位存储前缀 |
| 开头声明读了多少文档 | `**[Documents loaded: N file(s)]**`（N = 本轮实际读的） |
| 读不到就明确说（原文 `The loaded documents do not contain information about …`） | 「读到的文档里没有关于 … 的信息」 |
| 数字/金额/日期原样引用，不换算口径 | 同 |
| 不许用自身知识补 | 同 |

预算：一轮最多读 3 个文件；长文件只读命中部分（doc_chat 的等价限制是 300 文件 / 1M 字符）。

## 实测（上传真文件，不是演示数据）

| 上传 | 问 | 工具 | 结果 |
|---|---|---|---|
| `星河项目交付说明.md`（322 B） | 项目编号和预算是多少 | `glob` → `read_any_file` | `XH-2026-014` / `人民币 128 万元`，各带 `[Source: 星河项目交付说明.md]` |
| `industry_analysis_report.pdf`（612 KB，11 页） | 这份 PDF 讲什么行业？2025 市场规模 | `read_any_file`（6s） | 全球眼镜行业；列出 6 家机构口径表，全部带来源 |
| 同上 | 有没有提到越南的监管要求？没有就说没有 | `grep` | **「读到的文档里没有关于越南监管要求的信息」** + 核对过程（监管章节只覆盖美/欧/中） |

**上传即开始**：附件上传后前端会替用户发一句"我已上传附件「X」"，agent 先回一行确认再读 ——
不需要用户再补一句"请读一下"。没有读文件工具的 agent 收到同样的话，会直接说明"缺什么工具"。

## 两条要讲的判断

1. **agent 版和面板版的差别是"按需读"而不是"全塞进去"。** 面板版一次把文件夹里能塞的都放进提示词，
   大库会顶满上下文；agent 版先 `glob`/`grep` 缩小范围，只读命中的 1–3 个文件，读不到就明说。
2. **"读不到"比"答得像"更重要。** 三条规则里最值钱的是那句缺席声明：它把"我不知道"从模型的礼貌变成了可验收的判据
   （我们的验收脚本就是按这句话断言的）。

---


# 案例 4 · 个人助理：supervisor + 两个专家（`case-4-assistant`，id 323）

教程：**[https://docs.langchain.com/oss/python/langchain/multi-agent/subagents-personal-assistant](https://docs.langchain.com/oss/python/langchain/multi-agent/subagents-personal-assistant)**

## Overview（页面原文 · 中文译文）

> supervisor 模式是一种多 agent 架构：一个中心的 **supervisor agent** 协调若干专职的
> **worker agent**。当任务需要几种不同类型的专业能力时，它最合适 —— 与其造一个要在多个领域里
> 挑工具的 agent，不如造几个各自专注的专家，由理解整体流程的 supervisor 来协调。
>
> 教程要搭的是一套个人助理系统，用一条真实的工作流来演示这套结构。系统协调两个
> **职责完全不同**的专家：
>
> - **calendar agent**：排期、查空闲、管理日程事件。
> - **email agent**：负责沟通、起草消息、发送通知。
>
> 还会引入 **human-in-the-loop review**，让人**批准 / 编辑 / 拒绝**动作（例如对外发邮件）。
>
> 从 `langgraph-supervisor` 迁移过来的，参考「Migrate from langgraph-supervisor」——
> 那里有 interrupt 与 resume 的前后对照。

## Why use a supervisor?（页面原文 · 中文译文）

> 多 agent 架构可以把**工具**切分给不同 worker，每个 worker 有自己的提示词或指令。
> 试想一个直接握着全部日历与邮件 API 的 agent：它要在**很多相似的**工具里挑、要记住每套 API
> 的确切格式、还要同时处理多个领域。**如果效果开始变差**，把相关工具与配套提示词拆成逻辑组
> 往往有帮助（一部分也是为了让后续迭代更好管理）。

## 结构：一共 3 个 agent（1 + 2）

教程把 worker 叫 subagent；**supervisor 自己也是一个 agent**。

```text
                supervisor                  ← 它自己也是一个 agent
                     │  只看得见「包装工具」
          ┌──────────┴──────────┐
   schedule_event            manage_email
          │                        │
   calendar agent              email agent      ← 两个 worker
   create_calendar_event       send_email
   get_available_time_slots
```

两条要点：

1. **supervisor 看不到 `create_calendar_event`** —— 故意的信息差：它只面对 2 个包装工具，选项少才不容易挑错。
2. **审批挂在外发那一层** —— `interrupt_on={"send_email": …}` 属于 email agent；挂到 supervisor 只能拦住“派活”。

## 教程的步骤

| 步骤                    | 教程做了什么                                                                                                                          |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| 1. 定义工具             | 三个 stub：`create_calendar_event`（要 ISO 时间）、`send_email`、`get_available_time_slots`                                     |
| 2. 建专家               | calendar agent（**把「下周二下午 2 点」解析成 ISO**）、email agent（推断收件人、写主题正文）                                    |
| 3. **包装成工具** | `schedule_event(request)`、`manage_email(request)` — **supervisor 只看到这两个高层工具，看不到 `create_calendar_event`** |
| 4. supervisor           | 按领域分派；一句话涉及两件事时，**一轮里同时调两个工具**                                                                        |
| 5. 两个例子             | ①「安排明天 9 点站会」→ 只调 `schedule_event`；②「下周二 2 点跟设计团队开会，并发邮件提醒」→ 同时调度两个                       |

## 平台上怎么还原

1. **建 agent**：名字 `case-4-assistant`，Model `deepseek-flash`，Temperature `0`。
2. **Tools 页签只勾 `Task (Subagent)`** —— supervisor 只该看到“派人”这一件事，具体 API 由专家自己拿。
3. **JSON 页签**贴两个专家（`interrupt_on` 写在 `email_expert` 身上，不是 supervisor 上 ——
   supervisor 的中间件只看得到 `task`，看不到专家手里的 `write_file`）：

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

4. **Prompt 页签**：`你是一个个人助理。日程问题交给 calendar_expert，邮件问题交给 email_expert；你自己不写文件、不算日期。一件事涉及两方时，分别派活再汇总。`

## 实测（`case-4-assistant`，id 323）

| 问 | 发生了什么 |
|---|---|
| `安排下周二下午 2 点跟 Alice 开 1 小时的会` | `task(calendar_expert)` → `ls` → `python_execute` 算日期 → `write_file` → `generated/与Alice开会.ics`；答「2026-11-03 周二 14:00–15:00」 |
| 同一句 + `然后给 alice@example.com 发封确认邮件` | 一轮两个 `task`；`email_expert` 写 `.eml` 前**打断** → 点批准 → `outbox/…eml` 出现 |

点聊天窗口右上角**日历图标**：11 月 3 日格子里是 `14:00 与 Alice 开会`，来源文件与 Files 面板一致；
面板底部写明「N 个日程的文件没写时区，时间按文件字面显示」—— 只读，不替模型编时区。

## 和教程的差异（要如实讲）

| 教程 | 平台 | 原因 |
|---|---|---|
| 三个 stub 工具 | `python_execute` 算 + `write_file` 存 `.ics` / `.eml`，**不新增工具** | 平台不鼓励为演示造 stub；副作用靠文件可观测 |
| 每个专家包成 1 个工具 | 用内置的 `task(description, subagent_type)` | 等价：supervisor 一样看不到专家的工具 |
| 真发信 / 真日历（SendGrid、Google Calendar） | 写文件 | 教程**自己也是 stub**；平台没有真通道 |
| `edit`（改参数再执行） | 只有批准 / 拒绝 | 改参数会触发重新规划，实测更乱 |

## 四个要讲的判断

1. **分层是为了“少选项”**：supervisor 只面对 1 个工具、每个专家只面对自己的 2 个 —— 选错的概率就下来了。
2. **信息差是设计出来的**：supervisor 不知道 `write_file`、也不知道 `.ics` 怎么写得出来；所以**约束要写在专家身上**。
3. **审批放在有副作用的那一层**：放 supervisor 只能拦住“派活”，拦不住“发信”。
4. **专家要有自己的中间件**：子代理原来既无 `interrupt_on` 也无文件系统，文件根本落不了盘（平台已修）。

---


# 案例 5 · 售后客服：一个 agent 三步配置（`case-5-support`，id 325）

教程：**<https://docs.langchain.com/oss/python/langchain/multi-agent/handoffs-customer-support>**

## Overview（页面原文 · 中文译文）

> 状态机模式描述的是这样一类工作流：agent 的行为随着任务走到不同状态而改变。本教程用**工具调用
> 动态改变同一个 agent 的配置** —— 按当前状态更换它可用的工具与指令 —— 来实现一个状态机。状态可以
> 来自多个来源：agent 过去的动作（工具调用）、外部状态（比如 API 返回），甚至最初的用户输入
> （比如先跑一个分类器判断意图）。
>
> 本教程要搭的是一个售后客服 agent，它会：
>
> - 先收集保修信息再往下走；
> - 把问题分成硬件或软件；
> - 给出解决方案，或升级给人工；
> - 在多轮对话里保持状态。
>
> 和 subagents 模式（把子代理当工具调用）不同，**状态机模式用的是一个 agent**，它的配置随流程推进
> 而改变。所谓“一步”，只是同一个 agent 的另一套配置（system prompt + 工具），由状态动态选中。

## 流程（页面那张图的文字版）

```text
客户报问题 → 在保？ ──是──→ 问题类型？ ──硬件──→ 保修维修流程
                │                        └─软件──→ 排查步骤
                └──否──→ 问题类型？ ──硬件──→ 升级人工（付费维修）
                                    └─软件──→ 排查步骤
```

## 结构：1 个 agent + 3 步配置

| 步骤 | 这一步看得到什么 | 什么时候进 |
|---|---|---|
| `warranty_collector` | `transfer_to_issue_classifier` | 一开始（`default_step`） |
| `issue_classifier` | `transfer_to_resolution_specialist` | 保修状态问清之后 |
| `resolution_specialist` | `write_file` + `transfer_to_warranty_collector` + `transfer_to_issue_classifier` | 硬件/软件判定之后 |

**顺序不是靠提示词自觉，是靠工具集**：第一步手里根本没有进方案的转移工具，所以它进不去。

## 教程的步骤（9 节压成 5 行）

| 教程 | 做了什么 |
|---|---|
| 1. 定义 state | `current_step` / `warranty_status` / `issue_type` |
| 2. 建工具 | `record_warranty_status(...)` 返回 `Command(update={..., "current_step": ...})` |
| 3–4. 每步配置 + 中间件 | 字典里存 `prompt` / `tools` / `requires`；中间件读 `current_step`，覆盖 prompt 与工具，缺字段就 `raise` |
| 5. 建 agent | `state_schema=SupportState`、`middleware=[apply_step_config]`、加 checkpointer |
| 6–9. 跑 4 轮 + 回退 | 保修 → 分类 → 方案；再加 `go_back_to_*` 让客户改错的信息 |

## 平台上怎么还原（1 个 agent + 1 段 middleware）

Agents → New Agent，名字 `case-5-support`，Model `deepseek-flash`，Temperature `0`；
Tools 页签只勾 `write_file`；JSON 页签贴：

```json
"middleware": [{
  "type": "handoff",
  "config": {
    "default_step": "warranty_collector",
    "steps": {
      "warranty_collector": {
        "system_prompt": "你是售后客服，当前阶段：保修确认。先打招呼，再问设备是否在保修期内，不要一次问多个问题。客户回答后调用 transfer_to_issue_classifier。",
        "tools": [],
        "transfers": [{"to": "issue_classifier", "description": "客户已说明是否在保修期内"}]
      },
      "issue_classifier": {
        "system_prompt": "你是售后客服，当前阶段：问题分类。先请客户说明问题怎么发生的（即使开头提过也要确认），再判断硬件还是软件，然后调用 transfer_to_resolution_specialist。保修状态在对话历史里，自己回看。",
        "tools": [],
        "transfers": [{"to": "resolution_specialist", "description": "已判定硬件/软件"}]
      },
      "resolution_specialist": {
        "system_prompt": "你是售后客服，当前阶段：解决方案。回答最多 5 行，细节写进文件。文件名用 generated/support/<Current time 的日期时间>-<类型>.md（不要用客户名）。软件→排查步骤；硬件+在保→保修维修；硬件+过保→升级人工（写明平台没有真实工单系统）。客户说信息有误就用 transfer_to_warranty_collector / transfer_to_issue_classifier 回去改。",
        "tools": ["write_file"],
        "transfers": [
          {"to": "warranty_collector", "description": "客户说保修信息有误"},
          {"to": "issue_classifier", "description": "客户说问题类型判断有误"}
        ]
      }
    }
  }
}]
```

## 实测（`case-5-support`，id 325）

| 轮 | 客户说 | 用了什么 | 结果 |
|---|---|---|---|
| 1 | `Hi, my phone screen is cracked` | 无工具 | 只问保修状态（进不去下一步） |
| 2 | `Yes, it's still under warranty` | `transfer_to_issue_classifier` | 换配置：问"屏幕怎么坏的" |
| 3 | `The screen is physically cracked from dropping it` | `transfer_to_resolution_specialist` + `write_file` | 换配置：给保修维修流程；`generated/support/2026-10-31T1324-保修维修.md` |
| 4 | `What should I do?` | 无工具 | 只补充操作步骤（不再复述整份方案） |
| 5 | `Actually I made a mistake - my device is out of warranty` | `transfer_to_warranty_collector` | **回退**到保修确认（教程第 9 节） |

三次 hop 都落库成 `handoff` 消息，顺序 `issue_classifier → resolution_specialist → warranty_collector`。

> **回退那一轮可能连跳两次**：客户在"其实过保了"这句话里已经给出了新答案，所以
> `warranty_collector` 收到后立刻又转给 `issue_classifier`（实测出现过 4 跳）。判据要写"能回到保修"，
> 不能写"最后一跳必须是保修" —— 否则复跑会假失败。

## 和教程的差异（要如实讲）

| 教程 | 平台 | 原因 |
|---|---|---|
| `warranty_status` / `issue_type` 存进 state，prompt 用 `{warranty_status}` 插值 | 没有：事实留在**对话历史**里，prompt 写"自己回看" | 平台没有可编辑的 state 字段 |
| `requires` 缺字段就 `raise` | 没有这道校验；顺序靠"这一步手里有哪些转移工具" | 同上，属于要新增的能力 |
| `record_warranty_status` 返回 `Command` 写 state | `transfer_to_*` 写 `handoff_to` | 机制同构：工具改状态、中间件换配置 |
| `provide_solution` / `escalate_to_human`（stub 返回字符串） | `write_file` 写 `generated/support/*.md` | 平台没有工单系统，"升级人工"只是文件 + 一句告知 |
| 第 8 节：用摘要中间件压历史 | 中间件页签可加 `summarization` | 等价 |

## 三个要讲的判断

1. **一个 agent 也能"变成好几个人"**：换的是配置（prompt + 工具），不是进程，也不是子代理。
2. **顺序由工具集约束，不是靠模型自觉**：第一步没有"进方案"的工具，它想跳也跳不过去。
3. **回退要显式给**：只在方案步给 `transfer_to_warranty_collector`，客户改错才有路可走；给多了就等于没有流程。

## 复建自检（5 条）

- [ ] 第 1 轮只问保修，**没有** hop —— 判据：工具记录为空、没有 `handoff` 消息
- [ ] 第 2 轮出现 `transfer_to_issue_classifier`，回答变成"问问题怎么发生的"
- [ ] 第 3 轮出现 `transfer_to_resolution_specialist` + `write_file`，Files 面板多出 `generated/support/…md`
- [ ] 第 5 轮说"其实过保了" → 出现 `transfer_to_warranty_collector`（回退成功）
- [ ] 反证：把 `resolution_specialist` 的两个 `transfers` 删掉 → 客户说"搞错了"时它只能解释，退不回去

---


# 第 2 类 · 机制演示（机制一项 + 四个模式）

> 这些章节各讲**一个机制**，用最小例子证明它成立；业务场景请看第 1 类的案例 4（用 subagents + HITL）
> 和案例 5（用 handoff 状态机）。

# 机制 · 改文件前要人批准（HITL，`acc-hitl`，id 321）

页面：**[https://docs.langchain.com/oss/python/concepts/human-in-the-loop](https://docs.langchain.com/oss/python/concepts/human-in-the-loop)**

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

| 步骤                                                              | 看到什么                                              |
| ----------------------------------------------------------------- | ----------------------------------------------------- |
| 发 `hi`，它自己 `cd … && ls -la … 2>/dev/null` 扫工作区     | **没有打断**（只读命令不批）                    |
| 发「用 bash 执行：`echo approved > …/generated/approved.txt`」 | 输入框变成审批卡，显示工具名和整条命令                |
| 点 **批准这一次**                                           | 命令执行，`approved.txt` 出现，内容是 `approved`  |
| 再点一次批准                                                      | **409**：没有待批的东西了（批准只对那一次有效） |
| 15 分钟不点                                                       | 按**拒绝**处理，并告诉模型“工具没执行”        |
| agent 配 `approval_policy: "never"`                             | 直接拒绝，不等人                                      |

## 两个必须讲的判断

1. **这是“人在环里”，不是“让模型小心点”。** 提示词里写“重要操作前先问我”，模型可以不听；
   中间件是**循环停下来**，等人。页面的四种决策里，平台只给 approve / reject 两个按钮 ——
   `edit`（改参数再执行）会让模型重新规划，实测批准后它常会再试一次。
2. **拦“调用”，不拦“工具”。** deep agent 用同一个 `bash` 干自己的活（扫目录、写临时文件）。
   按工具名拦，拦到的几乎都是它的簿记；所以要配谓词：只读命令放行、写文件只拦交付物
   （`other/`、`skills/` 里的不拦）。这就是 `InterruptOnConfig` 的 `when`。

> 每次决策都会在 `audit_logs` 留痕（`HitlApproval`）：谁批的、审的是哪些工具、什么决定。

---


# 案例 6 · 主 agent 把专家当工具（`case-6-subagents`，id 301）

页面：**[https://docs.langchain.com/oss/python/langchain/multi-agent/index](https://docs.langchain.com/oss/python/langchain/multi-agent/index)**、
**[https://docs.langchain.com/oss/python/langchain/multi-agent/subagents](https://docs.langchain.com/oss/python/langchain/multi-agent/subagents)**

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

## 实测（`case-6-subagents`，`deepseek-flash`，temperature 0）

问一句：**「上海今天的天气怎么样？另外算一下 1234567 乘以 891011。」**

| 顺序 | 发生了什么                                                                                          |
| ---- | --------------------------------------------------------------------------------------------------- |
| 1    | 主 agent 一轮里发出**两个** `task`：`weather_expert`（查天气）、`math_expert`（算乘法） |
| 2    | 子代理内部各自调用工具：`web_search` ×3、`python_execute` ×1                                  |
| 3    | 结果回到主 agent，主 agent 汇总成一条回答                                                           |
| 4    | 落库：`tool_calls` 5 条、`subagent_spawns` 2 条（`{subagent, task, status:"completed"}`）     |

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

| 实验                | 配置                                                                                     | 结果                                                                               |
| ------------------- | ---------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------- |
| ① 描述匹配         | `weather_expert`：「查询某个城市的实时天气」                                           | 委派给 `weather_expert` ✅                                                       |
| ② 描述改成无关     | 同一个子代理，描述改成「整理会议纪要并输出要点」                                         | **仍然委派给它** —— 没变                                                   |
| ③ 两个候选都说得通 | `data_expert`：「查询【实时】天气…」和 `archive_expert`：「查询【历史】气候统计…」 | 「现在气温多少」→ `data_expert`；「往年 10 月平均气温」→ `archive_expert` ✅ |

**结论要如实讲**：路由不是只看描述 —— 任务文本、子代理名字、以及**候选有几个**都在参与。
② 之所以没变，是因为只有两个候选、任务里又出现了“天气”这个词，模型顺着**名字**也能找对。
描述真正的威力在 ③：**当两个候选都说得通时，只有描述能把它们分开。**

> 这一组数据可以直接从 `chat_sessions.subagent_spawns` 读出来（谁被派了、派的是什么任务），
> 比看回答文本可靠。

---


# 案例 7 · 把对话交给另一个角色（`case-7-handoff`，id 314）

页面：**[https://docs.langchain.com/oss/python/langchain/multi-agent/index](https://docs.langchain.com/oss/python/langchain/multi-agent/index)**、
**[https://docs.langchain.com/oss/python/langchain/multi-agent/handoffs](https://docs.langchain.com/oss/python/langchain/multi-agent/handoffs)**

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

## 实测（`case-7-handoff`，三个角色，CLI 验收）

| 轮次 | 用户说              | 发生什么                                           | 谁回答                                         |
| ---- | ------------------- | -------------------------------------------------- | ---------------------------------------------- |
| 1    | 我有发票问题        | `transfer_to_support` → `transfer_to_finance` | **财务**（「你好，我是财务专员…」）     |
| 2    | 另外，我有 500 错误 | `transfer_to_support`                            | **售后**（「500 属于服务端内部错误…」） |

每跳都留下痕迹，且**刷新后仍在**：`session.messages` 里是一条

```json
{"role": "handoff", "to": "finance", "reason": "…", "content": "转交给「财务」 · …"}
```

聊天里渲染成琥珀色卡片：`转交给「finance」· 用户咨询发票开错如何处理…`

> **跳数是模型判断，不是契约**：同一个问题（"发票开错了怎么处理"）复跑会得到 1 跳
> （售后自己答）或 2 跳（`support → finance`）。所以判据只能写"至少一次转交 + 回答在最后一跳之后"，
> 写死"必须两跳"会假失败。

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


# 案例 8 · 需要时才加载知识（`case-8-skills`，id 319）

页面：**[https://docs.langchain.com/oss/python/langchain/multi-agent/skills](https://docs.langchain.com/oss/python/langchain/multi-agent/skills)**

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

## 实测（`case-8-skills`，只有 `skill` + `python_execute` 两个工具）

| 问题                                                   | 是否加载技能                                | 结果                   |
| ------------------------------------------------------ | ------------------------------------------- | ---------------------- |
| 帮我把这句话改得更简洁：今天天气不错                   | **0 次**                              | 直接改（7 字 → 5 字） |
| 帮我 review 这段 Python 代码：`def f(x): return x/0` | **`skill(skill_id="code-review")`** | 先加载技能，再作答     |

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


# 案例 9 · 分派台 + 专家并行 + 汇总（`case-9-router`，id 320）

页面：**[https://docs.langchain.com/oss/python/langchain/multi-agent/router](https://docs.langchain.com/oss/python/langchain/multi-agent/router)**

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

## 实测（`case-9-router`）

问：**「上海今天天气怎么样？顺便算一下 1280 的 15% 是多少。」**

| 观察点       | 实测                                                                                     |
| ------------ | ---------------------------------------------------------------------------------------- |
| 分派内容     | 一轮里发出**两个** `task`：`weather_desk`（查天气）、`math_desk`（算百分比） |
| 专家各自干活 | 子代理内部 `web_search` ×2、`python_execute` ×1                                    |
| 汇总         | 同一条回答里既有 `192` 也有上海 19.9℃ / 湿度 68%                                      |
| 记账         | `subagent_spawns` 2 条（两个都 completed）、`tool_calls` 5 条                        |

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


# 案例 10 · 深度研究：文件即交付物（`case-10-deep-research`，id 327）

依据：**[deepagents/deep-research](https://docs.langchain.com/oss/python/deepagents/deep-research)** + 本地 `deepagents-quickstarts/deep_research`。

| 项 | 值 |
|---|---|
| 类型 | **deep agent** |
| 结构 | orchestrator + **1 个** `research-agent` 子代理 + `todo_list` |
| 工具 | `tavily_search` / `web_fetch` / `think_tool` / `write_todos` / `read_todos` |
| 契约 | 报告写进文件、子代理回报 ≤500 字、**每次搜索后必须 `think_tool`**、引用 `[n]` + `### Sources` 连续编号 |

## 实测（同一个问题，三轮改造）

*Compare the main approaches to context engineering for AI agents in 2025.*

| | 第一版 | 加严 prompt | **对齐 quickstart 契约** |
|---|---|---|---|
| 耗时 | 180s | 261s | 277s |
| 委派 | 1 | 2 | **1（默认单个 ✓）** |
| `think_tool` | 0 | 0 | **2 ✓** |
| `tavily_search` | 13 ❌ | 12 ❌ | **5 ✓**（上限 5） |
| `web_fetch` | 15 ❌ | 16 ❌ | **11**（上限 8，仍超） |
| 交付物 | 无 | 无 | **`generated/research/<主题>/{research_request.md, final_report.md}` ✓** |
| 引用 | 30 | 38 | **40 + Sources ✓** |

## 三条要讲的判断

完整报告模板见 `docs/tutorial/deep-research-agents.md`。

1. **超大工具结果会被平台截断**（换成 500 字预览）→ 主 agent 误判"资料不全"就自己下场搜（第一版 13 次搜索的由来）。
2. **预算只是 prompt 建议**：写"≤5 次"能把 13 压到 5，但 `web_fetch` 仍跑到 11（平台没有 `ToolCallLimit` 中间件）。
3. **一轮 = 一条消息**：过程旁白和最终答复同体，聊天里无法只留摘要。

# 案例 11 · 内容创作：品牌语气 + 技能 + 研究子代理（`case-11-content-builder`，id 328）

依据：**[deepagents/content-builder](https://docs.langchain.com/oss/python/deepagents/content-builder)**。

| 教程机制 | 平台落地 |
|---|---|
| `AGENTS.md` 品牌语气（always-on） | 存进 `agent_docs`，deep agent 由 `MemoryMiddleware` 读进系统提示词 |
| `skills/blog-post/SKILL.md`、`social-media` | 技能库新增两个技能，生产契约写在技能里 |
| `researcher` 子代理 | 独立 prompt，必须先研究并**把结果写到指定路径** |
| `generate_cover`（Gemini 出图） | **平台无文生图** → 改用 `write_file` 写 **SVG 封面**（1200×630 / 1080×1080） |

## 实测（教程原句：*Write a blog post about how AI agents are transforming software development*）

- 249.6s；工具：`write_file`×6、`task`×1、`tavily_search`×9、`web_fetch`×11、`think_tool`×1
- 产物：`generated/blogs/ai-agents-software-development/{post.md（139 行，7 个 H2/H3+CTA）, hero.svg}` + 研究笔记
- 正文 **24 处 `[来源: URL]`**，全部真实链接；研究笔记里写清了互相冲突的数据（Copilot 快 55.8% vs METR 慢 19% vs DORA 吞吐下降）

## 判断

1. **没有文生图也能做内容 agent**：SVG 封面让"必须有配图"这条契约仍然可验收。
2. **技能是契约载体**：产出路径、封面规格、自检清单都写在 SKILL.md 里，agent 换一次对话也不会忘。

# 案例 12 · CSV / Excel 数据分析（`case-12-csv-chat`，id 329）

依据：**[langchain/sql-agent](https://docs.langchain.com/oss/python/langchain/sql-agent)**。

| 文档的 4 个工具 | 平台的对应物 |
|---|---|
| `sql_db_list_tables()` | `sqlite_execute("SELECT name FROM sqlite_master WHERE type='table' …")` |
| `sql_db_schema(tables)` | `SELECT sql FROM sqlite_master WHERE name=…` + `SELECT * FROM "t" LIMIT 3` |
| `sql_db_query(query)` | `sqlite_execute(sql, db_path=…)`（出错把错误串回给模型） |
| `sql_db_query_checker(query)`（LLM 复检） | **写成执行前自检清单**（NULL/NOT IN、UNION ALL、BETWEEN 开闭、类型、引号、JOIN 列） |
| — | 多一步：**CSV / Excel → 建表**（`sqlite_load_csv`，文档假定库已存在） |

## 多 sheet Excel（用户要求的"和 CSV 一样"）

1. `glob("**/*", path="upload")` 找文件；
2. **`read_any_file("upload/<文件>")`** 读 —— Excel 返回按 sheet 分块的文本 `[Sheet: 汇总]` + `a | b | c` 行；
3. 每个 sheet 块当一份 CSV：`|` 换逗号 → `sqlite_load_csv(..., db_path="generated/<stem>.db")`，**所有 sheet 同一个库**；
4. 表名规则：**只能 ASCII**（`9月`→`m9`、`汇总`→`summary`），否则 `sqlite_load_csv` 直接报错重试。

## 示例：一个 3-sheet 工作簿的完整对话

比纯文本 agent 复杂的地方只有一处：**上传件不是文本，要先把"sheet"变成"表"**。
下面是一次真实运行，可以照着一字不差地复现。

**准备**（任何 3 sheet 的 xlsx 都行，这里用仓库里的样本）：

```
区域表：汇总 / 9月 / 10月
     汇总  = region, revenue, orders          （两月合计）
     9月   = region, month, revenue          （month = 2026-09）
     10月  = region, month, revenue          （month = 2026-10）
```

**第 1 问：摸清结构**

> 这个 Excel 有几个 sheet？分别建成了哪些表？

它做的事（工具轨迹）：

```
glob(upload/**) → read_any_file(upload/xxx.xlsx) → sqlite_load_csv ×3 → sqlite_execute ×2
```

回答（它会自己列出对照表）：

| Sheet | 表名 | 列 | 行数 |
|---|---|---|---|
| 汇总 | `summary` | region, revenue, orders | 3 |
| 9月 | `m9` | region, month, revenue | 3 |
| 10月 | `m10` | region, month, revenue | 3 |

**第 2 问：跨 sheet 汇总**

> 9月和10月的总收入各是多少？说明用的哪张表。

```sql
-- 它实际执行的查询（原文）
SELECT month, SUM(CAST(revenue AS REAL)) FROM m9 GROUP BY month
UNION ALL
SELECT month, SUM(CAST(revenue AS REAL)) FROM m10 GROUP BY month;
```

| 月份 | 总收入 |
|---|---:|
| 2026-09（`m9`） | 2,780,000 |
| 2026-10（`m10`） | 3,042,000 |
| 环比 | **+262,000（+9.42%）** |

**第 3 问：分组对比**

> 9月到10月按 region 看，谁增长最快？

| region | 9月 | 10月 | 环比 |
|---|---:|---:|---:|
| 华北 | 540,000 | 612,000 | **+13.33%** |
| 华东 | 1,280,000 | 1,410,000 | +10.16% |
| 华南 | 960,000 | 1,020,000 | +6.25% |

**第 4 问：交叉核对**

> 汇总表和两张月表对得上吗？

结论：汇总表 `summary` 的总收入 = 5,822,000，正是 `m9` + `m10` 之和 —— **两张月表与汇总表一致**。

## 它的完整配置（照抄即可复建）

```json
{
  "system_prompt": "（见上文『多 sheet Excel』的四步流程 + 自检清单 + 硬规则）",
  "model": "deepseek-flash",
  "temperature": 0.0,
  "use_deepagents": false,
  "native_tools": ["glob", "read_any_file", "read_file", "sqlite_load_csv", "sqlite_execute", "python_execute"],
  "skills": [],
  "subagents": [],
  "middleware": []
}
```

六个工具的分工，一个都不能少：

| 工具 | 只干一件事 |
|---|---|
| `glob` | 找 `upload/` 里有什么文件 |
| `read_any_file` | 把 CSV 读成文本；把 Excel 读成**按 sheet 分块的文本** |
| `read_file` | 读 CSV 原文（纯文本场景，比 read_any_file 轻） |
| `sqlite_load_csv` | 一块 CSV → 一张表（表名必须 ASCII，`db_path` 必须显式给） |
| `sqlite_execute` | 只读 SELECT；报错就把错误串回给模型 |
| `python_execute` | 只在要画图时用（matplotlib → base64） |

## 落盘产物（实测）

```
generated/<文件名stem>.db      16 KB
  ├─ summary(3行) / m9(3行) / m10(3行)     ← 一次建好，同名的重跑覆盖
└─ 全部列 TEXT（sqlite_load_csv 的行为），求和前必须 CAST
```

## 三个要讲的判断

1. **先看库再写 SQL**：`sqlite_master` 拿到表和结构、`LIMIT 3` 看样例，再写业务查询 —— 跳过这步必错。
2. **类型**：`sqlite_load_csv` 把所有列建成 TEXT，求和前必须 `CAST(x AS REAL)` —— agent 会自己发现并说明（实测它主动提示了这点）。
3. **中文 sheet 名**：`sqlite_load_csv` 表名只接受 `[A-Za-z_][A-Za-z0-9_]*`，所以中文 sheet 必须转写成 ASCII 表名（想保留中文得改走 `python_execute` + `to_sql`）。

# 附录 · 复建自检清单（照案例 4 复建一遍）

照着做，每步都有**可观察的判据**。任一步判据不成立，先修这一步再往下走 —— 后面的现象都会失真。

## A. 建 agent

- [ ] Agents → **New Agent**，名字填 `case-4-assistant`
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
- [ ] 判据：回复里出现 `case-4-assistant` 或你的 agent 名、以及工作区路径

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

## G. 看日程（右侧 Calendar）

- [ ] 点聊天窗口右上角的**日历图标** → 面板出现在右侧
- [ ] 判据 1：例 1 那天（例：11 月 3 日）格子里有 `14:00 与…开会`
- [ ] 判据 2：点那天，下方显示时间 / 参与者 / 来源文件 `generated/….ics`
- [ ] 判据 3：底部有「N 个日程的文件没写时区，时间按文件字面显示」（没有 TZID 时）
- [ ] 反证：删掉那个 `.ics`（或换一个没有日历的 agent）→ 刷新 → 面板显示“还没有日程”

## H. 反证（可选，但很值得做）

- [ ] 重跑例 2，这次点 **拒绝** → 判据：`outbox/` 里**没有**新文件，且答复里说明没发出去
- [ ] 把 `email_expert` 的 `interrupt_on` 删掉 → Save → 新聊天重跑 → 判据：**不再打断**
  （反向证明这次审批确实来自那一段配置）

## I. 常见失败对照

| 现象                          | 大概率原因                                                                              | 修法                                                            |
| ----------------------------- | --------------------------------------------------------------------------------------- | --------------------------------------------------------------- |
| 完全不派活，supervisor 自己答 | supervisor 的 system prompt 没写清“交给谁”，或 Tools 里没勾 `task`                  | 补 prompt / 勾 `task`                                         |
| 派了但**没有文件**      | 专家的 `tools` 里没写 `write_file`（或该环境没有工作区）                            | 在专家的 `tools` 里补 `write_file`                          |
| 例 2 **不打断**         | `interrupt_on` 写到了 agent 顶层 `middleware`，而不是专家对象里                     | 移到 `email_expert.intrrupt_on`（注意拼写：`interrupt_on`） |
| 打断后批准了但没文件          | `when: writes_deliverable` 把该路径当成了草稿（`other/`、`skills/` 不拦也不落地） | 让文件写到 `generated/`                                       |
| 刷新后转交/审批痕迹不见了     | 用的是旧会话                                                                            | 开新聊天重跑（历史记录已落库，但当前回合别复用旧上下文）        |
| 日历面板空白 | 这次会话没有写过 `.ics`，或 `.ics` 里没有 `DTSTART` | 看 Files 面板有没有 `.ics`；面板底部会列出“读不出日程”的文件名 |

> 整份清单跑完约 3–5 分钟。跑通后，这套配置就是“教程里的 supervisor + 专家 + 外发审批”
> 在本平台的完整对应物。
