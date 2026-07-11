# Plan — 100% Mirror of 2.2_files.ipynb in LangConfig UI

## Goal
Reproduce the **observable behavior** of `2.2_files.ipynb` cells 13/18/20/22/23/25
in the LangConfig UI as closely as possible. The notebook introduces a
**virtual filesystem** (`ls`, `read_file`, `write_file` operating on a state
dict, not real disk) used for **context offloading** — agent saves its work
to a virtual file and reads it back to compose the final answer.

## What 2.2_files actually does (cell by cell)

### Cell 13 (file_tools.py — written via %%writefile):
```python
from typing import Annotated
from langchain_core.messages import ToolMessage
from langchain_core.tools import InjectedToolCallId, tool
from langgraph.prebuilt import InjectedState
from langgraph.types import Command

from deep_agents_from_scratch.prompts import (
    LS_DESCRIPTION, READ_FILE_DESCRIPTION, WRITE_FILE_DESCRIPTION,
)
from deep_agents_from_scratch.state import DeepAgentState


@tool(description=LS_DESCRIPTION)
def ls(state: Annotated[DeepAgentState, InjectedState]) -> list[str]:
    """List all files in the virtual filesystem."""
    return list(state.get("files", {}).keys())


@tool(description=READ_FILE_DESCRIPTION, parse_docstring=True)
def read_file(
    file_path: str,
    state: Annotated[DeepAgentState, InjectedState],
    offset: int = 0,
    limit: int = 2000,
) -> str:
    """Read file content with line numbers, offset/limit pagination."""
    files = state.get("files", {})
    if file_path not in files:
        return f"Error: File '{file_path}' not found"
    content = files[file_path]
    if not content:
        return "System reminder: File exists but has empty contents"
    lines = content.splitlines()
    start_idx = offset
    end_idx = min(start_idx + limit, len(lines))
    if start_idx >= len(lines):
        return f"Error: Line offset {offset} exceeds file length ({len(lines)} lines)"
    result_lines = []
    for i in range(start_idx, end_idx):
        line_content = lines[i][:2000]
        result_lines.append(f"{i + 1:6d}\t{line_content}")
    return "\n".join(result_lines)


@tool(description=WRITE_FILE_DESCRIPTION, parse_docstring=True)
def write_file(
    file_path: str,
    content: str,
    state: Annotated[DeepAgentState, InjectedState],
    tool_call_id: Annotated[str, InjectedToolCallId],
) -> Command:
    """Write content to virtual filesystem."""
    files = state.get("files", {})
    files[file_path] = content
    return Command(
        update={
            "files": files,
            "messages": [ToolMessage(f"Updated file {file_path}", tool_call_id=tool_call_id)],
        }
    )
```

### Cell 16 (instructions):
```python
FILE_USAGE_INSTRUCTIONS = """You have access to a virtual file system...

## Workflow Process (FOLLOW IN ORDER):
1. **FIRST ACTION REQUIRED**: Before doing anything else, you MUST call
   write_file with file_path="user_request.txt" and content=<user's request>.
2. **Orient**: Use ls to see existing files.
3. **Research**: Make a single call to web_search.
4. **Read**: Use read_file to read user_request.txt.
5. **FINAL ACTION REQUIRED**: Call write_file with
   file_path="final_answer.txt" and content=<final answer>.

CRITICAL: FIRST tool call MUST be write_file(user_request.txt).
CRITICAL: LAST tool call (before responding) MUST be write_file(final_answer.txt)."""

SIMPLE_RESEARCH_INSTRUCTIONS = """IMPORTANT: Just make a single call to
the web_search tool and use the result to answer the user's question."""

INSTRUCTIONS = FILE_USAGE_INSTRUCTIONS + "\n\n" + "=" * 80 + "\n\n" + SIMPLE_RESEARCH_INSTRUCTIONS
```

