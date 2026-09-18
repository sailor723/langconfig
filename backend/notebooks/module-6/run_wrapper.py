import subprocess
import sys

result = subprocess.run(
    [sys.executable, "/Users/weiping/dev/Learn/langchain-ai/deep_agent_0530/notebooks/module-6/tmp_run_calc.py"],
    capture_output=True,
    text=True
)
print("STDOUT:", result.stdout)
print("STDERR:", result.stderr)
