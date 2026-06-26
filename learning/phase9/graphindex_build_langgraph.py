#!/usr/bin/env python3
"""
graphindex_build_langgraph.py — Phase 9 / Step L (graphindex Builder via LangGraph)

LangGraph-based CLI that orchestrates the 4 build operations
(ingest / rebuild_one / rebuild_project / show) through an explicit
3-node StateGraph.

The graph:
    START → parse_intent ─┬─→ execute_action → format_response → END
                          └─→ format_response ──────────────────→ END
                          (when intent is missing or invalid)

Why explicit StateGraph (not create_react_agent)?
  The 4 build ops are atomic, no multi-step tool-calling needed. Using
  an explicit 3-node graph gives us:

  1. **Transparency** — each phase (parse / execute / format) is a
     distinct node, easy to log + debug.
  2. **Single-LLM-call dispatch** — parse_intent uses structured
     output; format_response is a single LLM call. The dispatch itself
     is plain Python (no LLM).
  3. **Full leverage of graphindex_build_python** — execute_action
     directly calls cmd_ingest / cmd_rebuild_one / cmd_rebuild_project
     / cmd_show. No re-implementation of enrichment / dedup / upsert.

What the LLM is used for
  - parse_intent: 1 call to classify user request + extract args
                  (structured output, deterministic)
  - format_response: 1 call to turn raw cmd output into user prose
  - The actual heavy work (hash / dedup / copy / enrich / upsert)
    is pure Python with 1 LLM call (for metadata only) — that LLM
    call is INSIDE cmd_ingest, not in this graph.

Compare:
  graphindex_chat_agent.py       DeepAgent (multi-step, subagent delegation)
                                 → for chat: complex routing, multi-doc load
  graphindex_build_langgraph.py  LangGraph 3-node StateGraph (this file)
                                 → for build: parse → dispatch → format
  graphindex_build_python.py     Pure Python CLI (no graph)
                                 → for scripted use + reference impl
"""
from __future__ import annotations

import argparse
import contextlib
import io
import os
import sys
import time
from pathlib import Path
from typing import Annotated, Literal, Optional, TypedDict

# Repo + backend + learning/phase9 path resolution
REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "backend"))
if str(REPO_ROOT / "learning" / "phase9") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "learning" / "phase9"))

# LangGraph + LangChain
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.graph.state import CompiledStateGraph
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

# Reuse the build primitives from graphindex_build_python.py
from graphindex_build_python import (
    make_llm,
    cmd_ingest,
    cmd_rebuild_one,
    cmd_rebuild_project,
    cmd_show,
)


# ===========================================================================
# State schema
# ===========================================================================

class BuilderState(TypedDict):
    """State passed through the 3-node graph.

    Reducers:
      - messages: add_messages (append new, dedupe by id)

    Plain fields (last-write-wins):
      - intent:    BuildIntent as dict after parse_intent node
      - cmd_output: captured stdout from cmd_* (after execute_action)
      - error:     string if any step failed
      - final_response: formatted response (after format_response)
    """
    messages: Annotated[list, add_messages]
    intent: Optional[dict]
    cmd_output: Optional[str]
    error: Optional[str]
    final_response: Optional[str]


# ===========================================================================
# Pydantic schemas (for structured output)
# ===========================================================================

class BuildIntent(BaseModel):
    """Parsed user intent — what build action + arguments."""
    action: Literal["ingest", "rebuild_one", "rebuild_project", "show"] = (
        Field(description="Which build operation to perform")
    )
    file_path: Optional[str] = Field(
        default=None,
        description="Absolute path to the file to ingest (for action='ingest')"
    )
    name: Optional[str] = Field(
        default=None,
        description="Document name (for action='rebuild_one' or 'show')"
    )
    target_dir: Optional[str] = Field(
        default=None,
        description="Override target directory (for action='ingest')"
    )
    reasoning: str = Field(
        description="Why this action was chosen (1-2 sentences)"
    )


# ===========================================================================
# System prompts
# ===========================================================================

