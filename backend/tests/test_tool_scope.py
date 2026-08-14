# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Regression tests for cross-project custom-tool isolation.

load_custom previously queried CustomTool by tool_id alone, so any agent
could load any custom tool by ID regardless of project scope. The fix adds
a scope predicate: global (project_id NULL) / same-project / builtin /
public tools load; other projects' private tools do not.
"""
import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from core.agents.tool_loader import _custom_tool_scope_filter
from models.custom_tool import CustomTool
from db.database import Base


@pytest.fixture
def sqlite_session():
    engine = create_engine("sqlite:///:memory:")
    # Only the custom_tools table is needed; SQLite FK enforcement is off
    # by default so the projects FK is not an obstacle.
    Base.metadata.create_all(bind=engine, tables=[CustomTool.__table__])
    Session = sessionmaker(bind=engine)
    session = Session()

    def _mk(tool_id, project_id, is_builtin=False, is_public=False):
        session.add(CustomTool(
            tool_id=tool_id,
            name=tool_id,
            description="test",
            tool_type="api",
            is_builtin=is_builtin,
            is_public=is_public,
            project_id=project_id,
            input_schema={},
            implementation_config={"url_template": "https://example.com", "method": "GET"},
        ))

    _mk("other-project-tool", project_id=99)
    _mk("same-project-tool", project_id=7)
    _mk("global-tool", project_id=None)
    _mk("builtin-tool", project_id=99, is_builtin=True)
    _mk("public-tool", project_id=99, is_public=True)
    session.commit()
    return session


def _loadable_ids(session, project_id):
    rows = session.execute(
        select(CustomTool).where(_custom_tool_scope_filter(project_id))
    ).scalars().all()
    return {r.tool_id for r in rows}


def test_cross_project_tool_not_loadable(sqlite_session):
    ids = _loadable_ids(sqlite_session, project_id=7)
    assert "other-project-tool" not in ids


def test_same_project_tool_loadable(sqlite_session):
    ids = _loadable_ids(sqlite_session, project_id=7)
    assert "same-project-tool" in ids


def test_global_tool_loadable(sqlite_session):
    ids = _loadable_ids(sqlite_session, project_id=7)
    assert "global-tool" in ids


def test_builtin_tool_loadable_across_projects(sqlite_session):
    ids = _loadable_ids(sqlite_session, project_id=7)
    assert "builtin-tool" in ids


def test_public_tool_loadable_across_projects(sqlite_session):
    ids = _loadable_ids(sqlite_session, project_id=7)
    assert "public-tool" in ids


def test_other_project_sees_only_its_own(sqlite_session):
    ids = _loadable_ids(sqlite_session, project_id=99)
    assert "other-project-tool" in ids
    assert "same-project-tool" not in ids
