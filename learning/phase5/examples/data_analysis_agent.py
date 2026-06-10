#!/usr/bin/env uv run
# /// script
# requires-python = ">=3.10"
# dependencies = [
#     "deepagents>=0.5.0",
#     "langchain-core>=0.3.0",
# ]
# ///
"""
Data Analysis Agent — Standalone Demo
======================================

A 100% standalone DeepAgent that:
  1. Creates sample CSV sales data in a local sandbox
  2. Explores and analyzes the data via Python scripts (pandas, matplotlib)
  3. Shares results via a custom tool (saves to local file instead of Slack)

Usage:
  uv run data_analysis_agent.py

Based on: https://docs.langchain.com/oss/python/deepagents/data-analysis
"""

import csv
import io
import os
from pathlib import Path
from typing import Optional

from langchain.tools import tool
from langchain_core.utils.uuid import uuid7
from langgraph.checkpoint.memory import InMemorySaver

from deepagents import create_deep_agent
from deepagents.backends import LocalShellBackend

# ============================================================================
# 1. SETUP — Sandbox backend
# ============================================================================
# LocalShellBackend provides sandboxed file access + `execute` tool.
# All operations are scoped to the root_dir.
SANDBOX_DIR = Path("./_data_analysis_sandbox")
SANDBOX_DIR.mkdir(parents=True, exist_ok=True)

backend = LocalShellBackend(
    root_dir=str(SANDBOX_DIR),
    timeout=120,
    max_output_bytes=100_000,
    inherit_env=True,          # Inherit PATH so pip/python/pandas are available
)

print(f"🔧 Sandbox directory: {SANDBOX_DIR.resolve()}")

# ============================================================================
# 2. UPLOAD SAMPLE DATA
# ============================================================================
# Create sample sales data (same as the tutorial)
data = [
    ["Date", "Product", "Units Sold", "Revenue"],
    ["2025-08-01", "Widget A", 10, 250],
    ["2025-08-02", "Widget B", 5, 125],
    ["2025-08-03", "Widget A", 7, 175],
    ["2025-08-04", "Widget C", 3, 90],
    ["2025-08-05", "Widget B", 8, 200],
]

text_buf = io.StringIO()
writer = csv.writer(text_buf)
writer.writerows(data)
csv_bytes = text_buf.getvalue().encode("utf-8")
text_buf.close()

# Write the CSV file into the sandbox filesystem
backend.upload_files([("data/sales_data.csv", csv_bytes)])
print("✅ Sample sales data uploaded to sandbox: data/sales_data.csv")

# ============================================================================
# 3. IMPLEMENT CUSTOM TOOLS
# ============================================================================
# Instead of Slack (which requires an API token), we save results to a local
# file. The pattern is identical to the tutorial's slack_send_message tool.


@tool(parse_docstring=True)
def save_analysis_result(text: str, file_path: Optional[str] = None) -> str:
    """Save analysis results, optionally including file attachments.

    Args:
        text: (str) Text content of the analysis report
        file_path: (str) Optional path of a file attachment in the sandbox
    """
    output_dir = Path("./_analysis_output")
    output_dir.mkdir(parents=True, exist_ok=True)

    # Save the text report
    report_path = output_dir / "analysis_report.txt"
    report_path.write_text(text)
    print(f"\n📄 Analysis report saved to: {report_path.resolve()}")

    # If there's an attached file (e.g. a plot), download it from the sandbox
    if file_path:
        try:
            downloaded = backend.download_files([file_path])
            for fp in downloaded:
                local_path = output_dir / Path(fp.filename).name
                local_path.write_bytes(fp.content)
                print(f"📎 Attachment saved to: {local_path.resolve()}")
        except Exception as e:
            return f"Warning: could not download attachment '{file_path}': {e}"

    return "Analysis results saved successfully."


# ============================================================================
# 4. CREATE THE DEEP AGENT
# ============================================================================
checkpointer = InMemorySaver()

agent = create_deep_agent(
    model="deepseek-chat",           # Or any model you have configured
    tools=[save_analysis_result],    # Custom tool(s) for external integration
    backend=backend,                 # Sandbox for code execution
    checkpointer=checkpointer,       # Multi-turn conversation support
)

thread_id = str(uuid7())
config = {"configurable": {"thread_id": thread_id}}

print(f"🤖 Agent created (thread_id={thread_id})")
print(f"   Model: deepseek-chat")
print(f"   Tools: save_analysis_result + built-in (ls, read_file, write_file, execute, ...)")
print()

# ============================================================================
# 5. RUN THE AGENT
# ============================================================================
input_message = {
    "role": "user",
    "content": (
        "Analyze ./data/sales_data.csv in the current dir and generate a beautiful plot. "
        "When finished, save your analysis and the plot using the save_analysis_result tool."
    ),
}

print("=" * 70)
print("  AGENT RUNNING — analyzing sales data...")
print("=" * 70)
print()

for step in agent.stream(
    {"messages": [input_message]},
    config,
    stream_mode="updates",
):
    for node_name, update in step.items():
        if update and (messages := update.get("messages")) and isinstance(messages, list):
            for message in messages:
                message.pretty_print()
                print()

# ============================================================================
# 6. RESULTS
# ============================================================================
print()
print("=" * 70)
print("  RESULTS")
print("=" * 70)
print(f"  Sandbox:    {SANDBOX_DIR.resolve()}")
print(f"  Output:     {Path('./_analysis_output').resolve()}")
print(f"  Thread ID:  {thread_id}")
print()
print("  📖 Check _analysis_output/ for the report and any plots.")
print("  🧹 To clean up: rm -rf _data_analysis_sandbox _analysis_output")
print("=" * 70)
