import subprocess
result = subprocess.run(
    ["curl", "-s", "--max-time", "15", "https://docs.langchain.com/llms.txt"],
    capture_output=True, text=True, timeout=20
)
print("LEN:", len(result.stdout))
print("CONTENT:", result.stdout[:5000])
print("ERR:", result.stderr[:500])
print("RC:", result.returncode)
