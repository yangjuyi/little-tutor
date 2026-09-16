"""教学领域数据模型。"""

from typing import List, Literal, Optional, TypedDict

from app.domain.types import DifficultyLevel, ErrorType, Level


class Mastery(TypedDict):
    kp_id: str
    level: Level
    confidence: float
    evidence: str


class Question(TypedDict):
    id: str
    kp_id: str
    dep_kp_ids: List[str]
    difficulty: DifficultyLevel
    stem: str
    answer: str
    analysis: str
    images: List[str]
    source: Literal["public", "private", "ai_generated"]


class StudentStep(TypedDict):
    basis: str
    result: str


class StudentStepV2(TypedDict):
    step_no: int
    raw_latex: str
    operation: str
    source: Literal["typed", "template", "photo", "canvas"]
    confidence: float


SubmissionMode = Literal["final_answer_only", "step_by_step"]


class Submission(TypedDict):
    mode: SubmissionMode
    steps: List[StudentStepV2]
    final_answer: str


class TransitionCheck(TypedDict):
    from_step: int
    to_step: int
    is_valid: bool
    rule: str
    error_type: Optional[ErrorType]
    evidence: str
    confidence: float
    insufficient_evidence: bool


BlankKind = Literal["choice", "expression"]


class Blank(TypedDict):
    id: str
    kind: BlankKind
    basis: str
    options: Optional[List[str]]
    answer_index: Optional[int]
    expected: Optional[float]


class QuestionTemplate(TypedDict):
    blanks: List[Blank]
    answer_blank_ids: List[str]


class BlankResult(TypedDict):
    blank_id: str
    basis: str
    kind: BlankKind
    student_result: str
    is_correct: bool


class ErrorAnalysis(TypedDict):
    error_type: ErrorType
    error_kp_id: Optional[str]
    confidence: float
    evidence: str
    evidence_source: Literal["program", "llm", "teacher"]
    ai_certain: bool
    teacher_reviewed: bool
    steps_analyzed: int
    insufficient_evidence: bool
    program_breakpoint: Optional[str]


class QuestionResult(TypedDict):
    question_id: str
    is_correct: bool
    final_answer_correct: bool
    process_correct: bool
    difficulty: Optional[DifficultyLevel]
    attempt_no: int
    assistance_level: str
    hint_count: int
    scaffold_level: int
    error: ErrorAnalysis
    steps: List[StudentStep]
    blank_results: Optional[List[BlankResult]]


class RecheckResult(TypedDict):
    answer: str
    analysis: str
    process: List[str]
