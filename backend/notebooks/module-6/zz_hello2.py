import subprocess, sys
r = subprocess.run([sys.executable, "-c", "print('hello world')"], capture_output=True, text=True, timeout=5)
print("OUT:", r.stdout)
print("ERR:", r.stderr)
print("RC:", r.returncode)