PARSE_INTENT_PROMPT = """\
You are the graphindex_build_langgraph agent's intent classifier.

Given a user request, determine which of the 4 build actions they want AND
extract ALL required arguments. This is critical: the action alone is not
enough — the system will fail without the proper arguments.

  1. ingest        — Add a new file to the graph index.
                     Required: file_path (an absolute path like /Users/me/x.pdf).
                                Optional: target_dir (an absolute directory path).
                     Common signals: "ingest", "add", "include", "process", "import",
                     "上传", "添加", followed by a file path.

  2. rebuild_one   — Re-enrich ONE existing document.
                     Required: name (the document's exact filename, e.g. "report.pdf").
                     Common signals: "rebuild", "refresh", "re-enrich", "重新生成"
                     followed by a document name.

  3. rebuild_project — Re-enrich ALL documents in the project.
                     Required: (none).
                     Common signals: "rebuild all", "refresh project",
                     "re-enrich everything", "重新生成全部".

  4. show          — Show a document's metadata.
                     Required: name (the document's exact filename).
                     Common signals: "show", "inspect", "what's in", "查看"
                     followed by a document name.

CRITICAL — extract arguments explicitly:
  - When the user mentions a file path, COPY IT VERBATIM into file_path.
    Do not paraphrase, do not omit, do not add extra characters.
  - When the user mentions a document name, COPY IT VERBATIM into name.
  - If the user says "this file" / "the doc" without naming it,
    ask for the name in the reasoning.

Output: a BuildIntent JSON with action, all required args filled in,
optional args if mentioned, and reasoning.
"""

FORMAT_RESPONSE_PROMPT = """\
You are the graphindex_build_langgraph agent's response formatter.

Given the user's request, the action taken, and the raw command output,
produce a clear, user-friendly response.

Guidelines:
- For ingest: confirm file was added; show hash, target location, enrichment summary
- For rebuild_one: confirm doc was re-enriched; show timing
- For rebuild_project: confirm count + total timing
- For show: present about / supports / out_of_scope nicely (truncate long lists)
- For errors: explain what went wrong + suggest what to do
- Use markdown for structure (headers, lists, code blocks for paths)
- Be concise. 1-3 short paragraphs max.
"""


# ===========================================================================
# Graph nodes
# ===========================================================================

def parse_intent(state: BuilderState) -> dict:
    """Node 1: LLM call with structured output → BuildIntent dict.

    Strategy (mirrors extract_document_enrichment in graphindex_build_python.py):
      1. Try llm.with_structured_output(BuildIntent) (preferred)
      2. On failure, try plain llm.invoke() + strip <think> blocks + parse JSON
      3. On total failure, set state['error']

    Reads the last user message, classifies intent + extracts args.
    """
    import json
    import re

    last_msg = state["messages"][-1]
    llm = make_llm()

    # Path 1: structured output
    try:
        structured_llm = llm.with_structured_output(BuildIntent)
        intent: BuildIntent = structured_llm.invoke([
            SystemMessage(content=PARSE_INTENT_PROMPT),
            last_msg,
        ])
        return {"intent": intent.model_dump()}
    except Exception as e1:
        structured_err = e1

    # Path 2: plain invocation, strip <think> blocks, parse JSON
    try:
        raw = llm.invoke([
            SystemMessage(content=PARSE_INTENT_PROMPT
                         + "\n\nIMPORTANT: Return ONLY a JSON object, no prose, no "
                         + "<think> blocks, no markdown code fences. Just the JSON."),
            last_msg,
        ])
        text = raw.content if hasattr(raw, "content") else str(raw)
        # Strip <think>...</think> blocks
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
        # Strip markdown code fences if present
        text = re.sub(r"^```(?:json)?\s*", "", text).strip()
        text = re.sub(r"\s*```$", "", text).strip()
        # Find the JSON object (greedy match for outermost braces)
        m = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not m:
            return {"error": f"Structured failed: {structured_err}. "
                             f"Plain output has no JSON: {text[:200]}"}
        data = json.loads(m.group(0))
        intent = BuildIntent(**data)
        return {"intent": intent.model_dump()}
    except Exception as e2:
        return {"error": f"Failed to parse intent. Structured: {structured_err}. "
                         f"Plain: {e2}"}


