import subprocess, sys
r = subprocess.run([sys.executable, "/tmp/run_searches_v5.py"], capture_output=True, text=True, timeout=120)
print(r.stdout[:1000])
if r.stderr:
    print("STDERR:", r.stderr[:5000])
