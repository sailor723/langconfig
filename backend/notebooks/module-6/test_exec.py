import subprocess, sys
# Try running python3 -c with a simple command
result = subprocess.run(["python3", "-c", "print('hello')"], capture_output=True, text=True, timeout=10)
print(f"stdout: {result.stdout}")
print(f"stderr: {result.stderr}")
print(f"returncode: {result.returncode}")
