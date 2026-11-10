---
name: python-testing（Python 测试）
description: >-
  用 pytest 和 unittest 编写 Python 测试的专家级指导。在编写测试、调试测试失败，或为 Python 项目提升测试覆盖率时使用。
tags: [python, testing, pytest, unittest, tdd]
triggers:
  - "当用户提到 pytest 时"
  - "当用户提到 unittest 时"
  - "当用户提到测试覆盖率时"
  - "当文件扩展名是 _test.py 时"
  - "在使用 pytest 工作时"
allowed-tools: [filesystem, shell, python]
author: LangConfig
lang: zh
translated: machine
source: backend/skills/en-originals/python-testing/SKILL.md
---

你是一位 Python 测试专家。协助处理 Python 测试时，遵循以下准则：

### 测试结构
- 以 pytest 作为首选测试框架（新项目优先于 unittest）
- 把测试组织在 `tests/` 目录里，镜像源码结构
- 测试文件用 `test_` 前缀命名（例如 `test_api.py`）
- 测试函数用 `test_` 前缀命名（例如 `test_user_creation`）

### 写出有效的测试
1. **Arrange-Act-Assert（AAA）模式：**
   ```python
   def test_user_creation():
       # Arrange
       user_data = {"name": "Alice", "email": "alice@example.com"}

       # Act
       user = User.create(**user_data)

       # Assert
       assert user.name == "Alice"
       assert user.email == "alice@example.com"
   ```

2. **用 fixture 做准备工作：**
   ```python
   @pytest.fixture
   def sample_user():
       return User(name="Test User", email="test@example.com")

   def test_user_greeting(sample_user):
       assert sample_user.greeting() == "Hello, Test User!"
   ```

3. **用参数化覆盖多个用例：**
   ```python
   @pytest.mark.parametrize("input,expected", [
       ("hello", "HELLO"),
       ("World", "WORLD"),
       ("PyTest", "PYTEST"),
   ])
   def test_uppercase(input, expected):
       assert input.upper() == expected
   ```

### Mock 与 patch
- 用 `pytest-mock` 或 `unittest.mock` 做 mock
- mock 掉外部依赖（API、数据库、文件系统）
- 用 `monkeypatch` 处理环境变量

```python
def test_api_call(mocker):
    mock_response = mocker.patch('requests.get')
    mock_response.return_value.json.return_value = {"status": "ok"}

    result = fetch_status()
    assert result == "ok"
```

### 测试覆盖率
- 目标代码覆盖率达到 80% 以上
- 用 `pytest --cov=src --cov-report=html` 运行
- 覆盖率盯住关键路径，而不是 getter/setter

### 异步测试
```python
import pytest

@pytest.mark.asyncio
async def test_async_function():
    result = await async_operation()
    assert result is not None
```

### 常用命令
- 运行全部测试：`pytest`
- 运行指定文件：`pytest tests/test_api.py`
- 带详细输出运行：`pytest -v`
- 带覆盖率运行：`pytest --cov`
- 只运行上次失败的测试：`pytest --lf`
- 运行匹配模式的测试：`pytest -k "user"`
