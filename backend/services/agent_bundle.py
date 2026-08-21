# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""
Agent bundle service — self-contained .langconfig export/import for DeepAgents.

v1.1 bundles the agent's FULL config (system_prompt + custom_prompt + custom_suffix,
model, tools, middleware, subagents, backend, guardrails, skills, runtime flags)
PLUS the definitions of every referenced custom tool and skill (SKILL.md + files),
so a shared agent is self-contained and runs on the recipient's machine.

Security: tool implementation_config is redacted (no API keys / secrets); the
``requires_api_key`` flag is preserved as a hint but keys stay local.

Import is idempotent for dependencies: existing custom tools / skills with the
same id are reused (never clobbered); the agent itself is auto-renamed on name
collision. v1.0 files remain importable (missing fields fall back to defaults).
"""
import copy
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional, Set

from fastapi import HTTPException
from sqlalchemy.orm import Session

from core.skills.sync import PERSONAL_SKILLS_ROOT, serialize_skill_md
from models.custom_tool import CustomTool, ToolType, ToolTemplateType
from models.deep_agent import DeepAgentConfig, DeepAgentTemplate
from models.skill import Skill, SkillSourceType

logger = logging.getLogger(__name__)

AGENT_BUNDLE_VERSION = "1.1"

# Substrings that mark a config value as sensitive → redacted on export.
_SENSITIVE_KEY_HINTS = ("api_key", "webhook_url", "connection_string", "token", "password", "secret")

# Config keys DeepAgentConfig does not model, but which must survive a
# round-trip (stored as extra keys on the agent.config JSON).
_EXTRA_CONFIG_KEYS = ("custom_prompt", "custom_suffix", "mcp_tools")


def _redact_sensitive_data(config: Any) -> Any:
    """Deep-redact sensitive values (API keys, webhook URLs, tokens, ...)."""
    cleaned = copy.deepcopy(config)

    def _clean(node: Any) -> None:
        if isinstance(node, dict):
            for key in list(node.keys()):
                if any(hint in key.lower() for hint in _SENSITIVE_KEY_HINTS):
                    node[key] = "REDACTED"
                else:
                    _clean(node[key])
        elif isinstance(node, list):
            for item in node:
                _clean(item)

    _clean(cleaned)
    return cleaned


def _known_config_fields() -> Set[str]:
    """Field names accepted by DeepAgentConfig (pydantic v1 vs v2)."""
    try:
        return set(DeepAgentConfig.model_fields.keys())
    except AttributeError:
        return set(DeepAgentConfig.__fields__.keys())


# =============================================================================
# Export helpers
# =============================================================================

def _tool_bundle_dict(tool: CustomTool) -> Dict[str, Any]:
    """Serialize a custom tool row for the bundle (secrets redacted).

    Carries every metadata flag that matters for the tool's behavior so a
    round-trip reconstructs the tool faithfully: ``requires_api_key`` (the
    env-var hint — the key VALUE stays local), ``is_builtin``, the DSH-style
    ``definition`` block (category/order/presentation), mode flags, etc.
    """
    return {
        "tool_id": tool.tool_id,
        "name": tool.name,
        "description": tool.description,
        "tool_type": tool.tool_type.value,
        "template_type": tool.template_type.value if tool.template_type else None,
        "implementation_config": _redact_sensitive_data(tool.implementation_config or {}),
        "input_schema": tool.input_schema,
        "output_format": tool.output_format,
        "validation_rules": tool.validation_rules,
        "is_template_based": tool.is_template_based,
        "is_advanced_mode": tool.is_advanced_mode,
        "category": tool.category,
        "tags": list(tool.tags or []),
        "version": tool.version,
        "requires_api_key": tool.requires_api_key,
        "is_builtin": tool.is_builtin,
        "definition": tool.definition,
    }


def _collect_skill_files(skill_dir: Path) -> Dict[str, str]:
    """Map relative path -> text content for every file under a skill directory.

    Skips binary files and Python cache artifacts so the bundle stays text-only
    and shareable.
    """
    files: Dict[str, str] = {}
    if not skill_dir.is_dir():
        return files
    for p in sorted(skill_dir.rglob("*")):
        if not p.is_file() or "__pycache__" in p.parts:
            continue
        try:
            head = p.read_bytes()[:8192]
            if b"\x00" in head:  # NUL byte → binary file, skip
                logger.debug(f"Skip binary skill file {p}")
                continue
            files[p.relative_to(skill_dir).as_posix()] = p.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            logger.warning(f"Skip unreadable skill file {p}: {e}")
    return files


def _skill_bundle_dict(skill: Skill) -> Dict[str, Any]:
    """Serialize a skill row + its full filesystem contents for the bundle."""
    return {
        "skill_id": skill.skill_id,
        "name": skill.name,
        "description": skill.description,
        "version": skill.version,
        "author": skill.author,
        "tags": list(skill.tags or []),
        "triggers": list(skill.triggers or []),
        "allowed_tools": list(skill.allowed_tools or []),
        "required_context": list(skill.required_context or []),
        "examples": skill.examples,
        "instructions": skill.instructions,
        "files": _collect_skill_files(Path(skill.source_path)) if skill.source_path else {},
    }


def _normalized_config_dict(config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize stored agent.config into a complete, export-safe dict.

    Fills every DeepAgentConfig field with defaults and preserves the extra
    prompt keys (custom_prompt / custom_suffix / mcp_tools) that the model
    does not model but the runtime and UI read from config.
    """
    known = _known_config_fields()
    try:
        validated = DeepAgentConfig(**{k: v for k, v in config.items() if k in known})
        # .dict() keeps str-mixin enums (ReasoningEffort) as enum members; emit
        # plain values so consumers never see "ReasoningEffort.HIGH".
        normalized = json.loads(validated.json())
    except Exception as e:
        logger.warning(f"Config normalization failed, exporting raw config: {e}")
        normalized = dict(config)
    for key in _EXTRA_CONFIG_KEYS:
        if config.get(key) is not None:
            normalized[key] = config[key]
    return normalized