def execute_action(state: BuilderState) -> dict:
    """Node 2: Pure Python dispatch to graphindex_build_python.cmd_*.

    No LLM. Reads intent from state, dispatches to the right cmd_*,
    captures stdout. The cmd_* functions are the same ones the CLI uses
    — they handle all the build logic (hash, dedup, copy, enrich, upsert).
    """
    intent = state.get("intent") or {}
    action = intent.get("action")

    # Validate required args per action
    if action == "ingest" and not intent.get("file_path"):
        return {"error": "ingest requires file_path"}
    if action in ("rebuild_one", "show") and not intent.get("name"):
        return {"error": f"{action} requires name (doc filename)"}

    # Capture stdout (cmd_* print progress)
    buf = io.StringIO()
    try:
        with contextlib.redirect_stdout(buf):
            if action == "ingest":
                cmd_ingest(intent["file_path"], target_dir=intent.get("target_dir"))
            elif action == "rebuild_one":
                cmd_rebuild_one(intent["name"])
            elif action == "rebuild_project":
                cmd_rebuild_project()
            elif action == "show":
                cmd_show(intent["name"])
            else:
                return {"error": f"Unknown action: {action}"}
        return {"cmd_output": buf.getvalue()}
    except Exception as e:
        return {
            "error": f"cmd_{action} raised: {e}",
            "cmd_output": buf.getvalue(),
        }


def format_response(state: BuilderState) -> dict:
    """Node 3: LLM call to turn raw cmd output into user-friendly prose.

    On error: explains the error.
    On success: formats the cmd output with context about what was done.
    """
    user_msg = state["messages"][-1]
    user_content = getattr(user_msg, "content", str(user_msg))
    intent = state.get("intent") or {}
    error = state.get("error")
    cmd_output = state.get("cmd_output", "(no output captured)")

    if error:
        prompt = f"""\
The user asked: {user_content}

We tried to execute: {intent}

Error: {error}

Partial output (if any):
{cmd_output}

Briefly explain the error to the user and suggest what to do.
"""
    else:
        prompt = f"""\
The user asked: {user_content}

We executed: {intent}

Raw command output:
{cmd_output}

Format this into a clear, user-friendly response.
"""

    try:
        llm = make_llm()
        resp = llm.invoke([
            SystemMessage(content=FORMAT_RESPONSE_PROMPT),
            HumanMessage(content=prompt),
        ])
        return {"final_response": resp.content, "messages": [resp]}
    except Exception as e:
        # Fallback: return raw output if LLM fails
        return {
            "final_response": (
                f"Action: {intent.get('action')}\n\n"
                f"```\n{cmd_output}\n```\n\n"
                f"(Formatter LLM failed: {e})"
            ),
        }


# ===========================================================================
# Conditional edges
# ===========================================================================

def after_parse(state: BuilderState) -> str:
    """Conditional edge: route to execute_action or skip to format_response.

    Routes to format_response if:
      - error during intent parsing
      - intent is missing or has no action
    Otherwise routes to execute_action.
    """
    if state.get("error"):
        return "format_response"
    if not state.get("intent") or not state["intent"].get("action"):
        return "format_response"
    return "execute_action"


# ===========================================================================
# Graph construction
# ===========================================================================

def create_builder_graph() -> CompiledStateGraph:
    """Build the 3-node StateGraph and compile to a runnable.

    Topology:
        START → parse_intent ─┬─→ execute_action → format_response → END
                              └─→ format_response ──────────────────→ END
    """
    workflow = StateGraph(BuilderState)

    workflow.add_node("parse_intent", parse_intent)
    workflow.add_node("execute_action", execute_action)
    workflow.add_node("format_response", format_response)

    workflow.add_edge(START, "parse_intent")

    workflow.add_conditional_edges(
        "parse_intent",
        after_parse,
        {
            "execute_action": "execute_action",
            "format_response": "format_response",
        },
    )

    workflow.add_edge("execute_action", "format_response")
    workflow.add_edge("format_response", END)

    return workflow.compile()


# ===========================================================================
# Run helper
# ===========================================================================

def run(user_message: str, *, thread_id: str = "default") -> dict:
    """Run the graph on a single user message. Returns final state."""
    graph = create_builder_graph()
    result = graph.invoke(
        {"messages": [HumanMessage(content=user_message)]},
        config={"configurable": {"thread_id": thread_id}},
    )
    return result


# ===========================================================================
# CLI
# ===========================================================================

