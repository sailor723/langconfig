---
name: calculator
description: Use this skill when user asks to calculate, compute, do math, or work with numbers and formulas.
module: calculator.py
---

# Calculator Skill

## Tool

```python
from calculator import run_python

result = run_python("15 + 27")  # returns "42"
result = run_python("import math; math.sqrt(16)")  # returns "4.0"
```

## Instructions

### 1. Parse the Calculation Request
- Identify what mathematical operation is needed
- Extract the numbers and operators from the user's request
- Confirm understanding if the request is ambiguous

### 2. Perform the Calculation
- Call `run_python()` with Python code
- Supported: basic arithmetic, `import math`, etc.
- Examples: `run_python("2 + 2")`, `run_python("import math; math.sqrt(16)")`

### 3. Present the Result
- State the problem clearly
- Show the answer
- Explain the steps if helpful

### 4. Handle Errors
- Division by zero: explain and return null
- Invalid input: ask for clarification
