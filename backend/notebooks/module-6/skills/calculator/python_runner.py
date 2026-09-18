import asyncio
from typing import Any
from langchain_sandbox import PyodideSandbox

_sandbox = None

async def get_sandbox():
    global _sandbox
    if _sandbox is None:
        _sandbox = PyodideSandbox(allow_net=True)
    return _sandbox

async def run_python(code: str) -> str:
    sandbox = await get_sandbox()
    result = await sandbox.execute(code)
    if result.status == "success":
        if result.stdout:
            return result.stdout.strip()
        return str(result.result)
    else:
        return f"Error: {result.stderr}"

def sync_run_python(code: str) -> str:
    return asyncio.run(run_python(code))