def build_agent_bundle(agent: DeepAgentTemplate, db: Session) -> Dict[str, Any]:
    """
    Build a v1.1 .langconfig bundle for a DeepAgent.

    Embeds the full normalized config plus the definitions of every custom
    tool and skill referenced by ``config.custom_tools`` / ``config.skills``.
    """
    config = _normalized_config_dict(agent.config or {})
    bundle: Dict[str, Any] = {
        "version": AGENT_BUNDLE_VERSION,
        "export_type": "deepagent",
        "exported_at": datetime.utcnow().isoformat() + "Z",
        "agent": {
            "name": agent.name,
            "description": agent.description,
            "category": agent.category,
            "base_template_id": agent.base_template_id,
            "version": agent.version,
            "config": config,
        },
        "custom_tools": {},
        "skills": {},
    }

    # Embed referenced custom tools (user tools only — builtins are seeded everywhere).
    for tool_id in config.get("custom_tools") or []:
        tool = db.query(CustomTool).filter(CustomTool.tool_id == tool_id).first()
        if tool:
            bundle["custom_tools"][tool_id] = _tool_bundle_dict(tool)
        else:
            logger.warning(f"Agent '{agent.name}' references missing custom tool '{tool_id}'")

    # Embed referenced skills (row + SKILL.md + any other files).
    for skill_id in config.get("skills") or []:
        skill = db.query(Skill).filter(Skill.skill_id == skill_id).first()
        if skill:
            bundle["skills"][skill_id] = _skill_bundle_dict(skill)
        else:
            logger.warning(f"Agent '{agent.name}' references missing skill '{skill_id}'")

    return bundle


# =============================================================================
# Import helpers
# =============================================================================

def _import_custom_tool(tool_id: str, tool_data: Dict[str, Any], db: Session) -> bool:
    """Create a custom tool from bundle data; reuse silently if it already exists."""
    existing = db.query(CustomTool).filter(CustomTool.tool_id == tool_id).first()
    if existing:
        logger.info(f"Reusing existing custom tool '{tool_id}'")
        return False
    db.add(CustomTool(
        tool_id=tool_id,
        name=tool_data.get("name", tool_id),
        description=tool_data.get("description") or f"Imported tool '{tool_id}'",
        tool_type=ToolType(tool_data["tool_type"]),
        template_type=ToolTemplateType(tool_data["template_type"]) if tool_data.get("template_type") else None,
        implementation_config=tool_data.get("implementation_config") or {},
        input_schema=tool_data.get("input_schema") or {},
        output_format=tool_data.get("output_format", "string"),
        validation_rules=tool_data.get("validation_rules"),
        is_template_based=tool_data.get("is_template_based", True),
        is_advanced_mode=tool_data.get("is_advanced_mode", False),
        category=tool_data.get("category"),
        tags=tool_data.get("tags", []),
        version=tool_data.get("version", "1.0.0"),
        # Preserve the API-key hint (the KEY VALUE is redacted on export and
        # never crosses the wire — the user must re-enter it locally) and the
        # builtin/mode flags so the imported tool behaves like the source.
        requires_api_key=tool_data.get("requires_api_key"),
        is_builtin=tool_data.get("is_builtin", False),
        definition=tool_data.get("definition") or None,
    ))
    return True


