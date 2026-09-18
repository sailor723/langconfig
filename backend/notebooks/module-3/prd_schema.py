"""Phase 1 产品设计 Agent 使用的结构化 PRD Schema。

该模块用于明确 Phase 1 的事实来源，帮助 Agent 区分：
- 用户已经提供的字段
- 仍然缺失或语义模糊的字段
- 在生成系统提示词前必须补齐的字段
"""

from dataclasses import dataclass, field


REQUIRED_FIELDS = [
    "project_name",
    "target_user",
    "problem_statement",
    "primary_goal",
    "core_scenarios",
    "agent_role",
    "main_tasks",
    "must_have_functions",
    "can_do",
    "must_ask_first",
    "must_not_do",
    "tooling_and_data",
    "fallback_strategy",
    "output_tone",
]


@dataclass
class PRDDocument:
    """Phase 1 使用的结构化 PRD 表示。"""

    project_name: str = ""
    version: str = "0.1"
    status: str = "draft"

    target_user: str = ""
    current_workflow: str = ""
    problem_statement: str = ""
    pain_cost: str = ""
    why_now: str = ""

    primary_goal: str = ""
    secondary_goals: list[str] = field(default_factory=list)
    out_of_scope: list[str] = field(default_factory=list)
    success_definition: str = ""

    core_scenarios: list[str] = field(default_factory=list)
    high_frequency_scenarios: list[str] = field(default_factory=list)
    high_risk_scenarios: list[str] = field(default_factory=list)
    not_applicable_scenarios: list[str] = field(default_factory=list)

    agent_role: str = ""
    output_tone: str = ""
    autonomy_level: str = ""
    main_tasks: list[str] = field(default_factory=list)
    approval_points: list[str] = field(default_factory=list)

    must_have_functions: list[str] = field(default_factory=list)
    advanced_functions: list[str] = field(default_factory=list)

    can_do: list[str] = field(default_factory=list)
    must_ask_first: list[str] = field(default_factory=list)
    must_not_do: list[str] = field(default_factory=list)

    tooling_and_data: list[str] = field(default_factory=list)
    data_guardrails: list[str] = field(default_factory=list)

    fallback_strategy: str = ""
    human_handoff_conditions: list[str] = field(default_factory=list)

    quality_metrics: list[str] = field(default_factory=list)


def get_missing_required_fields(prd: PRDDocument) -> list[str]:
    """返回会阻塞系统提示词生成的缺失字段。"""
    missing: list[str] = []

    for field_name in REQUIRED_FIELDS:
        value = getattr(prd, field_name)
        if isinstance(value, list):
            if not value:
                missing.append(field_name)
        elif not str(value).strip():
            missing.append(field_name)

    return missing


def is_ready_for_prompt_generation(prd: PRDDocument) -> bool:
    """仅当 PRD 完整到足以生成系统提示词时返回 True。"""
    return not get_missing_required_fields(prd)


def format_missing_field_checklist(prd: PRDDocument) -> str:
    """返回用于向用户发起澄清的问题清单。"""
    missing = get_missing_required_fields(prd)
    if not missing:
        return "所有必填 PRD 字段均已提供。"

    lines = ["当前仍缺少以下必填 PRD 字段："]
    for field_name in missing:
        lines.append(f"- {field_name}")
    return "\n".join(lines)
