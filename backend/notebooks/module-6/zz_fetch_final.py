#!/usr/bin/env python3
# Try to fetch the docs index
import urllib.request, ssl
ctx = ssl._create_unverified_context()
url = "https://docs.langchain.com/llms.txt"
req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
try:
    with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
        data = resp.read().decode("utf-8")
    print("SUCCESS")
    print(data[:8000])
except Exception as e:
    print(f"ERROR: {e}")
