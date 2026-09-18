"""Phase 1 产品设计 Agent 运行入口。"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import yaml
from deepagents import create_deep_agent
from deepagents.backends import FilesystemBackend
from dotenv import load_dotenv
from langchain.chat_models import init_chat_model


MODULE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = MODULE_DIR.parents[1]


def load_environment() -> None:
    """加载项目根目录下的环境变量。"""
    load_dotenv(PROJECT_ROOT / ".env")


def build_model():
    """Initialize chat model using environment variables (Agnes/OpenAI-compatible)."""
    model_name = os.environ.get("PHASE1_MODEL_NAME", "agnes-2.0-flash")
    temperature = float(os.environ.get("PHASE1_MODEL_TEMPERATURE", "0.0"))
    model_timeout_seconds = float(os.environ.get("PHASE1_MODEL_TIMEOUT_SECONDS", "60"))
    model_max_retries = int(os.environ.get("PHASE1_MODEL_MAX_RETRIES", "2"))
    return init_chat_model(
        model=model_name,
        model_provider="openai",
        base_url=os.getenv("AGNES_BASE_URL"),
        api_key=os.getenv("AGNES_API_KEY"),
        temperature=temperature,
        timeout=model_timeout_seconds,
        max_retries=model_max_retries,
    )


def load_subagents(config_path: Path) -> list[dict]:
    """从 YAML 中加载子 Agent 配置。"""
    with config_path.open(encoding="utf-8") as file:
        config = yaml.safe_load(file)

    subagents: list[dict] = []
    for name, spec in config.items():
        subagent = {
            "name": name,
            "description": spec["description"],
            "system_prompt": spec["system_prompt"],
            "prompt": spec["system_prompt"],
        }
        if spec.get("model"):
            subagent["model"] = spec["model"]
        subagents.append(subagent)
    return subagents


def load_system_prompt() -> str:
    """读取全局 Agent 规则文件作为系统提示词。"""
    return (MODULE_DIR / "AGENTS.md").read_text(encoding="utf-8")


def ensure_artifact_dir() -> None:
    """确保产物目录存在。"""
    (MODULE_DIR / "artifacts").mkdir(parents=True, exist_ok=True)


def create_phase1_agent():
    """创建 Phase 1 产品设计 Agent。"""
    return create_deep_agent(
        model=build_model(),
        system_prompt=load_system_prompt(),
        subagents=load_subagents(MODULE_DIR / "subagents.yaml"),
        backend=FilesystemBackend(root_dir=MODULE_DIR),
        name="phase1-product-design-agent",
    )


def main() -> None:
    """直接运行 Phase 1 Agent（无子进程 / 无 SIGALRM）。"""
    load_environment()
    ensure_artifact_dir()

    user_task = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else (
        "客户已写好一份 PRD（artifacts/prd.md），是关于 ERP 运营数据分析 Agent 的。"
        "请读取这份 PRD，理解其内容，然后基于 PRD 生成系统提示词并写入 artifacts/system_prompt.md，"
        "再对系统提示词进行评审，将评审结果写入 artifacts/system_prompt_review.md。"
    )

    print("Creating agent...", flush=True)
    agent = create_phase1_agent()
    print("Invoking agent with streaming...\n", flush=True)

    all_messages = []
    last_msg_count = 0
    final_content = None

    for event in agent.stream(
        {"messages": [{"role": "user", "content": user_task}]},
        stream_mode="values",
    ):
        messages = event.get("messages", [])
        if not messages:
            continue

        # Detect new messages since last step
        new_msgs = messages[last_msg_count:]
        last_msg_count = len(messages)

        for msg in new_msgs:
            all_messages.append(msg)
            if not hasattr(msg, "type"):
                continue

            if msg.type == "ai":
                tool_calls = getattr(msg, "tool_calls", None)
                if tool_calls:
                    for tc in tool_calls:
                        tool_name = tc.get("name", "unknown")
                        tool_args = tc.get("args", {})
                        if tool_name == "task":
                            subagent = tool_args.get("subagent_type", tool_args.get("name", "?"))
                            desc = tool_args.get("description", "")[:120]
                            print(f"  🔧 [Tool] task -> {subagent}", flush=True)
                            if desc:
                                print(f"         {desc}", flush=True)
                        elif tool_name == "read_file":
                            print(f"  📖 [Tool] read_file: {tool_args.get('file_path', '?')}", flush=True)
                        elif tool_name == "write_file":
                            path = tool_args.get("file_path", "?")
                            print(f"  ✏️  [Tool] write_file: {path}", flush=True)
                        else:
                            print(f"  🔧 [Tool] {tool_name}", flush=True)
                if msg.content:
                    preview = msg.content[:160].replace("\n", " ")
                    suffix = "..." if len(msg.content) > 160 else ""
                    print(f"  💬 [AI] {preview}{suffix}", flush=True)
                    final_content = msg.content

            elif msg.type == "tool":
                content = (msg.content or "")[:120]
                if getattr(msg, "name", None) == "task":
                    print(f"  📝 [SubAgent] 返回", flush=True)
                    if content:
                        print(f"     {content}", flush=True)
                elif content:
                    print(f"  📊 [Tool Result] {content}", flush=True)

    print("\n=== ✅ Agent 执行完成 ===", flush=True)

    if final_content:
        print("\n" + "=" * 80)
        print("  Agent Response")
        print("=" * 80)
        print(final_content)

    # --- Token Usage & Cost Report ---
    print()
    print("=" * 80)
    print("  Token Usage & Cost Report")
    print("=" * 80)

    model_provider = os.environ.get("PHASE1_MODEL_PROVIDER", "openai")
    model_name = os.environ.get("PHASE1_MODEL_NAME", "agnes-2.0-flash")

    PRICING = {
        "agnes":     {"input": 0.0, "output": 0.0},
        "deepseek":  {"input": 0.5, "output": 2.0},
        "openai":    {"input": 2.5, "output": 10.0},
        "anthropic": {"input": 3.0, "output": 15.0},
        "minimax":   {"input": 0.5, "output": 2.0},
    }
    # Use "agnes" pricing if the model name contains "agnes", otherwise use provider-based pricing
    if "agnes" in model_name.lower():
        pricing = PRICING["agnes"]
    else:
        pricing = PRICING.get(model_provider, PRICING["deepseek"])

    print(f"Model Provider : {model_provider}")
    print(f"Model Name     : {model_name}")
    if pricing["input"] == 0 and pricing["output"] == 0:
        print(f"Cost           : Free (Agnes)")
    else:
        print(f'Input Price    : \xa5{pricing["input"]}/1M tokens')
        print(f'Output Price   : \xa5{pricing["output"]}/1M tokens')
    print()

    seen_ids = set()
    input_tokens = 0
    output_tokens = 0
    total_tokens = 0
    call_count = 0

    for msg in all_messages:
        msg_id = id(msg)
        if msg_id in seen_ids:
            continue
        seen_ids.add(msg_id)

        um = getattr(msg, "usage_metadata", None)
        if um:
            inp = um.get("input_tokens", 0) or 0
            out = um.get("output_tokens", 0) or 0
            tot = um.get("total_tokens", 0) or 0
            input_tokens += inp
            output_tokens += out
            total_tokens += tot
            call_count += 1

    input_cost = (input_tokens / 1_000_000) * pricing["input"]
    output_cost = (output_tokens / 1_000_000) * pricing["output"]
    total_cost = input_cost + output_cost

    print('=' * 60)
    print(f"  {'Item':<30} {'Count':>12}")
    print('=' * 60)
    print(f'  {"LLM Calls":<30} {call_count:>12,}')
    print(f'  {"Input Tokens":<30} {input_tokens:>12,}')
    print(f'  {"Output Tokens":<30} {output_tokens:>12,}')
    print(f'  {"Total Tokens":<30} {total_tokens:>12,}')
    print('-' * 60)
    print(f'  {"Input Cost (¥)":<30} {input_cost:>12.6f}')
    print(f'  {"Output Cost (¥)":<30} {output_cost:>12.6f}')
    print(f'  {"Total Cost (¥)":<30} {total_cost:>12.6f}')
    print('=' * 60)

    if call_count == 0:
        print()
        print("WARNING: No usage_metadata detected. Possible causes:")
        print("  - Model provider did not return token stats")
        print("  - Model does not support token stats")
        print("  - Agent did not make any LLM calls")
    print()

    # --- File existence check ---
    artifacts_dir = MODULE_DIR / "artifacts"
    expected = ["system_prompt.md", "system_prompt_review.md"]
    all_ok = True
    for fname in expected:
        fpath = artifacts_dir / fname
        if fpath.exists():
            size = len(fpath.read_text(encoding="utf-8"))
            print(f"  ✅ {fname} exists ({size:,} chars)")
        else:
            print(f"  ❌ {fname} NOT FOUND — Agent may have failed to write it.")
            all_ok = False
    if all_ok:
        print("\nAll expected artifacts are in place.")
    else:
        print(f"\nWARNING: Some artifacts are missing. Check {artifacts_dir}")

    print()
    print("生成的系统提示词请查看：")
    print(f"- {MODULE_DIR / 'artifacts' / 'system_prompt.md'}")
    print(f"- {MODULE_DIR / 'artifacts' / 'system_prompt_review.md'}")


if __name__ == "__main__":
    main()
