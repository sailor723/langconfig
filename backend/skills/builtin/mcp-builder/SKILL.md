---
name: "mcp-builder（MCP 服务器构建）"
lang: zh
translated: machine
source: backend/skills/en-originals/mcp-builder/SKILL.md
description: >-
  创建 Model Context Protocol（MCP）服务器的完整指南。构建 MCP 服务器、集成外部 API，
  或为 LLM 编写工具接口时使用。
tags: [mcp, api, typescript, python, tools, integration]
triggers:
  - "用户提到 MCP"
  - "用户提到 Model Context Protocol"
  - "用户想创建工具"
  - "用户提到服务器集成"
allowed-tools: [filesystem, shell, python]
author: LangConfig
---

你是一名 MCP 服务器开发专家。创建 MCP 服务器时，按下面这套四阶段流程走：

### 阶段 1：调研与规划

写代码之前，先彻底搞清楚这些：

1. **API 分析**
   - 完整读一遍目标 API 的文档
   - 确认认证方式（OAuth、API key、token）
   - 摸清速率限制与分页模式
   - 记下有没有 webhook 或实时特性

2. **工具设计原则**
   - 在覆盖全部端点与做专用工作流工具之间取得平衡
   - 用动作导向的命名：`get_`、`create_`、`update_`、`delete_`、`list_`、`search_`
   - 把相关操作按逻辑分组
   - 为智能体的灵活性设计，而不只是图人用着方便

3. **框架选型**
   - **TypeScript**（推荐）：SDK 支持更好，类型安全更强
   - **Python**：适合数据密集的集成，ML 工程师也熟悉

### 阶段 2：实现

#### TypeScript 项目结构
```
my-mcp-server/
├── src/
│   ├── index.ts          # Entry point
│   ├── tools/            # Tool implementations
│   │   ├── index.ts
│   │   └── [feature].ts
│   ├── types/            # Type definitions
│   └── utils/            # Helpers (auth, pagination)
├── package.json
└── tsconfig.json
```

#### 核心实现模式

**1. 用 Zod schema 定义工具：**
```typescript
import { z } from "zod";

const GetUserSchema = z.object({
  userId: z.string().describe("The unique user identifier"),
  includeDetails: z.boolean().optional().describe("Include extended profile")
});

server.tool(
  "get_user",
  "Retrieve user profile by ID",
  GetUserSchema,
  async ({ userId, includeDetails }) => {
    // Implementation
  }
);
```

**2. 错误处理：**
```typescript
try {
  const response = await api.request(endpoint);
  return { content: [{ type: "text", text: JSON.stringify(response) }] };
} catch (error) {
  if (error.status === 429) {
    return { content: [{ type: "text", text: "Rate limited. Retry in 60s." }] };
  }
  throw new McpError(ErrorCode.InternalError, error.message);
}
```

**3. 分页辅助函数：**
```typescript
async function* paginate<T>(fetcher: (cursor?: string) => Promise<PageResponse<T>>) {
  let cursor: string | undefined;
  do {
    const page = await fetcher(cursor);
    yield* page.items;
    cursor = page.nextCursor;
  } while (cursor);
}
```

**4. 工具注解：**
```typescript
server.tool("delete_resource", "Permanently delete a resource", schema, handler, {
  annotations: {
    destructiveHint: true,
    idempotentHint: false,
    readOnlyHint: false
  }
});
```

#### Python 项目结构
```
my-mcp-server/
├── src/
│   └── my_mcp_server/
│       ├── __init__.py
│       ├── server.py     # Main server
│       └── tools/        # Tool modules
├── pyproject.toml
└── README.md
```

**Python 工具定义：**
```python
from mcp.server import Server
from pydantic import BaseModel, Field

class GetUserInput(BaseModel):
    user_id: str = Field(description="The unique user identifier")

@server.tool()
async def get_user(input: GetUserInput) -> str:
    """Retrieve user profile by ID."""
    user = await api.get_user(input.user_id)
    return json.dumps(user)
```

### 阶段 3：测试与验证

1. **构建验证：**
   ```bash
   # TypeScript
   npm run build

   # Python
   python -m py_compile src/**/*.py
   ```

2. **MCP Inspector 测试：**
   ```bash
   npx @anthropic/mcp-inspector
   ```

3. **集成测试：**
   - 用合法输入逐个测每个工具
   - 测错误路径（非法 ID、认证失败）
   - 确认分页工作正常
   - 检查速率限制的处理

### 阶段 4：文档与评测

1. **README 要求：**
   - 清晰的安装说明
   - 环境变量的文档
   - 每个工具的用法示例
   - 故障排查一节

2. **评测问题：**
   造 10 个复杂、贴近真实的问题，用来检验 LLM 的效果：
   - 问题必须只读（不做变更）
   - 答案必须可核验
   - 覆盖不同的工具组合
   - 测边界情况
