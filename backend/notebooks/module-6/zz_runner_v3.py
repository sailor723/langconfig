import subprocess, sys
# Try running the fetch script directly
result = subprocess.run(
    [sys.executable, "/Users/weiping/dev/Learn/langchain-ai/deep_agent_0530/notebooks/module-6/zz_fetch_llms_tmp.py"],
    capture_output=True, text=True, timeout=30
)
print("STDOUT:", result.stdout[:5000])
print("STDERR:", result.stderr[:2000])
print("RC:", result.returncode)
