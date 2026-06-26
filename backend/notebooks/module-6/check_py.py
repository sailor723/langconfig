import subprocess, sys
try:
    r = subprocess.run([sys.executable, "--version"], capture_output=True, text=True, timeout=10)
    print("Python:", r.stdout, r.stderr)
except Exception as e:
    print(f"Error: {e}")
