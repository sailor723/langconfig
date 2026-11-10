---
name: "webapp-testing（Web 应用测试）"
lang: zh
translated: machine
source: backend/skills/en-originals/webapp-testing/SKILL.md
description: >-
  使用 Playwright 及其他测试框架测试 Web 应用的专业指导。适用于测试 UI、自动化浏览器交互，
  或验证 Web 应用行为。
tags: [testing, playwright, selenium, e2e, browser, automation]
triggers:
  - "用户提到 Playwright"
  - "用户提到浏览器测试"
  - "用户提到 e2e 测试"
  - "用户提到 UI 测试"
  - "用户提到 selenium"
allowed-tools: [filesystem, shell, python]
author: LangConfig
---

你是一名 Web 应用测试专家，专精于用 Playwright 做浏览器自动化。要做全面测试时，请遵循下面这些准则。

### 测试策略决策树

**第 1 步：判断应用类型**
- 静态 HTML → 直接做简单的页面检查
- 动态 SPA → 先等网络空闲，再开始检查
- 服务端渲染 → 初始 HTML 与水合之后的状态都要看一遍

**第 2 步：选择测试方式**
```
Is the server running?
├── Yes → Use live server testing
│   └── Can you start it? → Use with_server.py helper
└── No → Static file testing or start server first
```

### Playwright 核心模式

#### 1. 基础测试结构（Python）
```python
from playwright.sync_api import sync_playwright

def test_login_flow():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()

        # Navigate and wait for load
        page.goto("http://localhost:3000")
        page.wait_for_load_state("networkidle")

        # Interact with elements
        page.fill('[data-testid="email"]', "user@example.com")
        page.fill('[data-testid="password"]', "password123")
        page.click('button[type="submit"]')

        # Assert result
        page.wait_for_url("**/dashboard")
        assert page.title() == "Dashboard"

        browser.close()
```

#### 2. 关键等待模式
```python
# ALWAYS wait for network idle on SPAs
page.wait_for_load_state("networkidle")

# Wait for specific element
page.wait_for_selector('[data-testid="loaded"]', state="visible")

# Wait for navigation
page.wait_for_url("**/success")

# Wait for network request
with page.expect_response("**/api/data") as response_info:
    page.click("#load-data")
response = response_info.value
```

#### 3. 选择器最佳实践
```python
# PREFERRED: Test IDs (most stable)
page.click('[data-testid="submit-btn"]')

# GOOD: Role-based selectors
page.click('role=button[name="Submit"]')

# GOOD: Text content
page.click('text=Submit Form')

# ACCEPTABLE: CSS selectors
page.click('.submit-button')

# AVOID: XPath (fragile)
# AVOID: nth-child selectors (fragile)
```

#### 4. 表单测试
```python
# Fill form fields
page.fill('#username', 'testuser')
page.fill('#email', 'test@example.com')

# Select dropdowns
page.select_option('#country', 'US')

# Checkboxes and radios
page.check('#agree-terms')
page.click('input[name="plan"][value="premium"]')

# File uploads
page.set_input_files('#avatar', 'path/to/image.png')

# Submit and verify
page.click('button[type="submit"]')
page.wait_for_selector('.success-message')
```

### 多服务测试

如果被测应用的前端和后端是分开跑的，就按下面这个方式测：

```python
# Helper script usage
# python scripts/with_server.py --help

# Start multiple servers
# python scripts/with_server.py \
#   --server "cd backend && python main.py" --port 8000 \
#   --server "cd frontend && npm run dev" --port 3000 \
#   -- python tests/e2e_test.py
```

### 视觉测试模式

```python
# Screenshot comparison
page.screenshot(path="screenshots/homepage.png")

# Full page screenshot
page.screenshot(path="full_page.png", full_page=True)

# Element screenshot
element = page.locator('.hero-section')
element.screenshot(path="hero.png")

# Compare with baseline (using pixelmatch or similar)
```

### 控制台与网络监控

```python
# Capture console logs
console_messages = []
page.on("console", lambda msg: console_messages.append(msg.text))

# Monitor network requests
requests = []
page.on("request", lambda req: requests.append(req.url))

# Check for errors
errors = []
page.on("pageerror", lambda err: errors.append(str(err)))

# After test
assert len(errors) == 0, f"Page errors: {errors}"
```

### 与 API 测试集成

