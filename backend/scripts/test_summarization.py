#!/usr/bin/env python
"""Prove that conversation summarization compacts context — with numbers.

Runs a throwaway conversation through the REAL DeepAgent build path
(``DeepAgentFactory.create_deep_agent``) and prints, per turn, how many
messages were stored vs how many the model actually received, plus the token
count the provider reported. Two arms are compared so the effect is visible:

  arm "on"   - the agent's guardrails summarization threshold, set LOW here
  arm "off"  - summarization disabled in guardrails (what the team hit)

Only DeepAgents have this wired today: ``use_deepagents=False`` agents never
read ``guardrails.enable_summarization``, so there is nothing to test there.

How to read the output
----------------------
* ``state msgs``   - what the checkpointer holds (grows every turn)
* ``evicted``      - how many of those were folded into the running summary
* ``sent``         - messages the model actually got: 1 summary + the kept tail
* ``in_tokens``    - tokens the provider billed as input (system prompt + tools
                     + ``sent``); this is the number that must stay flat
* ``offload``      - the file evicted history is written to, under the agent
                     workspace (``/conversation_history/<thread>.md``) so the
                     agent can re-open it with its own file tools

Two things make a naive test look like "summarization is broken":
1. ``keep`` is measured in MESSAGES. Nothing is ever evicted while the stored
   history has <= keep messages, no matter how low the token threshold is.
2. The threshold is compared against the token count of the CONVERSATION
   (plus system prompt); a 1,500-token threshold is not reached by one turn.

Usage (from ``backend/``):
    .venv/bin/python scripts/test_summarization.py --agent-id 222
    .venv/bin/python scripts/test_summarization.py --agent-id 222 --turns 16 --threshold 1500 --keep 20
    .venv/bin/python scripts/test_summarization.py --agent-id 222 --arms on
    .venv/bin/python scripts/test_summarization.py --agent-id 222 --keep-workspace
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import pathlib
import shutil
import sys
import tempfile
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from langchain_core.messages import HumanMessage  # noqa: E402
from sqlalchemy import text  # noqa: E402

from core.workflows.checkpointing.manager import initialize_checkpointer  # noqa: E402
from db.database import SessionLocal  # noqa: E402
from models.deep_agent import DeepAgentConfig, DeepAgentTemplate  # noqa: E402
from services.deepagent_factory import DeepAgentFactory  # noqa: E402

FILLER = "Please acknowledge this message. "


def load_config(agent_id: int, *, enable_summarization: bool, threshold: int, keep: int) -> DeepAgentConfig:
    """Build the agent's config from its DB row, overriding the summarization knob."""
    db = SessionLocal()
    try:
        row = db.query(DeepAgentTemplate).filter(DeepAgentTemplate.id == agent_id).first()
        if row is None:
            raise SystemExit(f"agent {agent_id} not found in deep_agent_templates")
        cfg_dict = dict(row.config or {})
        guardrails = dict(row.guardrails_config or {})
        total = max(threshold * 2, threshold + 1000)
        guardrails["enable_summarization"] = enable_summarization
        guardrails["token_limits"] = {
            "summarization_threshold": threshold,
            "eviction_threshold": threshold + max(1, (total - threshold) // 2),
            "max_total_tokens": total,
            # Read by the factory: messages kept after compaction.
            "keep_last_messages": keep,
        }
        cfg_dict["guardrails"] = guardrails
        allowed = set(DeepAgentConfig.model_fields)
        return DeepAgentConfig(**{k: v for k, v in cfg_dict.items() if k in allowed})
    finally:
        db.close()


def cleanup_thread(thread_ids: list[str]) -> int:
    """Delete the throwaway threads so the test leaves no checkpoint baggage."""
    db = SessionLocal()
    try:
        removed = 0
        for table in ("checkpoints", "checkpoint_blobs", "checkpoint_writes"):
            for tid in thread_ids:
                res = db.execute(
                    text(f"delete from {table} where thread_id = :tid"), {"tid": tid}
                )
                removed += res.rowcount or 0
        db.commit()
        return removed
    finally:
        db.close()


async def run_arm(
    label: str,
    cfg: DeepAgentConfig,
    workspace: str,
    thread_id: str,
    turns: int,
    keep: int,
) -> dict:
    agent, _, _ = await DeepAgentFactory.create_deep_agent(
        config=cfg, project_id=None, task_id=None, context="",
        workspace_root=workspace, agent_id=None,
    )
    run_cfg = {"configurable": {"thread_id": thread_id}}
    message = f"{FILLER * 30}Reply with exactly one short acknowledgement."

    print(f"\n=== arm: {label} (keep={keep} messages, threshold={cfg.guardrails.token_limits['summarization_threshold']} tokens)")
    print(f"{'turn':>4} {'state msgs':>10} {'evicted':>8} {'sent':>5} {'in_tokens':>10} {'delta':>7} {'summary ch':>11}  offload")
    rows, prev_tokens, first_compaction = [], None, None
    for turn in range(1, turns + 1):
        res = await agent.ainvoke({"messages": [HumanMessage(content=f"Message {turn}. {message}")]}, run_cfg)
        usage = getattr(res["messages"][-1], "usage_metadata", None) or {}
        tokens = usage.get("input_tokens")
        state = await agent.aget_state(run_cfg)
        messages = state.values.get("messages", [])
        event = state.values.get("_summarization_event")

        if event:
            cutoff = event["cutoff_index"]
            evicted = cutoff
            sent = 1 + max(0, len(messages) - cutoff)   # 1 = the summary message
            summary_chars = len(str(event["summary_message"].content))
            offload = event.get("file_path") or "-"
            if first_compaction is None:
                first_compaction = {"turn": turn, "tokens": prev_tokens, "state": len(messages) - 2,
                                    "evicted": evicted, "sent": sent}
        else:
            evicted, sent, summary_chars, offload = 0, len(messages), 0, "-"

        delta = "" if prev_tokens is None or tokens is None else f"{tokens - prev_tokens:+d}"
        rows.append({"turn": turn, "state": len(messages), "evicted": evicted, "sent": sent,
                     "tokens": tokens, "delta": tokens - prev_tokens if prev_tokens and tokens else 0})
        if event or turn <= 2 or turn == turns:
            print(f"{turn:>4} {len(messages):>10} {evicted:>8} {sent:>5} {tokens if tokens else '?':>10} {delta:>7} {summary_chars:>11}  {offload}")
        prev_tokens = tokens

    path = pathlib.Path(workspace) / "conversation_history" / f"{thread_id}.md"
    print(f"offload file: {path} exists={path.exists()}"
          + (f" size={path.stat().st_size}B" if path.exists() else "  (nothing was evicted)"))
    return {"rows": rows, "first": first_compaction, "offload": path}


def summarise(label: str, result: dict) -> None:
    rows, first = result["rows"], result["first"]
    print(f"\n--- {label}: context before vs after compaction")
    if not first:
        growth = [r["delta"] for r in rows[1:] if r["delta"]]
        avg = sum(growth) / len(growth) if growth else 0
        print(f"    NEVER COMPACTED in {len(rows)} turns. input tokens "
              f"{rows[0]['tokens']} -> {rows[-1]['tokens']} ({avg:+.0f}/turn)")
        return
    before = next((r for r in rows if r["turn"] == first["turn"] - 1), rows[0])
    after = next((r for r in rows if r["turn"] == first["turn"]), rows[-1])
    print(f"    last turn before  : {before['state']:>3} messages stored, {before['tokens']:>7} input tokens")
    print(f"    first turn after  : {after['state']:>3} messages stored, {after['tokens']:>7} input tokens"
          f"  ({after['evicted']} evicted -> 1 summary + {after['sent'] - 1} kept)")
    tail = [r["delta"] for r in rows if r["turn"] > first["turn"] + 1 and r["delta"]]
    if tail:
        print(f"    growth after      : {sum(tail) / len(tail):+.0f} tokens/turn "
              f"(state still holds {rows[-1]['state']} messages)")


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--agent-id", type=int, default=222)
    parser.add_argument("--turns", type=int, default=14)
    parser.add_argument("--threshold", type=int, default=0,
                        help="summarization_threshold (tokens); 0 = auto (baseline + 400). "
                             "The counter includes the system prompt + tool schemas, so a "
                             "small literal like 1500 fires immediately while 60000 may "
                             "never fire in a short test.")
    parser.add_argument("--keep", type=int, default=20,
                        help="messages kept verbatim after compaction (default 20)")
    parser.add_argument("--arms", choices=("both", "on", "off"), default="both")
    parser.add_argument("--keep-workspace", action="store_true",
                        help="leave the workspace + offload file on disk for inspection")
    args = parser.parse_args()

    logging.getLogger().setLevel(logging.WARNING)   # keep the tables readable
    await initialize_checkpointer()

    explicit = args.threshold > 0
    stamp = int(time.time())
    arms = {"on": True, "off": False} if args.arms == "both" else {args.arms: args.arms == "on"}
    workspaces, threads, results = [], [], {}
    auto_threshold = args.threshold
    try:
        if "on" in arms and not explicit:
            # The trigger counts system prompt + tool schemas + conversation, so
            # the useful value is "what this agent already costs" + a margin.
            # Measure it with one throwaway turn.
            probe_cfg = load_config(args.agent_id, enable_summarization=True,
                                    threshold=10 ** 9, keep=args.keep)
            probe_ws = tempfile.mkdtemp(prefix="summtest-probe-")
            probe_tid = f"summtest-probe-{stamp}"
            workspaces.append(probe_ws)
            threads.append(probe_tid)
            probe = await run_arm("probe - baseline only", probe_cfg, probe_ws, probe_tid, 1, args.keep)
            baseline = probe["rows"][0]["tokens"] or 0
            auto_threshold = baseline + 400
            print(f"\nbaseline for this agent (system prompt + tool schemas + 1 message): {baseline} tokens")
            print(f"auto threshold: {auto_threshold} tokens  (override with --threshold N)")

        for label, enabled in arms.items():
            threshold = args.threshold if explicit else (auto_threshold if label == "on" else 1500)
            cfg = load_config(args.agent_id, enable_summarization=enabled,
                              threshold=threshold, keep=args.keep)
            workspace = tempfile.mkdtemp(prefix=f"summtest-{label}-")
            thread_id = f"summtest-{label}-{stamp}"
            workspaces.append(workspace)
            threads.append(thread_id)
            print(f"\nagent {args.agent_id} | model {cfg.model} | enable_summarization={enabled}")
            results[label] = await run_arm(label, cfg, workspace, thread_id, args.turns, args.keep)
            summarise(label, results[label])

        print("\nA real chat writes the same file into the agent's workspace:")
        print("    backend/outputs/agents/agent_<id>/conversation_history/<thread_id>.md")
        print("    find backend/outputs -path '*conversation_history*' -name '*.md'")
    finally:
        print(f"\ncleaned {cleanup_thread(threads)} checkpoint rows for {len(threads)} test thread(s)")
        if args.keep_workspace:
            for w in workspaces:
                print(f"kept workspace: {w}")
        else:
            for w in workspaces:
                shutil.rmtree(w, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
