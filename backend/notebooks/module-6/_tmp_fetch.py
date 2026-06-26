import subprocess, sys
result = subprocess.run(
    [sys.executable, "-c", 
     "import urllib.request,ssl;ctx=ssl._create_unverified_context();"
     "req=urllib.request.Request('https://docs.langchain.com/llms.txt',headers={'User-Agent':'Mozilla/5.0'});"
     "d=urllib.request.urlopen(req,timeout=30,context=ctx).read().decode();"
     "print(d[:5000])"],
    capture_output=True, text=True, timeout=30
)
print("STDOUT:", result.stdout)
print("STDERR:", result.stderr[:2000])
print("RC:", result.returncode)
