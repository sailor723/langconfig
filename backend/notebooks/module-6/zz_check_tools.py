import subprocess
for cmd in ["python3", "curl", "wget", "python"]:
    result = subprocess.run(["which", cmd], capture_output=True, text=True, timeout=10)
    print(f"{cmd}: {result.stdout.strip() or 'NOT FOUND'}")
