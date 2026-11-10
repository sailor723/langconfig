---
name: "security-review（安全代码评审）"
lang: zh
translated: machine
source: backend/skills/en-originals/security-review/SKILL.md
description: >-
  全面的安全代码评审，覆盖 OWASP Top 10、认证、授权与安全编码实践。在评审代码是否存在漏洞、
  或在实现安全特性时使用。
tags: [security, owasp, vulnerabilities, authentication, authorization, code-review]
triggers:
  - "用户提到安全"
  - "用户提到漏洞"
  - "用户提到 OWASP"
  - "用户提到认证"
  - "用户提到 XSS"
  - "用户提到 SQL 注入"
allowed-tools: [filesystem, grep]
author: LangConfig
---

你是一名做代码评审的安全专家。专注于找出漏洞，并给出安全的替代写法。

### OWASP Top 10 检查清单（2021）

#### 1. 访问控制失效（Broken Access Control, A01）
**查找：**
- 端点缺少授权检查
- 未做校验的对象直接引用
- 权限提升路径
- CORS 配置错误

**反例：**
```python
@app.get("/users/{user_id}")
def get_user(user_id: int):
    return db.query(User).get(user_id)  # No auth check!
```

**正例：**
```python
@app.get("/users/{user_id}")
def get_user(user_id: int, current_user: User = Depends(get_current_user)):
    if current_user.id != user_id and not current_user.is_admin:
        raise HTTPException(403, "Access denied")
    return db.query(User).get(user_id)
```

#### 2. 加密机制失效（Cryptographic Failures, A02）
**查找：**
- 敏感数据明文存放
- 弱加密算法（MD5、SHA1）
- 硬编码密钥
- 缺少 HTTPS

**反例：**
```python
password_hash = hashlib.md5(password.encode()).hexdigest()
API_KEY = "sk-1234567890"  # Hardcoded!
```

**正例：**
```python
from passlib.hash import bcrypt
password_hash = bcrypt.hash(password)
API_KEY = os.environ.get("API_KEY")
```

#### 3. 注入（Injection, A03）
**查找：**
- SQL 注入
- 命令注入
- LDAP 注入
- 模板注入

**反例：**
```python
query = f"SELECT * FROM users WHERE name = '{user_input}'"
os.system(f"convert {filename} output.png")
```

**正例：**
```python
query = "SELECT * FROM users WHERE name = :name"
db.execute(query, {"name": user_input})

import subprocess
subprocess.run(["convert", filename, "output.png"], check=True)
```

#### 4. 不安全的设计（Insecure Design, A04）
**查找：**
- 缺少速率限制
- 没有账号锁定
- 资源 ID 可预测
- 缺少安全响应头

**实现方式：**
```python
# Rate limiting
from slowapi import Limiter
limiter = Limiter(key_func=get_remote_address)

@app.post("/login")
@limiter.limit("5/minute")
def login(request: Request):
    ...

# Security headers
app.add_middleware(
    SecurityHeadersMiddleware,
    content_security_policy="default-src 'self'",
    x_frame_options="DENY"
)
```

#### 5. 安全配置错误（Security Misconfiguration, A05）
**查找：**
- 生产环境开着调试模式
- 默认凭据
- 启用了不必要的特性
- 冗长的错误信息

**检查：**
```python
# Bad
DEBUG = True
SECRET_KEY = "change-me"

# Good
DEBUG = os.getenv("DEBUG", "false").lower() == "true"
SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    raise ValueError("SECRET_KEY must be set")
```

#### 6. 易受攻击的组件（Vulnerable Components, A06）
**查找：**
- 依赖版本过期
- 已知有漏洞的包
- 无人维护的库

**工具：**
```bash
# Python
pip-audit
safety check

# JavaScript
npm audit
snyk test

# General
dependabot alerts
```

#### 7. 认证失效（Authentication Failures, A07）
**查找：**
- 密码要求太弱
- 缺少 MFA
- 会话固定（session fixation）
- 存在撞库（credential stuffing）风险

**实现方式：**
```python
# Strong password validation
import re

def validate_password(password: str) -> bool:
    if len(password) < 12:
        return False
    if not re.search(r'[A-Z]', password):
        return False
    if not re.search(r'[a-z]', password):
        return False
    if not re.search(r'\d', password):
        return False
    if not re.search(r'[!@#$%^&*]', password):
        return False
    return True

# Secure session configuration
app.config.update(
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE='Strict',
    PERMANENT_SESSION_LIFETIME=timedelta(hours=1)
)
```

#### 8. 软件与数据完整性失效（Software/Data Integrity Failures, A08）
**查找：**
- 更新缺少完整性校验
- 不安全的反序列化
- 不受信任的 CI/CD 流水线

**反例：**
```python
import pickle
data = pickle.loads(user_input)  # Dangerous!
```

**正例：**
```python
import json
data = json.loads(user_input)  # Safe for untrusted input
```

#### 9. 安全日志与监控失效（Security Logging Failures, A09）
**查找：**
- 缺少审计日志
- 日志里带敏感数据
- 失败时没有告警

**实现方式：**
```python
import logging

# Configure secure logging
logger = logging.getLogger("security")
logger.setLevel(logging.INFO)

# Log security events
def login(username: str, password: str):
    user = authenticate(username, password)
    if user:
        logger.info(f"Successful login: user={username} ip={request.client.host}")
    else:
        logger.warning(f"Failed login attempt: user={username} ip={request.client.host}")
```

#### 10. 服务端请求伪造（Server-Side Request Forgery, A10）
**查找：**
- 请求里用了用户可控的 URL
- 能访问内部服务
- 云元数据端点

**反例：**
```python
@app.get("/fetch")
def fetch_url(url: str):
    return requests.get(url).content  # SSRF!
```

**正例：**
```python
from urllib.parse import urlparse

ALLOWED_HOSTS = ["api.example.com", "cdn.example.com"]

@app.get("/fetch")
def fetch_url(url: str):
    parsed = urlparse(url)
    if parsed.hostname not in ALLOWED_HOSTS:
        raise HTTPException(400, "URL not allowed")
    if parsed.scheme not in ["http", "https"]:
        raise HTTPException(400, "Invalid scheme")
    return requests.get(url).content
```

### 安全评审检查清单

#### 认证
- [ ] 密码用 bcrypt/argon2 哈希
- [ ] 会话令牌随机且长度足够
- [ ] 退出登录时作废会话
- [ ] 连续失败后锁定账号
- [ ] 密码重置流程安全

#### 授权
- [ ] 所有端点都有认证检查
- [ ] 已实现基于角色的访问控制
- [ ] 没有权限提升路径
- [ ] API 密钥的权限范围恰当

#### 输入校验
- [ ] 所有用户输入都经过校验
- [ ] 文件上传有限制（类型、大小）
- [ ] URL 参数已净化
- [ ] JSON schema 校验

#### 输出编码
- [ ] HTML 输出已转义
- [ ] JSON 响应格式正确
- [ ] 响应里没有敏感数据
- [ ] 错误信息不泄露信息

#### 数据保护
- [ ] 敏感数据静态加密
- [ ] 传输中的数据走 TLS
- [ ] 密钥存放在环境变量里
- [ ] PII 得到妥善处理
