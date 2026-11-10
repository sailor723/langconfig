---
name: "debugging（调试）"
lang: zh
translated: machine
source: backend/skills/en-originals/debugging/SKILL.md
description: >-
  调试代码、分析错误与系统化解决问题的专家指引。排查缺陷、理解错误信息，或调查反常行为时使用。
tags: [debugging, errors, troubleshooting, logging, profiling]
triggers:
  - "用户提到缺陷"
  - "用户提到错误"
  - "用户提到调试"
  - "用户提到排查"
  - "用户提到“不工作”"
allowed-tools: [filesystem, shell, python]
author: LangConfig
---

你是一名具备系统化问题解决能力的专家级调试者。帮助用户高效地定位、理解并修复缺陷。

### 调试心态

**核心原则：**
1. **先复现**——复现不了的，就修不了
2. **隔离问题**——缩到最小的失败用例
3. **先理解再修**——搞清楚它**为什么**坏
4. **一次只改一处**——科学方法
5. **验证修复**——确认它真的有效

### 系统化调试流程

#### 第 1 步：收集信息
```
要问的问题：
- 期望的行为是什么？
- 实际的行为是什么？
- 什么时候开始出现的？
- 最近改了什么？
- 可复现吗？必现还是偶发？
- 在所有环境都会出现吗？
```

#### 第 2 步：复现缺陷
```bash
# Create minimal reproduction
1. Start with failing case
2. Remove unrelated code
3. Simplify inputs
4. Document exact steps
```

#### 第 3 步：提出假设
```
按症状看，可能是什么造成的？
- 输入校验问题？
- 状态管理缺陷？
- 竞态条件？
- 环境差异？
- 依赖版本不一致？
```

#### 第 4 步：验证假设
```
对每条假设：
1. 预测它成立时你会看到什么
2. 设计验证它的测试
3. 执行该测试
4. 分析结果
5. 修正它，或换下一条假设
```

### 错误信息分析

#### Python 回溯（traceback）
```python
Traceback (most recent call last):
  File "app.py", line 42, in process_data
    result = transform(data)
  File "utils.py", line 15, in transform
    return data["key"]
KeyError: 'key'

# Analysis:
# 1. Error type: KeyError
# 2. Direct cause: Accessing 'key' that doesn't exist
# 3. Location: utils.py line 15
# 4. Call path: app.py:42 -> utils.py:15
# 5. Fix: Add key existence check or use .get()
```

#### JavaScript 错误
```javascript
TypeError: Cannot read property 'map' of undefined
    at UserList (components/UserList.js:15:23)
    at renderWithHooks (react-dom.js:1234)

// Analysis:
// 1. Error type: TypeError (accessing property of undefined)
// 2. The array being mapped is undefined
// 3. Location: UserList.js line 15
// 4. Fix: Add null check or default value
```

### 调试技法

#### 1. 打印 / 日志调试
```python
# Strategic logging
import logging
logger = logging.getLogger(__name__)

def process_order(order):
    logger.debug(f"Processing order: {order.id}")
    logger.debug(f"Order items: {order.items}")

    for item in order.items:
        logger.debug(f"Processing item: {item.id}, quantity: {item.qty}")
        result = calculate_price(item)
        logger.debug(f"Calculated price: {result}")

    logger.info(f"Order {order.id} processed successfully")
```

#### 2. 交互式调试
```python
# Python debugger
import pdb; pdb.set_trace()  # Breakpoint

# Or use breakpoint() in Python 3.7+
breakpoint()

# Common pdb commands:
# n - next line
# s - step into function
# c - continue
# p variable - print variable
# l - list source code
# w - show call stack
# q - quit debugger
```

#### 3. 二分查找调试
```
缺陷存在，但不知道位置时：
1. 找一个已知正常的状态（commit、版本）
2. 找到坏掉的状态
3. 测中点
4. 坏了，就搜前半段
5. 正常，就搜后半段
6. 重复直到找到

# Git bisect 把这件事自动化了：
git bisect start
git bisect bad HEAD
git bisect good v1.0.0
# Git 会自己 checkout 中点给你测
```

#### 4. 小黄鸭调试
```
把问题大声讲出来：
1. 说出代码应该做什么
2. 一行一行走一遍
3. 解释每一行实际做了什么
4. 两者对不上的地方，往往就是缺陷所在
```

### 常见缺陷模式

#### 差一错误
```python
# Bug
for i in range(len(arr)):  # Might miss last element
    process(arr[i], arr[i+1])  # IndexError!

# Fix
for i in range(len(arr) - 1):
    process(arr[i], arr[i+1])
```

#### 空 / undefined 引用
```python
# Bug
user = get_user(id)
print(user.name)  # AttributeError if user is None

# Fix
user = get_user(id)
if user:
    print(user.name)
else:
    print("User not found")
```

#### 竞态条件
```python
# Bug: Check-then-act race condition
if not file_exists(path):
    create_file(path)  # Another process might create it between check and create

# Fix: Use atomic operation
try:
    create_file_exclusive(path)
except FileExistsError:
    pass  # Handle existing file
```

#### 状态变异缺陷
```python
# Bug: Mutating shared state
def add_item(cart, item):
    cart.append(item)  # Mutates original!
    return cart

# Fix: Return new state
def add_item(cart, item):
    return cart + [item]  # Creates new list
```

### 性能调试

#### 剖析 Python
```python
import cProfile
import pstats

# Profile a function
cProfile.run('my_function()', 'profile_output')

# Analyze results
stats = pstats.Stats('profile_output')
stats.sort_stats('cumulative')
stats.print_stats(10)  # Top 10 time consumers
```

#### 内存剖析
```python
from memory_profiler import profile

@profile
def memory_intensive_function():
    big_list = [i for i in range(1000000)]
    return sum(big_list)
```

#### 给代码计时
```python
import time
from contextlib import contextmanager

@contextmanager
def timer(label):
    start = time.perf_counter()
    yield
    elapsed = time.perf_counter() - start
    print(f"{label}: {elapsed:.4f}s")

# Usage
with timer("Database query"):
    results = db.query(User).all()
```

### 调试工具

#### Python
- `pdb` / `ipdb`——交互式调试器
- `logging`——结构化日志
- `traceback`——堆栈回溯工具
- `cProfile`——性能剖析
- `memory_profiler`——内存分析

#### JavaScript
- 浏览器 DevTools——调试器、网络面板、控制台
- `console.log/trace/table`——日志输出
- `debugger` 语句——断点
- Chrome Performance 面板——性能剖析

#### 通用
- Git bisect——定位引入问题的 commit
- Strace/ltrace——系统调用跟踪
- Wireshark——网络调试
- Docker logs——容器调试

### 调试检查清单

- [ ] 你能复现这个缺陷吗？
- [ ] 你拿到了确切的错误信息吗？
- [ ] 你查过日志了吗？
- [ ] 它是否只在特定环境出现？
- [ ] 最近改了什么？
- [ ] 你试过最小复现了吗？
- [ ] 你验证过修复有效吗？
- [ ] 你加了防止回归的测试吗？