def _import_skill(skill_id: str, skill_data: Dict[str, Any], db: Session) -> bool:
    """
    Create a personal skill from bundle data; reuse silently if it already exists.

    Writes the bundled files (SKILL.md + extras) under PERSONAL_SKILLS_ROOT so the
    runtime FilesystemBackend can read them, then inserts the indexed DB row.
    """
    existing = db.query(Skill).filter(Skill.skill_id == skill_id).first()
    if existing:
        logger.info(f"Reusing existing skill '{skill_id}'")
        return False

    skill_dir = PERSONAL_SKILLS_ROOT / skill_id
    skill_dir.mkdir(parents=True, exist_ok=True)

    files = skill_data.get("files") or {}
    if not files:
        # Fallback for bundles without files: rebuild SKILL.md from row fields.
        frontmatter = {k: v for k, v in skill_data.items() if k in (
            "name", "description", "version", "author", "tags", "triggers",
            "allowed_tools", "required_context", "examples") and v is not None}
        frontmatter.setdefault("name", skill_id)
        body = skill_data.get("instructions") or ""
        if skill_data.get("examples"):
            body = f"## Instructions\n\n{body}\n\n## Examples\n\n{skill_data['examples']}"
        else:
            body = f"## Instructions\n\n{body}"
        files = {"SKILL.md": serialize_skill_md(frontmatter, body)}

    for rel, content in files.items():
        target = skill_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")

    db.add(Skill(
        skill_id=skill_id,
        name=skill_data.get("name", skill_id),
        description=skill_data.get("description") or f"Imported skill '{skill_id}'",
        version=skill_data.get("version", "1.0.0"),
        author=skill_data.get("author", "User"),
        source_type=SkillSourceType.PERSONAL,
        source_path=str(skill_dir),
        tags=skill_data.get("tags", []),
        triggers=skill_data.get("triggers", []),
        allowed_tools=skill_data.get("allowed_tools"),
        required_context=skill_data.get("required_context", []),
        instructions=skill_data.get("instructions", ""),
        examples=skill_data.get("examples"),
        file_modified_at=datetime.utcnow(),
    ))
    return True


def _map_config(agent_data: Dict[str, Any], version: str) -> Dict[str, Any]:
    """Map the bundle's agent payload into a config dict, preserving extras."""
    if version == "1.1":
        config = dict(agent_data.get("config") or {})
        for key in _EXTRA_CONFIG_KEYS:
            if agent_data.get(key) is not None:
                config[key] = agent_data[key]
        return config

    # v1.0 legacy mapping (config fields lived at the top level).
    config = {
        "model": agent_data.get("model"),
        "temperature": agent_data.get("temperature", 0.7),
        "max_tokens": agent_data.get("max_tokens"),
        "system_prompt": agent_data.get("system_prompt", ""),
        "tools": agent_data.get("tools", []),
        "native_tools": agent_data.get("native_tools", []),
        "cli_tools": agent_data.get("cli_tools", []),
        "middleware": agent_data.get("middleware", []),
        "subagents": agent_data.get("subagents", []),
        "backend": agent_data.get("backend", {}),
        "guardrails": agent_data.get("guardrails", {}),
    }
    for key in _EXTRA_CONFIG_KEYS:
        if agent_data.get(key) is not None:
            config[key] = agent_data[key]
    return config


def _unique_agent_name(name: str, db: Session) -> str:
    """Auto-rename on collision: 'X' -> 'X (2)' -> 'X (3)' ..."""
    base = name.strip() or "Imported Agent"
    candidate = base
    counter = 2
    while db.query(DeepAgentTemplate).filter(DeepAgentTemplate.name == candidate).first():
        candidate = f"{base} ({counter})"
        counter += 1
    return candidate