```python
# Intercept and mock API calls
page.route("**/api/users", lambda route: route.fulfill(
    status=200,
    content_type="application/json",
    body='[{"id": 1, "name": "Test User"}]'
))

# Verify API calls were made
with page.expect_request("**/api/submit") as request_info:
    page.click("#submit")
request = request_info.value
assert request.method == "POST"
```

### 常见测试场景

1. **认证流程**
   - 用有效凭据和无效凭据分别测登录
   - 验证会话能不能保持下来
   - 测登出，以及登出后的会话清理
   - 检查访问受保护路由时的重定向

2. **表单校验**
   - 测必填字段的校验
   - 测格式校验（email、phone 这类输入）
   - 测最小长度 / 最大长度限制
   - 测表单提交成功和失败这两条路径

3. **导航**
   - 把导航链接都测一遍
   - 验证浏览器前进 / 后退按钮还能用
   - 测深链接能不能直达
   - 检查 404 的处理

4. **响应式设计**
   - 在移动端断点上测（375px、414px）
   - 在平板断点上测（768px、1024px）
   - 在桌面端断点上测（1280px、1920px）

### 在本仓库/本机上验证（实测配方，照抄比猜快）

上面的写法是通用的。真正在这个应用里开浏览器时，下面这些是**实测**出来的，每一条都省掉一次失败重试。

**先认清自己在哪**：你是被 `:8765` 的后端调用起来的。**不要重启这个栈**——`./start.sh` 的第一步就是杀掉
`:8765` 上的监听进程，也就是正在跑你这轮对话的那个进程（脚本现在有祖先守卫会拒绝，但别把它当许可）。实测后果：
回合在工具执行中途消失，用户看到转圈、然后 "Load failed"，而 LangGraph 会在下一轮重跑那个没跑完的工具调用。
需要重启就把命令原样交给用户。

| 事实 | 值 |
|---|---|
| 前端 | `http://localhost:1421`（vite） |
| 路由形式 | `HashRouter`：`http://localhost:1421/#/chat?agentId=<id>` —— 不是 `/chat?…` |
| 后端 | `http://127.0.0.1:8765` |
| 聊天页 | 输入框 `textarea[placeholder="Do anything"]`，发送按钮 `button[title="Send message"]` |
| 消息滚动容器 | `div.overflow-y-auto`，取 `scrollHeight - clientHeight`（可滚动高度）最大的那个 |
| 模型 key | 在数据库里，不在 `.env`——`.env` 为空不代表没配 |

**Playwright 在这台机器上是"半装"状态**：项目里没有；系统 python 是 externally-managed，`pip3 install` 会被拒
（PEP 668）；但 `~/Library/Caches/ms-playwright/chromium-1223/` 里有现成浏览器。所以：新建 venv 装库、复用缓存里的
浏览器，**不要 `playwright install` 重新下载**。

```bash
python3 -m venv /tmp/pwenv && /tmp/pwenv/bin/pip install -q playwright
```

```python
CHROME = ("/Users/<you>/Library/Caches/ms-playwright/chromium-1223/chrome-mac-arm64/"
          "Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing")
browser = p.chromium.launch(headless=True, executable_path=CHROME)
```

版本不匹配（新 playwright 想找 1254，缓存里是 1223）时同样走 `executable_path`，不要去下新的浏览器。

**测流式/滚动这类行为：采样，不要截图判读。** 判据写在数字上，例如"内容长高时视口还在底部"：

```python
snap = page.evaluate("""() => {
  const el = [...document.querySelectorAll('div.overflow-y-auto')]
    .filter(e => e.clientHeight > 200)
    .sort((a, b) => (b.scrollHeight - b.clientHeight) - (a.scrollHeight - a.clientHeight))[0];
  return {top: Math.round(el.scrollTop), sh: el.scrollHeight, ch: el.clientHeight,
          gap: Math.round(el.scrollHeight - el.clientHeight - el.scrollTop)};
}""")
```

判据示例（一次真实验证用过）：内容增长 `> 300px`；**内容增长期间**的采样点里 `gap <= 40` 的比例 `>= 80%`。
这一个判据同时否掉两种假绿：根本没跟（`gap` 一直很大）和测错了容器（`sh` 不变化）。

**SPA 的两个坑**：用 `wait_until="domcontentloaded"` 而不是 `networkidle`（这个应用常驻 ws/SSE 长连接，
`networkidle` 可能永远不返回）；页面上不止一个 `textarea`，按 `placeholder` 选，别按位置选。
