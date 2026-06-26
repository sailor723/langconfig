"""Module 4 — Document Chat Bot (Long Context Version).

Usage:
  uv run python notebooks/module-4/doc_chatbot.py
  uv run python notebooks/module-4/doc_chatbot.py --doc path/to/doc.md
"""

from __future__ import annotations

import io
import os
import sys
import zipfile
import xml.etree.ElementTree as ET
from pathlib import Path

from dotenv import load_dotenv
from langchain.chat_models import init_chat_model
from langchain_core.tools import tool
from langchain.agents import create_agent

MODULE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = MODULE_DIR.parents[1]
ARTIFACTS_DIR = MODULE_DIR / "artifacts"


def load_environment() -> None:
    load_dotenv(PROJECT_ROOT / ".env")


def build_model():
    provider = os.environ.get("DOCBOT_MODEL_PROVIDER", "deepseek")
    model_name = os.environ.get("DOCBOT_MODEL_NAME", "deepseek-chat")
    temperature = float(os.environ.get("DOCBOT_MODEL_TEMPERATURE", "0.3"))
    return (
        init_chat_model(
            model=model_name,
            model_provider=provider,
            temperature=temperature,
        ),
        provider,
        model_name,
    )


def docx_to_markdown(docx_bytes: bytes) -> str:
    lines = []
    with zipfile.ZipFile(io.BytesIO(docx_bytes)) as z:
        xml_content = z.read("word/document.xml")
    root = ET.fromstring(xml_content)
    ns = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
    for para in root.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"):
        texts = []
        for t in para.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t"):
            if t.text:
                texts.append(t.text)
        text = "".join(texts).strip()
        if not text:
            lines.append("")
            continue
        ppr = para.find(".//w:pStyle", ns)
        if ppr is not None:
            style_val = ppr.get("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}val", "")
            if style_val.startswith("Heading"):
                try:
                    level = int(style_val.replace("Heading", ""))
                except ValueError:
                    level = 1
                lines.append(f"{'#' * level} {text}")
                continue
        lines.append(text)
    return "\n".join(lines)


def load_documents() -> str:
    parts = []
    supported = (".md", ".txt", ".docx")
    files = sorted(ARTIFACTS_DIR.iterdir())
    if not files:
        return ""

    for f in files:
        if f.suffix not in supported or not f.is_file():
            continue
        print(f"  Reading: {f.name}...", end=" ", flush=True)
        if f.suffix == ".docx":
            text = docx_to_markdown(f.read_bytes())
        else:
            text = f.read_text(encoding="utf-8")
        parts.append(text)
        print(f"{len(text):,} chars", flush=True)

    doc_text = "\n\n---\n\n".join(parts)
    print(f"\nTotal document length: {len(doc_text):,} chars", flush=True)
    print(f"Estimated tokens: ~{len(doc_text) // 4:,}", flush=True)
    return doc_text


def copy_doc_to_artifacts(path: str) -> None:
    src = Path(path)
    if not src.exists():
        print(f"File not found: {src}")
        sys.exit(1)
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    dst = ARTIFACTS_DIR / src.name
    content = src.read_bytes()
    if src.suffix == ".docx":
        text = docx_to_markdown(content)
        dst = dst.with_suffix(".md")
        dst.write_text(text, encoding="utf-8")
    else:
        dst.write_bytes(content)
    print(f"Copied {src} -> {dst}")


def main() -> None:
    load_environment()

    # Copy document if provided via CLI
    if "--doc" in sys.argv:
        idx = sys.argv.index("--doc")
        if idx + 1 < len(sys.argv):
            copy_doc_to_artifacts(sys.argv[idx + 1])
    else:
        # Check if artifacts has files
        ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
        has_files = any(f.suffix in (".md", ".txt", ".docx") for f in ARTIFACTS_DIR.iterdir())
        if not has_files:
            print("No documents found in artifacts/")
            print("Place .md/.txt/.docx files in:", ARTIFACTS_DIR)
            print("Or run with: uv run python doc_chatbot.py --doc path/to/doc.md")
            sys.exit(1)

    llm, provider, model_name = build_model()
    print(f"Model: {model_name}  Provider: {provider}\n", flush=True)

    document_text = load_documents()
    if not document_text:
        print("No documents loaded. Exiting.")
        sys.exit(1)

    @tool
    def read_uploaded_documents() -> str:
        """Read all uploaded documents. Call this first before answering questions."""
        return document_text

    agent = create_agent(llm, [read_uploaded_documents], system_prompt=(
        "You are a document Q&A assistant.\n\n"
        "1. When the user asks a question, first call read_uploaded_documents to get the full document content.\n"
        "2. Answer based on the document content.\n"
        "3. If the answer is not in the documents, say so.\n"
        "4. Cite specific parts of the document when possible.\n"
        "5. For summary/analysis questions, read thoroughly and give structured answers."
    ))

    print("Chat started! Type 'exit' to quit.\n", flush=True)

    while True:
        try:
            q = input("\nYou: ")
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye!")
            break
        if q.strip().lower() in ("exit", "quit", "q"):
            print("Goodbye!")
            break
        if not q.strip():
            continue

        print("Assistant: ", end="", flush=True)
        for event in agent.stream(
            {"messages": [{"role": "user", "content": q}]},
            config={"configurable": {"thread_id": "docbot-session"}},
            stream_mode="values",
        ):
            messages = event.get("messages", [])
            if not messages:
                continue
            msg = messages[-1]
            if hasattr(msg, "type") and msg.type == "ai" and msg.content:
                tool_calls = getattr(msg, "tool_calls", None)
                if not tool_calls:
                    print(msg.content, end="", flush=True)
        print()

    # Token report
    print("\n" + "=" * 60)
    print("  Token Usage & Cost Report")
    print("=" * 60)
    pricing = {
        "deepseek": {"input": 0.5, "output": 2.0},
        "openai": {"input": 2.5, "output": 10.0},
        "anthropic": {"input": 3.0, "output": 15.0},
        "minimax": {"input": 0.5, "output": 2.0},
    }
    p = pricing.get(provider, pricing["deepseek"])
    input_tokens = len(document_text) // 4
    input_cost = (input_tokens / 1_000_000) * p["input"]
    print(f"Model          : {model_name}")
    print(f"Provider       : {provider}")
    print(f"Input tokens   : {input_tokens:,}")
    print(f"Input cost     : \u00a5{input_cost:.6f}")
    print("=" * 60)


if __name__ == "__main__":
    main()