import urllib.request
import sys

url = "https://docs.langchain.com/llms.txt"
try:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as response:
        content = response.read().decode("utf-8")
        sys.stdout.write(content)
except Exception as e:
    print(f"Error: {e}", file=sys.stderr)
