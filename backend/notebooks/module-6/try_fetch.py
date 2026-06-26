import subprocess
# Try wget
try:
    r = subprocess.run(["wget", "-q", "-O", "-", "https://docs.langchain.com/llms.txt"], capture_output=True, text=True, timeout=30)
    print("WGET STDOUT:", r.stdout[:5000])
    print("WGET STDERR:", r.stderr[:500])
except FileNotFoundError:
    print("wget not found")
    
# Try curl
try:
    r = subprocess.run(["curl", "-sL", "https://docs.langchain.com/llms.txt"], capture_output=True, text=True, timeout=30)
    print("CURL STDOUT:", r.stdout[:5000])
    print("CURL STDERR:", r.stderr[:500])
except FileNotFoundError:
    print("curl not found")