### Cell 18 (build agent):
```python
from langchain.chat_models import init_chat_model
from langchain_core.tools import tool
from langchain.agents import create_agent       # ← plain langchain 1.0

# Mock search (returns fixed Chinese MCP paragraph)
@tool(parse_docstring=True)
def web_search(query: str) -> str: ...          # returns fixed Chinese MCP text

# Model
model = init_chat_model(
    model="agnes-2.0-flash",
    model_provider="openai",
    base_url=os.getenv("AGNES_BASE_URL"),
    api_key=os.getenv("AGNES_API_KEY"),
    temperature=0.0,
)

# Tools (write_file first to emphasize required-first ordering)
tools = [write_file, ls, read_file, web_search]

agent = create_agent(
    model,
    tools,
    system_prompt=INSTRUCTIONS,
    state_schema=DeepAgentState,
)
```

### Cell 20 (invoke):
```python
result = agent.invoke({
    "messages": [{"role": "user", "content": "请给我一个关于 MCP 的简短摘要。"}],
    "files": {},                                  # ← empty virtual fs
})
```

### Cell 22 / 23 / 25 (verify):
```python
result["files"]                                  # dict with user_request.txt + final_answer.txt
result['files']['final_answer.txt']              # the final answer content
pprint(result["files"])                          # show all files
```

## Cross-check: LangConfig library surface

### What `langchain.agents.create_agent` accepts (verified):
- `model`, `tools`, `system_prompt`, `state_schema` — all present
- `state_schema=DeepAgentState` IS supported by langchain 1.0

### What LangConfig's `core/agents/factory.py::AgentFactory.create_agent` does:
- `create_agent(**create_agent_kwargs)` at line 536
- `create_agent_kwargs` has only: `model, tools, system_prompt, response_format,
  middleware, checkpointer, interrupt_before, interrupt_after`
- **`state_schema` is NOT passed** — same divergence as 2.1 notebook
- Same functional behavior (langgraph accepts dynamic keys at runtime)

### What `_setup_middleware` adds by default (line 946-997):
- 6 default middleware when `enable_default_middleware=True` (Timestamp,
  ProjectContext, Logging, QuestionDetection, PermissionBasedTool, ContextBasedTool)
- **No `TodoListMiddleware`, no `FilesystemMiddleware`**
- Set `enable_default_middleware=False` to match notebook exactly

### What `ToolLoader.load_native(native_tool_names)` does:
- Routes through `tools.native_tools.load_native_tools(...)`
- Our new `ls`, `read_file`, `write_file` (notebook versions) will be bound
  here, alongside the existing LangConfig implementations

### Critical difference — LangConfig already has its OWN `ls`, `read_file`, `write_file`:
- **LangConfig's `read_file`** (line 570): workspace-aware, returns file content
  with line numbers but reads from **real disk** via `_read_file_impl`
- **LangConfig's `ls`** (line 1008): takes `directory_path` arg, reads from
  **real disk**
- **LangConfig's `write_file`** (line 981): `StructuredTool.from_function`,
  writes to **real disk** with workspace context tracking
- **Notebook's versions**: read/write a `state["files"]` dict (in-memory
  virtual filesystem), NOT real disk

These are **two completely different implementations** serving the same
purpose. The notebook's "virtual filesystem" is the deepagents standard.

## Two approaches

### Option A — Replace LangConfig's `ls`/`read_file`/`write_file` with notebook versions
- Pros: full notebook parity
- Cons: **breaks** all existing agents that rely on the real-disk version
  (every agent with filesystem tools would change behavior). High risk.

### Option B — Add notebook versions as NEW tools with different names
- Pros: no breaking change, existing agents unaffected
- Cons: agents would have BOTH versions bound, model may pick wrong one
- Possible names: `vfs_ls`, `vfs_read_file`, `vfs_write_file`

### Option C — Make the existing tools virtual-fs-by-default, with workspace mode opt-in
- Pros: notebook parity AND no breaking change
- Cons: subtle behavior change, may confuse existing users
- Risky — touching core tools for everyone

### Option D (RECOMMENDED) — Add notebook's `ls`/`read_file`/`write_file` as
### vfs_* aliases that share the same name
- Alias the existing tools under `vfs_ls`/`vfs_read_file`/`vfs_write_file`
- Add new entries in TOOL_REGISTRY
- This matches the notebook's "virtual filesystem" semantics, doesn't break
  the workspace-aware tools
- Users explicitly choose `vfs_*` for state-based, or rely on defaults for
  workspace-based

## Recommended approach: Option D

