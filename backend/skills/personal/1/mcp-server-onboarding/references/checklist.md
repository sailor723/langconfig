# MCP Server Onboarding — 逐条勾选清单

接入一个 MCP 服务器时，从上到下逐条打勾。任何一条不通过就停在那一步，不要跳到下一步。

## A. 传输方式

- [ ] A1 已确认传输方式：`http`（有 url）或 `stdio`（有 command + args）
- [ ] A2 http：url 从运行 agent 的机器上可访问（curl 得到响应，不是 404/连接拒绝）
- [ ] A3 stdio：command 在该机器上可执行，依赖已安装
- [ ] A4 不确定传输方式时，先按 http 试，连不通再换 stdio，且一次只改一处

## B. 写进 mcp_servers

- [ ] B1 服务器短名小写、连字符，短而有意义（`calendar`、`erp`）
- [ ] B2 已用 `pg_get_agent` 读过目标 agent 现有的 `mcp_servers`
- [ ] B3 本次只新增/修改了一个键，没有整体覆盖原有配置
- [ ] B4 目标 agent 是 public 或他人的 → 已先 `create_agent` 复制成私有副本

## C. 核对工具名

- [ ] C1 已执行 list_tools，并把原始输出里的工具名逐个抄下来
- [ ] C2 写进 prompt / 技能的每个工具名都能在 C1 清单里找到，没有凭记忆写的
- [ ] C3 工具名为空 → 已回到 A 步排查连接，未继续往下走
- [ ] C4 前缀/别名已按原始输出确认，没有猜测

## D. 写类工具审批

- [ ] D1 工具已分成读类（list/get/search/read）与写类（create/update/delete/send/post）
- [ ] D2 每个写类工具都挂了人工审批（`interrupt_on` 或等价 middleware）
- [ ] D3 审批按工具名逐个列出，没有宽泛通配把读类也拦住
- [ ] D4 system prompt 里写明「写操作先确认再执行」

## E. test_agent 验证

- [ ] E1 探针不是 "hi"，是针对本 skill 的读类 / 写类 / 错误路径三类用例
- [ ] E2 读类用例：工具序列里真的出现了那个 MCP 工具名
- [ ] E3 写类用例：agent 停下来要审批，没有直接改数据
- [ ] E4 错误路径：给不存在的 id/参数，agent 报错而不是编造结果
- [ ] E5 每条结果都写了 pass/fail + 证据（工具名、回答片段、耗时）
- [ ] E6 有 fail：每轮只改一处后复测；同一批 fail 两轮不变 → 停手报卡点并建议人工介入

## F. 交付

- [ ] F1 写了服务器名与传输方式
- [ ] F2 贴了 `mcp_servers` 的实际配置
- [ ] F3 贴了核对到的工具名清单，标出哪些挂了审批
- [ ] F4 贴了 test_agent 逐条 pass/fail + 证据
- [ ] F5 没跑通就写没跑通，没有用「已配置完成」代替证据
