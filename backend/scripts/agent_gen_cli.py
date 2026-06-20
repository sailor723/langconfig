#!/usr/bin/env python3
"""
agent-gen CLI — Thin CLI wrapper around LangConfigClient SDK.

Usage:
    # Natural language: describe what you want
    python scripts/agent_gen_cli.py create --name my-agent -q "data analysis, ticket classification and web search"

    # Or use explicit skill IDs:
    python scripts/agent_gen_cli.py create --name my-agent --skills ticket-classifier,data-analysis

    # With native tools (e.g. graphindex for PDF chat):
    python scripts/agent_gen_cli.py create --name doc-agent --skills pdf-chat --tools graphindex_search,graphindex_load

    # Dry-run to check which skills exist:
    python scripts/agent_gen_cli.py create --name test --skills a,b,c --dry-run

    # List all agents or skills:
    python scripts/agent_gen_cli.py list-agents
    python scripts/agent_gen_cli.py list-skills
"""
import argparse
import sys
from pathlib import Path

# langconfig_sdk is at project_root/lib/langconfig_sdk/
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "lib"))
from langconfig_sdk import LangConfigClient, LangConfigError


def resolve_skills(client, args):
    """Determine skill IDs from --query (natural language) or --skills (explicit)."""
    if args.query:
        print(f"🔄 Parsing query: \"{args.query}\"")
        print("    Using agent-gen to identify required skills...\n")
        skill_ids = client.parse_query_to_skills(args.query)
        print(f"    → Identified skills: {skill_ids}\n")
        return skill_ids

    # Fall back to explicit --skills
    skill_ids = [s.strip() for s in args.skills.split(",") if s.strip()]
    return skill_ids


def cmd_create(args):
    """Create an agent with auto-skill-generation."""
    client = LangConfigClient()

    # Resolve skill IDs from query or explicit list
    skill_ids = resolve_skills(client, args)

    if not skill_ids:
        print("❌ Could not determine any skills from input")
        sys.exit(1)

    # Determine extra native tools
    extra_tools = []
    if args.tools:
        extra_tools = [t.strip() for t in args.tools.split(",") if t.strip()]
    # Auto-add graphindex tools when pdf-chat skill is included
    if "pdf-chat" in skill_ids:
        for t in ["graphindex_search", "graphindex_load"]:
            if t not in extra_tools:
                extra_tools.append(t)
                print(f"    📎 Auto-added native tool: {t} (required by pdf-chat)")

    print(f"\n{'='*60}")
    print(f"  Agent:  {args.name}")
    print(f"  Skills: {skill_ids}")
    if extra_tools:
        print(f"  Tools:  {extra_tools}")
    print(f"{'='*60}\n")

    # Phase 1: Check
    print("📋 Phase 1: Checking skills...")
    existing = []
    missing = []
    for sid in skill_ids:
        exists = client.skill_exists(sid)
        print(f"    {'✅' if exists else '❌'} {sid}")
        if exists:
            existing.append(sid)
        else:
            missing.append(sid)

    if args.dry_run:
        print("\n   (dry-run, no changes)")
        return

    # Phase 2: Generate missing
    if missing and not args.skip_generate:
        print(f"\n🔧 Phase 2: Generating {len(missing)} missing skill(s)...")
        for sid in missing:
            print(f"\n    --- '{sid}' ---")
            try:
                client.create_skill(sid)
                print(f"    ✅ Created via API")
                existing.append(sid)
            except LangConfigError as e:
                print(f"    ❌ {e}")

        if not existing:
            print("\n❌ No skills available")
            sys.exit(1)

    # Phase 3: Create agent
    print(f"\n🚀 Phase 3: Creating agent '{args.name}'...")
    try:
        agent = client.create_agent(
            name=args.name,
            skills=existing,
            description=args.desc or f"Agent with: {', '.join(existing)}",
            extra_tools=extra_tools if extra_tools else None,
        )
        subagents = [s["name"] for s in agent.get("subagents", [])]
        print(f"    ✅ Agent ID={agent['id']}")
        print(f"    Subagents: {subagents}")
        print(f"\n{'='*60}")
        print(f"  DONE — test via Ctrl+K → '{args.name}'")
        print(f"{'='*60}")
    except LangConfigError as e:
        print(f"    ❌ {e}")
        sys.exit(1)


def cmd_list_agents(args):
    """List all deep agents."""
    client = LangConfigClient()
    agents = client.list_agents()
    if not agents:
        print("  (no agents)")
        return
    print(f"\n  {'ID':>4}  {'Name':<25}  Skills")
    print(f"  {'─'*4}  {'─'*25}  {'─'*30}")
    for a in agents:
        skills = ", ".join(a.get("config", {}).get("skills", []))
        print(f"  {a['id']:>4}  {a['name']:<25}  {skills}")


def cmd_list_skills(args):
    """List all skills."""
    client = LangConfigClient()
    skills = client.list_skills()
    if not skills:
        print("  (no skills)")
        return
    print(f"\n  {'Source':<12}  {'Skill ID':<30}  Name")
    print(f"  {'─'*12}  {'─'*30}  {'─'*30}")
    for s in skills:
        print(f"  {s.get('source_type','?'):<12}  {s['skill_id']:<30}  {s['name']}")


def main():
    parser = argparse.ArgumentParser(
        description="LangConfig Agent & Skill Manager",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    sub = parser.add_subparsers(dest="command", help="Available commands")

    # create
    p = sub.add_parser("create", help="Create an agent (auto-generate skills)")
    p.add_argument("--name", required=True)
    p.add_argument("--desc", default="")
    p.add_argument("-q", "--query", help='Natural language: "data analysis, ticket classification and web search"')
    p.add_argument("--skills", help="Comma-separated skill IDs (alternative to --query)")
    p.add_argument("--tools", help="Comma-separated extra native tools: graphindex_search,graphindex_load,doc_index_list")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--skip-generate", action="store_true")

    # list-agents
    sub.add_parser("list-agents", help="List all deep agents")

    # list-skills
    sub.add_parser("list-skills", help="List all skills")

    args = parser.parse_args()

    if args.command == "create":
        if not args.query and not args.skills:
            print("❌ Provide either --query (natural language) or --skills (explicit list)")
            sys.exit(1)
        cmd_create(args)
    elif args.command == "list-agents":
        cmd_list_agents(args)
    elif args.command == "list-skills":
        cmd_list_skills(args)
    else:
        parser.print_help()
        sys.exit(1)


if __name__ == "__main__":
    main()
