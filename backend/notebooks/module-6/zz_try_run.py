import subprocess, sys
r = subprocess.run([sys.executable, "/Users/weiping/dev/Learn/langchain-ai/deep_agent_0530/notebooks/module-6/tmp_run_calc.py"], capture_output=True, text=True, timeout=35)
print(r.stdout[:5000])
print("ERR:", r.stderr[:1000])
print("RC:", r.returncode)