Add three new tools with the `vfs_` prefix matching the notebook:

1. `vfs_ls` — `ls(state: Annotated[DeepAgentState, InjectedState]) -> list[str]`
2. `vfs_read_file` — `read_file(file_path, state, offset, limit) -> str`
3. `vfs_write_file` — `write_file(file_path, content, state, tool_call_id) -> Command`

The agent editor can select these via the existing `native_tools` list. The
agent's `config.native_tools` would be `["vfs_ls", "vfs_read_file", "vfs_write_file", "web_search"]`.

The system prompt uses the notebook's `FILE_USAGE_INSTRUCTIONS + "="*80 + SIMPLE_RESEARCH_INSTRUCTIONS`.

## Concrete steps

### Backend (one new file or additions to native_tools.py)

1. Add 3 new tool functions in `tools/native_tools.py`:
   - `vfs_ls`, `vfs_read_file`, `vfs_write_file` (vendored from notebook cell 13)
   - 3 entries in `available_tools` dict
   - 3 entries in `TOOL_REGISTRY` list

2. Use the notebook's exact prompts for descriptions:
   - `LS_DESCRIPTION` (139 chars from notebook)
   - `READ_FILE_DESCRIPTION` (442 chars)
   - `WRITE_FILE_DESCRIPTION` (336 chars)

3. Use the notebook's `DeepAgentState`-equivalent TypedDict (already have
   `_TodoState` from phase 11 — add a `_FilesState` for the file dict).

### UI configuration (no code)

Configure the existing 2.1 TODO Demo agent (id=129) or create a new one:

1. **Agent Type**: Regular (not Deep)
2. **Model**: `minimax-m3`, temperature 0.0, max_tokens 4000
3. **Native tools**: `["vfs_write_file", "vfs_ls", "vfs_read_file", "web_search"]`
4. **System prompt**: paste notebook's `INSTRUCTIONS` verbatim
5. **enable_default_middleware**: `false`
6. **No skills, no sub-agents**

### Testing

Run the notebook cell 20 query in the chat:
```
请给我一个关于 MCP 的简短摘要。
```

Expected streamed events:
1. `vfs_write_file("user_request.txt", "请给我一个关于 MCP 的简短摘要。")`
2. `vfs_ls()` — show existing files
3. `web_search("MCP")` — search
4. `vfs_read_file("user_request.txt")` — re-read user request
5. `vfs_write_file("final_answer.txt", "<answer>")` — save final answer
6. Final `AIMessage` to user

## Known divergences

1. `state_schema=DeepAgentState` — not exposed via UI, but langgraph accepts
   dynamic `files` key at runtime (same as 2.1 with `todos`).
2. `enable_default_middleware=False` — must be set explicitly.
3. `web_search` mock content — LangConfig's `web_search` returns keyword-routed
   text instead of the notebook's fixed MCP paragraph.
4. Model — `minimax-m3` instead of `agnes-2.0-flash`.
5. Existing `ls`/`read_file`/`write_file` tools remain workspace-aware on
   disk — only the new `vfs_*` versions are state-dict-based.

## What I learned

- Cell 13 file_tools.py is a fresh vendored module — **3 tools, ~100 LOC**
- Cell 16 instructions — 2 constants (FILE_USAGE_INSTRUCTIONS + SIMPLE_RESEARCH_INSTRUCTIONS)
- Cell 18 — same `create_agent(model, tools, system_prompt, state_schema)` call
- The notebook's "virtual filesystem" is **state-based**, not disk-based
- LangConfig's `ls`/`read_file`/`write_file` are **disk-based** and serve a
  different purpose (persistent workspace storage)

## Files to add/modify

| File | Change |
|---|---|
| `backend/tools/native_tools.py` | +~120 lines: 3 new `vfs_*` tool functions + 3 dict entries + 3 TOOL_REGISTRY entries + description constants |
| `learning/phase12/README.md` | this file |

## What I need you to confirm

1. Use **Option D** (add new `vfs_*` tools) — keeps existing tools intact?
2. Accept the divergences (state_schema, enable_default_middleware, web_search mock)?
3. Apply the same workflow as phase 11 (Regular Agent + system prompt + native_tools via UI)?