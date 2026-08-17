import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "learning" / "phase9"))

from api.chat.routes import list_session_generated_files


class _FakeQuery:
    def __init__(self, result):
        self._result = result

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return self._result


class _FakeDB:
    def __init__(self, session):
        self._session = session

    def query(self, model):
        return _FakeQuery(self._session)


class _FakeWorkspaceManager:
    def __init__(self, base_dir: Path):
        self.base_dir = base_dir

    def get_agent_workspace(self, agent_id: int) -> Path:
        workspace = self.base_dir / "agents" / f"agent_{agent_id}"
        workspace.mkdir(parents=True, exist_ok=True)
        return workspace

    def project_vault_key(self, db, project_id):
        """Mirror the real resolver: a fake project's number, else the id."""
        if project_id is None:
            return ""
        return str(getattr(db, "project_number", None) or project_id)

    def agent_vault_key(self, db, agent):
        """Mirror the real resolver: a fake agent's sanitized name, else id."""
        name = getattr(agent, "name", None)
        if name:
            return str(name).lower().replace(" ", "-")
        return f"agent_{getattr(agent, 'id', 'unknown')}"

    def resolve_agent_workspace(self, agent, project_id=None, vault_key=None, agent_key=None) -> Path:
        """Mirror the real resolver: custom workspace_path wins, else vault-
        scoped default, else legacy default."""
        custom = getattr(agent, "workspace_path", None)
        if custom and str(custom).strip():
            p = Path(str(custom).strip()).expanduser()
            if not p.is_absolute():
                if project_id is not None:
                    p = self.base_dir / "projects" / str(project_id) / p
                else:
                    p = self.base_dir / p
            p.mkdir(parents=True, exist_ok=True)
            return p
        if project_id is not None:
            vault = self.base_dir / "projects" / str(project_id) / "agents" / f"agent_{agent.id}"
            vault.mkdir(parents=True, exist_ok=True)
            return vault
        return self.get_agent_workspace(agent.id)

    def get_task_workspace(self, project_id, workflow_id, task_id) -> Path:
        return self.base_dir / "standalone" / f"workflow_{workflow_id}" / f"task_{task_id}"


def _make_session(**extra):
    now = datetime.now(timezone.utc)
    base = {
        # The fake doubles as both the ChatSession and (via _FakeDB.query)
        # the DeepAgentTemplate row resolved by _resolve_agent_workspace.
        "id": 0,
        "workspace_path": None,
        "tool_calls": [],
        "created_at": now - timedelta(hours=1),
        "updated_at": now,
    }
    base.update(extra)
    if base.get("id") == 0 and base.get("agent_id") is not None:
        base["id"] = base["agent_id"]
    return type("Session", (), base)()


def test_agent_workspace_is_primary_root(tmp_path):
    """All files under outputs/agents/agent_{id}/ are listed, no window needed."""
    agent_dir = tmp_path / "agents" / "agent_7"
    agent_dir.mkdir(parents=True)
    (agent_dir / "deck.html").write_text("<html/>", encoding="utf-8")
    (agent_dir / "data.csv").write_text("a,b\n", encoding="utf-8")

    session = _make_session(agent_id=7)
    db = _FakeDB(session)
    manager = _FakeWorkspaceManager(tmp_path)

    async def run():
        with patch(
            "services.workspace_manager.get_workspace_manager",
            return_value=manager,
        ):
            return await list_session_generated_files("session-1", db)

    result = asyncio.run(run())
    assert result["total_files"] == 2
    names = {f["filename"] for f in result["files"]}
    assert names == {"deck.html", "data.csv"}


def test_legacy_roots_still_scoped_to_session(tmp_path):
    default_dir = tmp_path / "default"
    default_dir.mkdir(parents=True)
    report_path = default_dir / "report.md"
    unrelated_path = default_dir / "unrelated.md"
    report_path.write_text("hello", encoding="utf-8")
    unrelated_path.write_text("other", encoding="utf-8")

    # Legacy fallback scan only surfaces files written inside the session
    # window, so unrelated.md (written hours before the session) is excluded
    # even though it sits in the same legacy root.
    now = datetime.now(timezone.utc)
    old_mtime = (now - timedelta(hours=3)).timestamp()
    os.utime(unrelated_path, (old_mtime, old_mtime))

    session = _make_session(
        agent_id=None,
        tool_calls=[
            {"tool_name": "write_file", "arguments": {"file_path": "report.md"}},
            {"tool_name": "read_file", "arguments": {"file_path": "unrelated.md"}},
            {"tool_name": "write_file", "arguments": {"file_path": "report.md"}},
        ],
    )
    db = _FakeDB(session)
    manager = _FakeWorkspaceManager(tmp_path)

    async def run():
        with patch(
            "services.workspace_manager.get_workspace_manager",
            return_value=manager,
        ):
            return await list_session_generated_files("session-1", db)

    result = asyncio.run(run())
    assert result["total_files"] == 1
    assert result["files"][0]["filename"] == "report.md"
    assert result["files"][0]["path"] == "default/report.md"


def test_folder_separation_uploads_excluded_generated_included(tmp_path):
    """Files are tagged with their workspace folder (generated/ · upload/ ·
    skills/ · other/ · workspace root) for the cascading view; the instruction
    docs (AGENTS.md / CLAUDE.md) are not listed."""
    agent_dir = tmp_path / "agents" / "agent_9"
    gen_dir = agent_dir / "generated"
    kb_dir = agent_dir / "upload"
    skills_dir = agent_dir / "skills"
    gen_dir.mkdir(parents=True)
    kb_dir.mkdir(parents=True)
    skills_dir.mkdir(parents=True)
    (gen_dir / "industry_report.md").write_text("report", encoding="utf-8")
    (kb_dir / "upload.pdf").write_bytes(b"pdf")
    (kb_dir / "data.csv").write_text("a,b\n", encoding="utf-8")
    (skills_dir / "my-skill").mkdir(parents=True, exist_ok=True)
    (skills_dir / "my-skill" / "SKILL.md").write_text("skill", encoding="utf-8")
    # .gitkeep placeholders are never shown.
    (gen_dir / ".gitkeep").write_text("", encoding="utf-8")
    (kb_dir / ".gitkeep").write_text("", encoding="utf-8")
    (agent_dir / "AGENTS.md").write_text("instructions", encoding="utf-8")
    (agent_dir / "CLAUDE.md").write_text("instructions", encoding="utf-8")
    # Legacy root-level generated file still surfaces (not a doc / upload).
    (agent_dir / "legacy_note.md").write_text("note", encoding="utf-8")

    session = _make_session(agent_id=9)
    db = _FakeDB(session)
    manager = _FakeWorkspaceManager(tmp_path)

    async def run():
        with patch(
            "services.workspace_manager.get_workspace_manager",
            return_value=manager,
        ):
            return await list_session_generated_files("session-1", db)

    result = asyncio.run(run())
    names = {f["filename"] for f in result["files"]}
    assert names == {
        "industry_report.md",
        "legacy_note.md",
        "upload.pdf",
        "data.csv",
        "SKILL.md",
    }
    by_name = {f["filename"]: f for f in result["files"]}
    assert by_name["industry_report.md"]["folder"] == "generated"
    assert by_name["upload.pdf"]["folder"] == "upload"
    assert by_name["data.csv"]["folder"] == "upload"
    assert by_name["SKILL.md"]["folder"] == "skills"
    assert by_name["legacy_note.md"]["folder"] == "workspace"
