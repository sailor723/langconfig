import subprocess, sys
r = subprocess.run([sys.executable, "-c", "print('hello')"], capture_output=True, text=True, timeout=5)
print(r.stdout)
print(r.stderr)
print(r.returncode)
