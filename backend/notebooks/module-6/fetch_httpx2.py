import httpx, sys
r = httpx.get("https://docs.langchain.com/llms.txt", follow_redirects=True, timeout=30)
print(f"Status: {r.status_code}, Length: {len(r.text)}", flush=True)
sys.stdout.flush()
# Save first 5000 chars to file
with open("/Users/weiping/dev/Learn/langchain-ai/deep_agent_0530/notebooks/module-6/llms_index.txt", "w") as f:
    f.write(r.text)
print(f"Saved to file", flush=True)
