"""Skill parameters — the same skill, configured per agent.

Why this exists. `config.skills` says WHICH skills an agent may read; it never said what they are
pointed AT. So "build an ontology" and "edit an ontology" had to learn their database and their ontology
from somewhere else: a `datasource` field on the agent, a workbench contract block, or worse, a sentence
in the prompt. That is the wrong place — the parameter belongs to the SKILL (it needs a database and an
ontology folder), and its VALUE belongs to the agent that pins it.

So a skill declares the parameters it needs, in its frontmatter:

    params:
      datasource:  {label: 数据库,    required: true,  default_from: agent.datasource,
                    description: which database this ontology is built from}
      ontology_key: {label: 本体,      required: true,
                    description: the folder under ontologies/ this agent works on}
      profile:     {label: profile 文件, required: false, default: "{ontology_key}_settings.json"}

and an agent supplies their values once:

    config.skill_params = {
      "build-ontology-from-db": {"datasource": "logistics", "ontology_key": "logistics"},
      "answer-ontology-question": {"ontology_key": "logistics", "workbench": "http://127.0.0.1:8098"},
    }

Two things then happen, both mechanical:

1. a **`Skill parameters` block** is appended to the system prompt — the values are stated once, where
   the agent cannot miss them, instead of being inferred from a path;
2. a **`params.json`** is written next to each pinned skill's SKILL.md (`/skills/<source>/<id>/params.json`),
   so the skill's own scripts can read the configured values from disk instead of parsing prose.

A required parameter with no value and no default **fails the build by name**. Filling in a silent default
would mean an agent building into the wrong ontology, which is precisely the failure this removes.
"""
from __future__ import annotations

import json
import logging
import pathlib
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

BUILTIN_ROOT = pathlib.Path(__file__).resolve().parents[2] / "skills" / "builtin"
PARAMS_FILE = "params.json"


def _frontmatter(skill_md: pathlib.Path) -> Dict[str, Any]:
    if not skill_md.is_file():
        return {}
    try:
        from core.skills.sync import parse_skill_md

        frontmatter, _body = parse_skill_md(skill_md.read_text(encoding="utf-8"))
        return frontmatter or {}
    except Exception as exc:                                    # noqa: BLE001
        logger.warning("could not read skill frontmatter from %s: %s", skill_md, exc)
        return {}


def declared(skill_md: pathlib.Path) -> Dict[str, Dict[str, Any]]:
    """The `params:` a skill declares (empty when it declares none)."""
    params = _frontmatter(skill_md).get("params") or {}
    if not isinstance(params, dict):
        return {}
    return {str(k): (v if isinstance(v, dict) else {}) for k, v in params.items()}


def _fill_defaults(spec: Dict[str, Dict[str, Any]], values: Dict[str, Any]) -> Dict[str, Any]:
    """Expand `{other_param}` placeholders inside defaults (e.g. "{ontology_key}_settings.json")."""
    out = dict(values)
    for name, declared_spec in spec.items():
        if out.get(name) in (None, ""):
            default = declared_spec.get("default")
            if isinstance(default, str) and "{" in default:
                try:
                    default = default.format(**{k: v for k, v in out.items() if v is not None})
                except (KeyError, IndexError):
                    continue
            if default not in (None, ""):
                out[name] = default
    return out


def resolve(agent_id: Optional[int], pins: list[str], skill_params: Optional[Dict[str, Any]],
            agent_config: Optional[Dict[str, Any]] = None) -> tuple[Dict[str, Dict[str, Any]], list[str]]:
    """Values per pinned skill, plus the list of problems (missing required parameters).

    Only skills that DECLARE parameters are touched: a skill with no `params:` frontmatter keeps
    working exactly as before, which is what makes this additive.
    """
    cfg = agent_config or {}
    supplied = skill_params or {}
    resolved: Dict[str, Dict[str, Any]] = {}
    problems: list[str] = []

    for pin in pins or []:
        skill_md = BUILTIN_ROOT / pin / "SKILL.md"
        spec = declared(skill_md)
        if not spec:
            continue
        values = dict(supplied.get(pin) or {})
        # a parameter may default from the agent's own config (datasource is the obvious one)
        for name, declared_spec in spec.items():
            if values.get(name) in (None, "") and declared_spec.get("default_from"):
                source = str(declared_spec["default_from"])
                if source.startswith("agent."):
                    fallback = cfg.get(source.split(".", 1)[1])
                    if fallback not in (None, ""):
                        values[name] = fallback
        values = _fill_defaults(spec, values)
        missing = [n for n, s in spec.items() if s.get("required") and values.get(n) in (None, "")]
        if missing:
            problems.append(
                f"skill {pin!r} needs {', '.join(missing)} — set config.skill_params[{pin!r}]"
                + (f" (agent {agent_id})" if agent_id else ""))
            continue
        resolved[pin] = values
    return resolved, problems


def render_block(resolved: Dict[str, Dict[str, Any]]) -> str:
    """The system-prompt section: the configured values, stated once."""
    if not resolved:
        return ""
    lines = [
        "\n\n# Skill parameters (configured for this agent)\n",
        "These are the values your skills are pointed at. They come from this agent's configuration, "
        "not from a path you infer — use them as given, and do not re-derive them from a folder name "
        "or a workspace path.\n",
    ]
    for skill, values in resolved.items():
        lines.append(f"- **{skill}**\n")
        for name, value in values.items():
            lines.append(f"  - `{name}` = `{value}`\n")
    lines.append(
        "- The same values are on disk at `/skills/<source>/<skill>/params.json`; a skill whose "
        "instructions say to read its parameters reads that file instead of asking.\n")
    return "".join(lines)


def write_params(skill_dir: pathlib.Path, skill: str, values: Dict[str, Any]) -> Optional[pathlib.Path]:
    """Persist one skill's values next to its SKILL.md, so its scripts can read them."""
    try:
        target = pathlib.Path(skill_dir) / PARAMS_FILE
        target.write_text(json.dumps({"skill": skill, **values}, ensure_ascii=False, indent=1) + "\n",
                          encoding="utf-8")
        return target
    except OSError as exc:
        logger.warning("could not write %s for skill %s: %s", PARAMS_FILE, skill, exc)
        return None
