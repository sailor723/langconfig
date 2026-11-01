---
name: mcp-server-onboarding
description: 在本平台接入一个新的 MCP 服务器：确认传输方式、写进 agent 配置的 mcp_servers、核对工具名、给写类工具挂审批、用 test_agent
  验证。用户要接入/更换 MCP 服务器，或现有 MCP 工具调不通（工具名报错、连接失败、工具列表为空）时读它。
version: 1.0.0
author: AI Generated
tags:
- mcp
- agent-config
- integration
- tooling
- platform
triggers:
- 用户要接入一个新的 MCP 服务器
- 用户要把 MCP 工具加给某个 agent
- 现有 MCP 工具调不通 / 工具名报错 / 连接失败
- mcp_servers 配置怎么写
- MCP 工具列表为空需要排查
allowed_tools:
- pg_get_agent
- pg_list_agents
- pg_list_custom_tools
- create_agent
- update_agent
- test_agent
- read_file
- write_file
---

## Instructions

# MCP Server Onboarding

目标：把一个 MCP 服务器安全地接到某个 agent 上，并证明工具真的能调通。按下面五步顺序走，不要跳步。

## 第 1 步：确认传输方式

向用户确认（问不到就用保守假设，并在回答里写明假设）：

- **http**：需要一个可访问的 `url`，例如 `http://127.0.0.1:3000`。这是本平台的主路径。
- **stdio**：需要 `command` + `args`（以及可选的 `env`）。stdio 服务必须在 agent 运行的机器上可执行。

判断规则：
- 服务是一个正在跑的 HTTP 进程 → http。
- 服务是一个本地可执行程序（`npx ...`、`python server.py`）→ stdio。
- 不确定就先按 http 试，连不通再换 stdio，一次只改一处。

## 第 2 步：写进 agent 配置的 mcp_servers

`mcp_servers` 是一个 map：键是服务器短名（小写、连字符），值是连接信息。

```json
{
  "mcp_servers": {
    "calendar": { "url": "http://127.0.0.1:3000" }
  }
}
```

规则：
- 键名会出现在工具名前缀里，起一个短而有意义的名字（`calendar`、`erp`）。
- 改现有 agent 前先用 `pg_get_agent` 读它当前的 `mcp_servers`，只加/改一个键，别整体覆盖。
- 要改 public / 别人的 agent，先 `create_agent` 复制一份私有副本再改。

## 第 3 步：list_tools 核对工具名

接入后立刻列工具，把 MCP 暴露的工具名逐个记下来：

- 工具名必须是**真实存在的**，不许凭记忆或推测写进 prompt 或技能里。
- 名字对不上时，先看前缀（通常带服务器短名）和 `list_tools` 的原始输出，不要猜别名。
- 工具列表为空 = 连接没成功，回到第 1 步查传输方式与 url/command，不要继续往下走。

## 第 4 步：给写类工具挂审批

区分读类和写类：

- **读类**（list / get / search / read）→ 可直接调用。
- **写类**（create / update / delete / send / post / 转账 / 改配置）→ 必须挂人工审批（`interrupt_on` 或等价的 middleware 配置），并写进 system prompt 明确"写操作先确认再执行"。

规则：
- 不要因为"方便"就把写类工具免审批。
- 审批范围按工具名逐个列，不要用宽泛通配把读类也拦住。

## 第 5 步：跑 test_agent 验证

写探针，不要用 "hi"。至少覆盖：

1. 一个读类调用：要求它列出/查询，检查工具序列里真的出现了那个 MCP 工具名。
2. 一个写类调用：要求它执行写操作，检查是否停下来要审批、没有直接改数据。
3. 一个错误路径：给一个不存在的 id/参数，检查它报错而不是编造结果。

判定时逐条写 pass/fail，附证据（工具名、回答片段、耗时）。有 fail 就 `update_agent` 每次只改一处再复测；同一批 fail 两轮不变 → 停手报卡在哪一条，建议人工介入。

## 输出契约

完成后给出：接入的服务器名与传输方式、`mcp_servers` 的实际配置、核对到的工具名清单（标出哪些挂了审批）、test_agent 逐条结果（pass/fail + 证据）。没跑通就写没跑通，不要用"已配置完成"代替证据。

## 支持文件（按需读取，不要整份预载）

- `references/checklist.md` —— 逐条勾选清单（A 传输方式 → F 交付，21 条）。接入过程中每一步都照它对一遍；任何一条不通过就停在那一步。
- `references/agent-mcp-config.json` —— 配置骨架（http 与 stdio 两种）。写 `mcp_servers` 前先复制它，别凭记忆拼字段。
