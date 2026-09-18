"""Phase 1 评估标准与评分维度定义."""

from dataclasses import dataclass, field


@dataclass
class EvaluationDimension:
    """单个评估维度定义."""

    name: str
    description: str
    passing_rule: str


@dataclass
class EvaluationRubric:
    """单类产物的评估 Rubric."""

    artifact_name: str
    purpose: str
    dimensions: list[EvaluationDimension] = field(default_factory=list)
    block_if_failed: bool = True


PRD_DRAFT_RUBRIC = EvaluationRubric(
    artifact_name="PRD 草稿",
    purpose="检查 Agent 是否正确提取用户输入，并把已知内容整理为结构化 PRD。",
    dimensions=[
        EvaluationDimension(
            name="完整性",
            description="是否已经捕捉到用户明确提供的信息，并清楚标出缺失字段。",
            passing_rule="已知信息不能遗漏，缺失信息不能假装已知。",
        ),
        EvaluationDimension(
            name="正确性",
            description="PRD 草稿中的内容是否与用户原始输入一致。",
            passing_rule="不允许曲解用户需求，不允许凭空补造业务细节。",
        ),
        EvaluationDimension(
            name="结构化程度",
            description="是否已按固定 PRD 字段进行归类，而不是散乱描述。",
            passing_rule="主要信息必须落入标准 PRD 字段。",
        ),
        EvaluationDimension(
            name="缺口识别质量",
            description="是否明确指出阻塞后续系统提示词生成的关键缺口。",
            passing_rule="关键缺口必须被标记出来，且能支撑后续提问。",
        ),
    ],
)


CLARIFICATION_QUESTION_RUBRIC = EvaluationRubric(
    artifact_name="澄清问题",
    purpose="检查 Agent 是否提出少量高价值问题，以补齐关键 PRD 字段。",
    dimensions=[
        EvaluationDimension(
            name="问题价值",
            description="问题是否直接帮助补齐关键字段，而不是泛泛追问。",
            passing_rule="每个问题都应显著提升 PRD 完整度。",
        ),
        EvaluationDimension(
            name="问题数量控制",
            description="是否只问必要问题，避免让用户产生疲劳。",
            passing_rule="优先合并问题，避免重复和低价值追问。",
        ),
        EvaluationDimension(
            name="表达清晰度",
            description="问题是否容易理解，且用户知道如何回答。",
            passing_rule="问题必须具体、清楚、可回答。",
        ),
        EvaluationDimension(
            name="阶段边界控制",
            description="是否避免提前询问属于 Phase 2 的技术实现问题。",
            passing_rule="问题应聚焦 Phase 1，不提前深入技术方案。",
        ),
    ],
)


FINAL_PRD_RUBRIC = EvaluationRubric(
    artifact_name="最终 PRD",
    purpose="检查 PRD 是否已经完整到足以支撑系统提示词生成。",
    dimensions=[
        EvaluationDimension(
            name="必填字段完整性",
            description="关键字段是否已经补齐。",
            passing_rule="所有阻塞系统提示词生成的必填字段必须完整。",
        ),
        EvaluationDimension(
            name="内部一致性",
            description="目标用户、任务、边界、审批节点等内容是否自洽。",
            passing_rule="不能出现明显冲突或前后矛盾。",
        ),
        EvaluationDimension(
            name="可执行性",
            description="PRD 是否足够具体，能够转化为运行级系统提示词。",
            passing_rule="不能停留在过于抽象的口号层。",
        ),
        EvaluationDimension(
            name="边界清晰度",
            description="Agent 能做、必须先问、绝不能做的事项是否明确。",
            passing_rule="高风险边界必须清晰可判定。",
        ),
    ],
)


SYSTEM_PROMPT_RUBRIC = EvaluationRubric(
    artifact_name="系统提示词",
    purpose="检查系统提示词是否忠实于 PRD，且具备可执行性与安全性。",
    dimensions=[
        EvaluationDimension(
            name="PRD 对齐度",
            description="系统提示词是否完全基于 PRD，不引入无依据假设。",
            passing_rule="如 PRD 未明确，不允许在提示词中自行扩展业务事实。",
        ),
        EvaluationDimension(
            name="具体性",
            description="提示词是否足够具体，可直接指导 Agent 行为。",
            passing_rule="不能只写空泛原则，必须转化为操作规则。",
        ),
        EvaluationDimension(
            name="安全性",
            description="提示词是否明确禁止事项、审批规则与兜底逻辑。",
            passing_rule="高风险动作必须有显式限制与转人工条件。",
        ),
        EvaluationDimension(
            name="可审查性",
            description="提示词结构是否清晰，便于业务方或产品经理评审。",
            passing_rule="应按固定结构输出，方便 review 与版本管理。",
        ),
    ],
)


PHASE1_EVALUATION_FLOW = [
    "生成 PRD 草稿后，先进行 PRD 草稿评估。",
    "如 PRD 草稿存在关键缺口，则生成澄清问题并评估提问质量。",
    "在用户回答后，生成最终 PRD，并执行最终 PRD 评估。",
    "仅当最终 PRD 通过评估后，才允许生成系统提示词。",
    "系统提示词生成后，必须执行系统提示词评估。",
    "若任一关键评估未通过，则状态应为 revise 或 blocked，而不是直接输出最终结果。",
]
