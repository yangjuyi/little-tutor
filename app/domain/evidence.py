"""作答证据契约。

程序判定、模型归因和老师结论的来源不同，不能混成同一种可信证据。
"""

from dataclasses import dataclass
from typing import Literal

from app.domain.session import PracticeSession


EvidenceSource = Literal["program", "llm", "teacher"]
EvidenceKind = Literal["independent", "hinted", "scaffolded"]


@dataclass(frozen=True, slots=True)
class AnswerEvidence:
    """单题的一次作答证据。"""

    question_id: int
    attempt_no: int
    is_correct: bool
    source: EvidenceSource
    hints_used: int = 0
    scaffold_level: int = 0

    def __post_init__(self) -> None:
        if self.attempt_no < 1:
            raise ValueError("attempt_no 必须从 1 开始")
        if self.hints_used < 0:
            raise ValueError("hints_used 不能为负数")
        if self.scaffold_level < 0:
            raise ValueError("scaffold_level 不能为负数")

    @property
    def kind(self) -> EvidenceKind:
        """按学生受到的帮助程度标记证据类型。"""
        if self.scaffold_level > 0:
            return "scaffolded"
        if self.hints_used > 0:
            return "hinted"
        return "independent"

    @property
    def is_independent(self) -> bool:
        return self.attempt_no == 1 and self.kind == "independent"


def is_mastery_evidence(
    session: PracticeSession, answer: AnswerEvidence
) -> bool:
    """判断一条作答证据是否允许进入掌握度计算。

    AI 归因不能直接证明答案对错，因此不能单独驱动掌握度。
    """
    return session.allows_mastery_evidence() and answer.source != "llm"