def cmd_show_graph() -> int:
    """Print the graph structure (nodes + edges)."""
    graph = create_builder_graph()
    print("📊 graphindex_build_langgraph graph structure")
    print()
    print("Nodes:")
    print("  - parse_intent    (LLM: structured output → BuildIntent)")
    print("  - execute_action  (Python: dispatch to cmd_*)")
    print("  - format_response (LLM: prose)")
    print()
    print("Edges:")
    print("  START → parse_intent")
    print("  parse_intent → execute_action     (if intent parsed)")
    print("  parse_intent → format_response    (if error / no intent)")
    print("  execute_action → format_response")
    print("  format_response → END")
    print()
    print("State (BuilderState):")
    print("  - messages:       Annotated[list, add_messages]  (chat history)")
    print("  - intent:         Optional[dict]                 (parsed BuildIntent)")
    print("  - cmd_output:     Optional[str]                  (captured stdout)")
    print("  - error:          Optional[str]                  (if any)")
    print("  - final_response: Optional[str]                  (formatted prose)")
    print()
    print("Graph object (repr):")
    print(f"  {graph!r}")
    return 0


def cmd_answer(message: str) -> int:
    """One-shot Q&A: run the graph on a user message, print the response."""
    print(f"🛠  graphindex_build_langgraph agent")
    print(f"   user: {message}")
    print()

    t0 = time.time()
    result = run(message, thread_id="cli")
    elapsed = time.time() - t0

    # Print tracing
    intent = result.get("intent")
    if intent:
        print(f"   [parse_intent] action={intent.get('action')}")
        if intent.get("file_path"):
            print(f"                file_path={intent.get('file_path')}")
        if intent.get("name"):
            print(f"                name={intent.get('name')}")
        if intent.get("target_dir"):
            print(f"                target_dir={intent.get('target_dir')}")
        if intent.get("reasoning"):
            print(f"                reasoning={intent.get('reasoning')}")

    if result.get("cmd_output"):
        # Show captured stdout (cmd_*) in a code block
        print()
        print("   [execute_action] raw output:")
        for line in result["cmd_output"].splitlines():
            print(f"     {line}")

    if result.get("error"):
        print()
        print(f"   [error] {result['error']}")

    # Final formatted response
    print()
    print("─" * 70)
    print(result.get("final_response", "(no response)"))
    print("─" * 70)
    print()
    print(f"   ⏱  {elapsed:.1f}s  (graph invoke latency)")

    return 0


def cmd_chat() -> int:
    """Interactive REPL: multi-turn conversation with thread persistence."""
    print("🛠  graphindex_build_langgraph agent (REPL)")
    print("   Type your request, or 'exit' / 'quit' to leave.")
    print("   'graph' to show graph structure, 'state' to show last state.")
    print()

    thread_id = "repl"
    last_state: Optional[dict] = None

    while True:
        try:
            user_input = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not user_input:
            continue
        if user_input in ("exit", "quit", "q"):
            break
        if user_input == "graph":
            cmd_show_graph()
            continue
        if user_input == "state":
            print(f"   last state keys: {list((last_state or {}).keys())}")
            if last_state and last_state.get("intent"):
                print(f"   last intent: {last_state['intent']}")
            continue

        last_state = run(user_input, thread_id=thread_id)
        print()
        print(f"agent> {last_state.get('final_response', '(no response)')}")
        print()

    print("👋 bye")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="graphindex_build_langgraph agent (LangGraph 3-node StateGraph)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Show graph structure
  python graphindex_build_langgraph.py --show-graph

  # One-shot Q&A
  python graphindex_build_langgraph.py --answer "Ingest /Users/me/report.pdf"
  python graphindex_build_langgraph.py --answer "Rebuild nke-10k-2023.pdf"
  python graphindex_build_langgraph.py --answer "Show me what's in nke-10k-2023.pdf"
  python graphindex_build_langgraph.py --answer "Re-enrich all docs"

  # Interactive REPL
  python graphindex_build_langgraph.py --chat
""",
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--show-graph", action="store_true",
                       help="print graph structure")
    group.add_argument("--answer", metavar="MSG",
                       help="one-shot Q&A: run graph on a single user message")
    group.add_argument("--chat", action="store_true",
                       help="interactive REPL")
    args = parser.parse_args()

    if not os.getenv("MINIMAX_API_KEY"):
        sys.stderr.write("FATAL: MINIMAX_API_KEY not set in .env\n")
        return 1

    if args.show_graph:
        return cmd_show_graph()
    if args.answer is not None:
        return cmd_answer(args.answer)
    if args.chat:
        return cmd_chat()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
