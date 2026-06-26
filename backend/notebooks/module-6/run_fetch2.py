import subprocess, sys
result = subprocess.run(
    [sys.executable, "-c", "import urllib.request,ssl;ctx=ssl._create_unverified_context();req=urllib.request.Request('https://docs.langchain.com/llms.txt',headers={'User-Agent':'Mozilla/5.0'});d=urllib.request.urlopen(req,timeout=30,context=ctx).read().decode();open('/Users/weiping/dev/Learn/langchain-ai/deep_agent_0530/notebooks/module-6/llms_index.txt','w').write(d);print('OK:'+str(len(d)))"],
    capture_output=True, text=True, timeout=30
)
print("STDOUT:", result.stdout)
print("STDERR:", result.stderr[:1000])
print("RC:", result.returncode)
