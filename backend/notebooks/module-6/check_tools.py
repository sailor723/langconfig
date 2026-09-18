import subprocess
result = subprocess.run(["which", "python3"], capture_output=True, text=True, timeout=10)
print("python3:", result.stdout.strip())
result = subprocess.run(["which", "uv"], capture_output=True, text=True, timeout=10)
print("uv:", result.stdout.strip())
result = subprocess.run(["which", "curl"], capture_output=True, text=True, timeout=10)
print("curl:", result.stdout.strip())
result = subprocess.run(["which", "wget"], capture_output=True, text=True, timeout=10)
print("wget:", result.stdout.strip())
