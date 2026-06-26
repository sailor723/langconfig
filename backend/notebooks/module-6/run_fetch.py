import subprocess, sys
result = subprocess.run(
    [sys.executable, "/Users/weiping/dev/Learn/langchain-ai/deep_agent_0530/notebooks/module-6/fetch_llms.py"],
    capture_output=True, text=True, timeout=30
)
print("STDOUT:", result.stdout)
print("STDERR:", result.stderr[:1000])
print("RC:", result.returncode)