def import_agent_bundle(
    langconfig: Dict[str, Any],
    db: Session,
    project_id: Optional[int] = None,
) -> DeepAgentTemplate:
    """
    Import a .langconfig bundle (v1.0 or v1.1) as a new DeepAgent.

    Creates any embedded custom tools and skills first (reusing same-name
    ones), then the agent with its full config restored and a unique name.
    All mutations share one transaction — committed once at the end.

    ``project_id`` is the active project at import time, forwarded by
    the API layer (``ImportRequest.project_id``). When set, the new
    agent's workspace is resolved under that project's vault (so
    e.g. ``<vault>/projects/<slug>/agents/agent_<id>``) rather than the
    legacy fallback ``<output>/agents/agent_<id>``. The chat path can
    still re-bind to a different project on every session via
    ``chat_sessions.project_id``.

    After the row is inserted (and ``db.refresh`` has populated its real id),
    we resolve the new agent's workspace and re-bake the identity block
    in both ``config.system_prompt`` and ``agent_docs`` via
    ``rebake_agent_identity``. Without this step the imported agent would
    carry the SOURCE agent's id baked into its prompt + AGENTS.md +
    CLAUDE.md, which surfaces on the next chat ("I'm Agent 159" — wrong,
    the agent is now 187). The re-bake mutates in place and we commit
    once at the end so the fix is atomic with the import.
    """
    version = langconfig.get("version")
    if version not in ("1.0", "1.1") or langconfig.get("export_type") != "deepagent":
        raise HTTPException(status_code=400, detail="Invalid .langconfig format")

    agent_data = langconfig.get("agent") or {}
    if not agent_data or not agent_data.get("name"):
        raise HTTPException(status_code=400, detail="Invalid .langconfig: missing agent name")

    # 1) Dependencies first — custom tools and skills (v1.1+).
    for tool_id, tool_data in (langconfig.get("custom_tools") or {}).items():
        _import_custom_tool(tool_id, tool_data, db)
    for skill_id, skill_data in (langconfig.get("skills") or {}).items():
        _import_skill(skill_id, skill_data, db)

    # 2) Build + validate the config, preserving extra prompt keys.
    config_dict = _map_config(agent_data, version)
    known = _known_config_fields()
    config = DeepAgentConfig(**{k: v for k, v in config_dict.items() if k in known})
    # json round-trip keeps enums as plain values in the stored payload.
    config_payload = json.loads(config.json())
    for key in _EXTRA_CONFIG_KEYS:
        if config_dict.get(key) is not None:
            config_payload[key] = config_dict[key]

    # 3) Create the agent (auto-renamed on name collision).
    agent = DeepAgentTemplate(
        name=_unique_agent_name(agent_data["name"], db),
        description=agent_data.get("description"),
        category=agent_data.get("category", "research"),
        base_template_id=agent_data.get("base_template_id"),
        config=config_payload,
        middleware_config=[m.dict() for m in config.middleware] if config.middleware else [],
        subagents_config=[s.dict() for s in config.subagents] if config.subagents else [],
        backend_config=config.backend.dict() if config.backend else {},
        guardrails_config=config.guardrails.dict() if config.guardrails else {},
        is_community=True,  # Mark as imported
    )
    db.add(agent)
    db.commit()
    db.refresh(agent)
    logger.info(f"Imported DeepAgent: {agent.name} (id={agent.id})")

    # 4) Re-bake the identity block with the NEW agent's id + workspace.
    # Must run after db.refresh so agent.id is populated. The helper
    # mutates agent.config + agent.agent_docs in place and returns True
    # when it actually changed something.
    from core.agents.identity import rebake_agent_identity
    from services.workspace_manager import WorkspaceManager, get_workspace_manager
    from sqlalchemy.orm.attributes import flag_modified
    ws_mgr = get_workspace_manager()
    ws_root = str(ws_mgr.resolve_agent_workspace(
        agent,
        project_id,
        vault_key=WorkspaceManager.project_vault_key(db, project_id) or None,
        agent_key=None,
    ))
    if rebake_agent_identity(agent, ws_root):
        flag_modified(agent, "config")
        flag_modified(agent, "agent_docs")
        db.commit()
        logger.info(
            f"Re-baked identity for imported agent "
            f"{agent.name!r} (id={agent.id}, workspace={ws_root})"
        )
    return agent
