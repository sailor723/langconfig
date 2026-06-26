import urllib.request, ssl
ctx = ssl._create_unverified_context()
url = "https://docs.langchain.com/llms.txt"
req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
    data = resp.read().decode("utf-8")
with open("/Users/weiping/dev/Learn/langchain-ai/deep_agent_0530/notebooks/module-6/llms_index.txt", "w") as f:
    f.write(data)
print(f"OK:{len(data)}")
