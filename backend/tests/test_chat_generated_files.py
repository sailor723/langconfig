import asyncio
import sys
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


def test_generated_files_are_scoped_to_session(tmp_path):
    default_dir = tmp_path / "default"
    default_dir.mkdir()
    (default_dir / "report.md").write_text("hello", encoding="utf-8")
    (default_dir / "unrelated.md").write_text("other", encoding="utf-8")

    session = type("Session", (), {
        "tool_calls": [
            {"tool_name": "write_file", "arguments": {"file_path": "report.md"}},
            {"tool_name": "read_file", "arguments": {"file_path": "unrelated.md"}},
            {"tool_name": "write_file", "arguments": {"file_path": "report.md"}},
        ]
    })()
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
