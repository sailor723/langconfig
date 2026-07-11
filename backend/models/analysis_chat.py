# Copyright (c) 2025 Cade Russell (Ghost Peony)
#
# This source code is licensed under the MIT license found in the
# LICENSE file in the root directory of this source tree.

"""Analysis Chat History — per-dashboard chat persistence.

Each row is one message in a chat thread tied to a specific
dashboard HTML file. Re-opening the same dashboard shows the
full history.
"""
from sqlalchemy import Column, Integer, String, Text, JSON, DateTime
from sqlalchemy.sql import func
from db.database import Base


class AnalysisChatMessage(Base):
    """One chat message in a dashboard's chat history.

    `dashboard_filename` is the file's basename (e.g.
    'erp_dashboard_20260711_055116.html'). It's a soft key —
    we don't FK to a `dashboards` table because dashboards are
    just files on disk under data/analysis_dbs/.
    """

    __tablename__ = "analysis_chat_messages"

    id = Column(Integer, primary_key=True, autoincrement=True)
    dashboard_filename = Column(
        String(255), nullable=False, index=True,
        comment="Filename of the dashboard HTML, e.g. 'erp_dashboard_20260711_055116.html'",
    )
    role = Column(
        String(20), nullable=False,
        comment="'user' | 'assistant' | 'system' | 'tool'",
    )
    content = Column(
        Text, nullable=False,
        comment="The user message or the assistant's final answer (no <think> traces).",
    )
    # Tool calls and thinking steps are kept separate from `content`
    # so the user sees a clean answer bubble; the trace is collapsible.
    tool_trace = Column(
        JSON, nullable=True,
        comment="List of {step, type, name, input, output} dicts captured during agent run.",
    )
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    def __repr__(self):
        return f"<AnalysisChatMessage id={self.id} dashboard={self.dashboard_filename!r} role={self.role}>"
