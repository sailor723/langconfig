import subprocess, sys
result = subprocess.run(
    [sys.executable, "/Users/weiping/dev/Learn/langchain-ai/deep_agent_0530/notebooks/module-6/zz_check_tools.py"],
    capture_output=True, text=True, timeout=10
)
print(result.stdout)
print("ERR:", result.stderr[:500])
