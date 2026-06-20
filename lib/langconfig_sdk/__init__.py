#!/usr/bin/env python3
"""
LangConfig SDK — Python client library for the LangConfig API.

Usage:
    from langconfig_sdk import LangConfigClient

    client = LangConfigClient()
    skills = client.list_skills()
    agent = client.create_agent("my-agent", ["ticket-classifier", "data-analysis"])
    ...
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import requests


# ──────────────────────────────────────────────
#  Data Models
# ──────────────────────────────────────────────


@dataclass
class SkillInfo:
    skill_id: str
    name: str
    description: str
    tags: list[str] = field(default_factory=list)
    triggers: list[str] = field(default_factory=list)
    source_type: str = "personal"


@dataclass
class AgentInfo:
    id: int
    name: str
    description: str
    skills: list[str] = field(default_factory=list)
    subagents: list[dict] = field(default_factory=list)
    config: dict = field(default_factory=dict)
    lock_version: int = 1


@dataclass
class ChatResponse:
    message: str
    tool_calls: list[dict]
    session_id: str


# ──────────────────────────────────────────────
#  SDK Client
# ──────────────────────────────────────────────


class LangConfigError(Exception):
    """Base exception for LangConfig SDK errors."""


class LangConfigClient:
    """
    Python SDK for the LangConfig API.

    Wraps all backend endpoints with typed Python methods.
    Defaults to localhost:8765 — override with ``base_url``.
    """

    def __init__(self, base_url: str = "http://127.0.0.1:8765", timeout: int = 30):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._session = requests.Session()
        self._session.headers["Content-Type"] = "application/json"

    # ── Helpers ──

    def _url(self, path: str) -> str:
        return f"{self.base_url}{path}"

    def _request(self, method: str, path: str, **kw) -> Any:
        """Make a request, parse JSON, raise on error."""
        t = kw.pop("timeout", self.timeout)
        fn = getattr(self._session, method.lower())
        try:
            r = fn(self._url(path), timeout=t, **kw)
        except requests.ConnectionError as e:
            raise LangConfigError(f"Cannot connect to {self.base_url}: {e}") from e
        except requests.Timeout as e:
            raise LangConfigError(f"Request timed out after {t}s: {e}") from e

        if r.status_code >= 400:
            detail = r.text[:300]
            raise LangConfigError(
                f"HTTP {r.status_code} on {method.upper()} {path}: {detail}"
            )

        # Return None for empty 2xx
        if not r.text.strip():
            return None
        return r.json()

    # ── Skills API ──

    def list_skills(self, search: str | None = None) -> list[dict]:
        """List all skills, optionally filtered by search."""
        params = {"search": search} if search else {}
        return self._request("GET", "/api/skills", params=params)

    def get_skill(self, skill_id: str) -> dict:
        """Get detailed info about a single skill."""
        return self._request("GET", f"/api/skills/{skill_id}")

    def create_skill(
        self,
        skill_id: str,
        name: str | None = None,
        description: str | None = None,
        instructions: str | None = None,
        tags: list[str] | None = None,
        triggers: list[str] | None = None,
    ) -> dict:
        """Create a new skill in the database.

        If a skill with the same ``skill_id`` already exists, auto-increments
        the version number (e.g. ``"1.0.0"`` → ``"2.0.0"``) and updates in place.
        """
        if name is None:
            name = skill_id.replace("-", " ").title()
        if description is None:
            description = f"{name} - auto-generated skill"
        if instructions is None:
            instructions = (
                f"You are a {skill_id} specialist.\n"
                f"Step 1: Read the user input carefully.\n"
                f"Step 2: Apply {name} logic.\n"
                f"Step 3: Return the structured result.\n"
            )

        # Check if skill already exists → increment version
        version = "1.0.0"
        try:
            existing = self.get_skill(skill_id)
            if existing and existing.get("skill_id") == skill_id:
                cur = existing.get("version", "1.0.0")
                try:
                    major = int(cur.split(".")[0]) + 1
                    version = f"{major}.0.0"
                except (ValueError, IndexError):
                    version = "2.0.0"
        except LangConfigError:
            pass  # skill doesn't exist yet

        payload = {
            "skill_id": skill_id,
            "name": name,
            "description": description,
            "instructions": instructions,
            "tags": tags or [skill_id],
            "triggers": triggers or [f"use {skill_id}", skill_id],
            "version": version,
            "source_type": "personal",
        }
        return self._request("POST", "/api/skills", json=payload)

    def skill_exists(self, skill_id: str) -> bool:
        """Check if a skill exists in the database (by exact ID match on full list)."""
        try:
            skills = self.list_skills()
            return any(s["skill_id"] == skill_id for s in skills)
        except Exception:
            return False

    # ── Agents API ──

    def list_agents(self) -> list[dict]:
        """List all deep agents."""
        return self._request("GET", "/api/deepagents/")

    def get_agent(self, agent_id: int) -> dict:
        """Get a deep agent by ID."""
        return self._request("GET", f"/api/deepagents/{agent_id}")

    # ── Settings API ──

    def get_settings(self) -> dict:
        """Get application settings (default_model, temperature, etc.)."""
        return self._request("GET", "/api/settings/")

    def get_default_model(self) -> str:
        """Get the default model from DB settings.

        Checks in order:
          1. ``default_model`` from ``GET /api/settings/`` (General Settings)
          2. ``primary_model`` from ``GET /api/settings/model-defaults`` (Model Defaults)

        Raises ``LangConfigError`` if no model is configured in DB.
        """
        # Check General Settings first
        try:
            settings = self.get_settings()
            model = settings.get("default_model")
            if model:
                return model
        except Exception:
            pass

        # Fallback to Model Defaults
        try:
            defaults = self._request("GET", "/api/settings/model-defaults")
            model = defaults.get("primary_model")
            if model:
                return model
        except Exception:
            pass

        raise LangConfigError(
            "No default_model configured in settings. "
            "Go to Settings Panel → Model Defaults and set a primary model."
        )

    def create_agent(
        self,
        name: str,
        skills: list[str],
        description: str = "",
        model: str | None = None,
        system_prompt: str = "You are a helpful assistant with access to specialized skills.",
        native_tools: list[str] | None = None,
        extra_tools: list[str] | None = None,
        temperature: float = 0.7,
    ) -> dict:
        """Create a deep agent with the given skills.

        If an agent with the same ``name`` already exists, auto-appends a
        version suffix (``-v2``, ``-v3``, ...) to avoid name collisions.
        The ``version`` field in config is also set accordingly.

        If ``model`` is not provided, the default model from DB settings is used.
        ``skill_router_model`` is also auto-set to the same model so both
        "Bot LLM" and "Skill LLM" are populated in the UI.

        ``extra_tools`` can include tools like ``graphindex_search``,
        ``graphindex_load``, ``doc_index_list``, etc.
        """
        if model is None:
            model = self.get_default_model()
        if native_tools is None:
            native_tools = ["ls", "read_file", "write_file", "edit_file", "glob", "grep"]
        if extra_tools:
            # Merge extra tools, avoid duplicates
            for t in extra_tools:
                if t not in native_tools:
                    native_tools.append(t)

        # ── Auto-version: if name exists, append -v2, -v3, ... ──
        version = "1.0.0"
        try:
            agents = self.list_agents()
            existing_names = {a["name"] for a in agents}
            if name in existing_names:
                max_v = 1
                prefix = name
                for aname in existing_names:
                    if aname == name:
                        max_v = max(max_v, 1)
                    elif aname.startswith(prefix + "-v"):
                        try:
                            v = int(aname.split("-v")[-1])
                            max_v = max(max_v, v)
                        except ValueError:
                            pass
                version = f"{max_v + 1}.0.0"
                name = f"{prefix}-v{max_v + 1}"
        except Exception:
            pass

        config = {
            "model": model,
            "skill_router_model": model,
            "version": version,
            "system_prompt": system_prompt,
            "temperature": temperature,
            "use_deepagents": True,
            "use_local_sandbox": True,
            "skills": skills,
            "native_tools": native_tools,
            "tools": native_tools,
            "middleware": [
                {"type": "todo_list", "enabled": True, "config": {"auto_track": True}},
                {"type": "filesystem", "enabled": True, "config": {"auto_eviction": True, "eviction_threshold_bytes": 1000000}},
                {"type": "subagent", "enabled": True, "config": {"max_depth": 3, "max_concurrent": 5}},
            ],
            "backend": {"type": "state", "config": {}},
        }

        return self._request("POST", "/api/deepagents/", json={
            "name": name,
            "description": description or f"Agent v{version} with skills: {', '.join(skills)}",
            "category": "deep_agent",
            "config": config,
        })

    def update_agent(
        self,
        agent_id: int,
        config: dict,
        lock_version: int | None = None,
    ) -> dict:
        """Update a deep agent's config."""
        if lock_version is None:
            current = self.get_agent(agent_id)
            lock_version = current.get("lock_version", 1)
        return self._request("PUT", f"/api/deepagents/{agent_id}", json={
            "config": config,
            "lock_version": lock_version,
        })

    # ── Chat API ──

    def start_chat(self, agent_id: int) -> str:
        """Start a new chat session. Returns session_id."""
        data = self._request("POST", "/api/chat/start", json={"agent_id": agent_id})
        return data["session_id"]

    def send_message(
        self,
        session_id: str,
        message: str,
        timeout: int = 300,
    ) -> ChatResponse:
        """Send a message to a chat session (non-streaming). Returns ChatResponse."""
        data = self._request(
            "POST", "/api/chat/message",
            json={"session_id": session_id, "message": message},
            timeout=timeout,
        )
        return ChatResponse(
            message=data.get("message", ""),
            tool_calls=data.get("tool_calls", []),
            session_id=session_id,
        )

    def get_chat_history(self, session_id: str) -> list[dict]:
        """Get message history for a session."""
        data = self._request("GET", f"/api/chat/{session_id}/history")
        return data.get("messages", [])

    # ── Query Parsing (uses agent-gen to understand natural language) ──

    def parse_query_to_skills(
        self,
        query: str,
        agent_gen_id: int = 69,
    ) -> list[str]:
        """Parse a natural language query into skill IDs using agent-gen.

        Example:
            "create an agent for data analysis, ticket classification and web search"
            → ["data-analysis", "ticket-classifier", "web-search"]
        """
        prompt = (
            "Extract skill names from this description. "
            "Return ONLY a JSON array of kebab-case skill IDs. "
            "Examples: 'data analysis' → 'data-analysis', "
            "'ticket classification' → 'ticket-classifier', "
            "'code review' → 'code-review', "
            "'web search' → 'web-search'.\n\n"
            f"Description: {query}\n\n"
            "JSON array:"
        )

        sid = self.start_chat(agent_gen_id)
        resp = self.send_message(sid, prompt, timeout=120)

        # Try to parse JSON from response
        text = resp.message.strip()
        # Handle markdown code blocks
        if "```" in text:
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]

        import json as _json
        try:
            skills = _json.loads(text)
            if isinstance(skills, list):
                return [s.strip().lower().replace("_", "-") for s in skills]
        except _json.JSONDecodeError:
            pass

        # Fallback: simple keyword extraction
        words = query.lower().replace(",", " ").split()
        known = {
            "data": "data-analysis", "analysis": "data-analysis",
            "ticket": "ticket-classifier", "classifier": "ticket-classifier",
            "code": "code-review", "review": "code-review",
            "web": "web-search", "search": "web-search",
            "security": "security-review",
            "testing": "python-testing", "test": "python-testing",
            "summarize": "text-summarizer", "summary": "text-summarizer",
        }
        seen = set()
        result = []
        for w in words:
            if w in known and known[w] not in seen:
                seen.add(known[w])
                result.append(known[w])
        return result if result else [query.strip().replace(" ", "-").lower()]

    # ── High-Level Convenience ──

    def ensure_skill(
        self,
        skill_id: str,
        name: str | None = None,
        description: str | None = None,
        instructions: str | None = None,
    ) -> bool:
        """Check if a skill exists; if not, create it.
        Returns True if the skill exists or was created."""
        if self.skill_exists(skill_id):
            return True
        try:
            self.create_skill(skill_id, name, description, instructions)
            # Wait for DB propagation
            for _ in range(5):
                time.sleep(2)
                if self.skill_exists(skill_id):
                    return True
            # Optimistic: assume it was created
            return True
        except LangConfigError as e:
            raise LangConfigError(f"Failed to create skill '{skill_id}': {e}") from e

    def ensure_skills(self, skill_ids: list[str]) -> list[str]:
        """Ensure all skill IDs exist. Creates missing ones.
        Returns the list of available skill IDs."""
        available = []
        for sid in skill_ids:
            if self.ensure_skill(sid):
                available.append(sid)
        return available

    def generate_agent(
        self,
        name: str,
        skills: list[str],
        description: str = "",
        **kwargs,
    ) -> dict:
        """High-level: ensure all skills exist, then create the agent.
        Returns the agent dict."""
        available = self.ensure_skills(skills)
        if not available:
            raise LangConfigError("No skills available to create the agent")
        return self.create_agent(name, available, description=description, **kwargs)
