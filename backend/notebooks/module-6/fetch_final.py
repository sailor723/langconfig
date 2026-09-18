import urllib.request, sys
req = urllib.request.Request("https://docs.langchain.com/llms.txt", headers={"User-Agent": "Mozilla/5.0"})
with urllib.request.urlopen(req, timeout=30) as response:
    data = response.read().decode("utf-8")
    sys.stdout.write(data)
