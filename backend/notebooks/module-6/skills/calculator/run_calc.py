import asyncio
import sys
sys.path.insert(0, '/Users/weiping/dev/Learn/langchain-ai/deep_agent_0530/notebooks/module-6/skills/calculator')
from calculator import run_python

result = run_python("15 + 27")
print(result)
