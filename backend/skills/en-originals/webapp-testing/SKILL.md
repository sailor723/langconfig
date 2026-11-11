---
name: webapp-testing
description: >-
  Expert guidance for testing web applications using Playwright and other testing frameworks. Use when testing UIs, automating browser interactions, or validating web app behavior.
tags: [testing, playwright, selenium, e2e, browser, automation]
triggers:
  - "when user mentions Playwright"
  - "when user mentions browser testing"
  - "when user mentions e2e testing"
  - "when user mentions UI testing"
  - "when user mentions selenium"
allowed-tools: [filesystem, shell, python]
author: LangConfig
---

You are an expert web application tester specializing in browser automation with Playwright. Follow these guidelines for comprehensive testing.

### Testing Strategy Decision Tree

**Step 1: Determine Application Type**
- Static HTML → Use simple page inspection
- Dynamic SPA → Wait for network idle before inspection
- Server-rendered → Check both initial HTML and hydrated state

**Step 2: Choose Testing Approach**
```
Is the server running?
├── Yes → Use live server testing
│   └── Can you start it? → Use with_server.py helper
└── No → Static file testing or start server first
```

### Core Playwright Patterns

#### 1. Basic Test Structure (Python)
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

#### 2. Critical Wait Patterns
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

#### 3. Selector Best Practices
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

#### 4. Form Testing
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

### Multi-Server Testing

When testing apps with separate frontend/backend:

```python
# Helper script usage
# python scripts/with_server.py --help

# Start multiple servers
# python scripts/with_server.py \
#   --server "cd backend && python main.py" --port 8000 \
#   --server "cd frontend && npm run dev" --port 3000 \
#   -- python tests/e2e_test.py
```

### Visual Testing Patterns

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

### Console and Network Monitoring

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

### API Testing Integration

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

### Common Testing Scenarios

1. **Authentication Flow**
   - Test login with valid/invalid credentials
   - Verify session persistence
   - Test logout and session cleanup
   - Check protected route redirects

2. **Form Validation**
   - Test required field validation
   - Test format validation (email, phone)
   - Test min/max length constraints
   - Test form submission success/failure

3. **Navigation**
   - Test all navigation links
   - Verify back/forward browser buttons
   - Test deep linking
   - Check 404 handling

4. **Responsive Design**
   - Test at mobile breakpoints (375px, 414px)
   - Test at tablet breakpoints (768px, 1024px)
   - Test at desktop breakpoints (1280px, 1920px)
### Verifying in THIS repository / on THIS machine (measured recipe)

The patterns above are generic. These were measured while driving this app, and each one
saves a failed attempt.

**Know where you are running.** You are invoked by the backend on `:8765`. **Do not restart
that stack** — `./start.sh`'s first act is to kill the listener on `:8765`, which is the
process running your own turn (the script now refuses via an ancestor guard; do not treat
that as permission). Measured consequence: the turn disappears mid-tool, the user sees a
spinner then "Load failed", and LangGraph re-runs the unfinished tool call on the next
message. Hand the restart command to the user instead.

| Fact | Value |
|---|---|
| Frontend | `http://localhost:1421` (vite) |
| Routing | `HashRouter`: `http://localhost:1421/#/chat?agentId=<id>` — not `/chat?…` |
| Backend | `http://127.0.0.1:8765` |
| Chat page | input `textarea[placeholder="Do anything"]`, send button `button[title="Send message"]` |
| Message scroller | `div.overflow-y-auto` — pick the one with the largest `scrollHeight - clientHeight` |
| Model keys | live in the database, not `.env` |

**Playwright is half-installed here**: absent from the project; the system python is
externally managed, so `pip3 install` is refused (PEP 668); but
`~/Library/Caches/ms-playwright/chromium-1223/` already holds a browser. So: make a venv,
install the library, reuse the cached browser — never `playwright install`.

```bash
python3 -m venv /tmp/pwenv && /tmp/pwenv/bin/pip install -q playwright
```

```python
CHROME = ("/Users/<you>/Library/Caches/ms-playwright/chromium-1223/chrome-mac-arm64/"
          "Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing")
browser = p.chromium.launch(headless=True, executable_path=CHROME)
```

When the versions disagree (a newer playwright looks for 1254, the cache has 1223) pass
`executable_path` instead of downloading a new browser.

**For streaming/scrolling behaviour: sample, do not read screenshots.** Put the criterion in
numbers, e.g. "while the content grows, the viewport stays at the bottom":

```python
snap = page.evaluate("""() => {
  const el = [...document.querySelectorAll('div.overflow-y-auto')]
    .filter(e => e.clientHeight > 200)
    .sort((a, b) => (b.scrollHeight - b.clientHeight) - (a.scrollHeight - a.clientHeight))[0];
  return {top: Math.round(el.scrollTop), sh: el.scrollHeight, ch: el.clientHeight,
          gap: Math.round(el.scrollHeight - el.clientHeight - el.scrollTop)};
}""")
```

A worked criterion: content grows by `> 300px`, and of the samples taken *while it grows*,
at least 80% must have `gap <= 40`. That single check rejects both false greens — never
following (`gap` stays large) and measuring the wrong container (`sh` never changes).

**Two SPA traps**: use `wait_until="domcontentloaded"`, not `networkidle` (this app holds
long-lived ws/SSE connections, so `networkidle` may never fire); and there is more than one
`textarea`, so select by `placeholder`, not by position.
