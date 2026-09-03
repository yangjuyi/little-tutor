"""LangGraph State / TypedDict definitions.

Source: PROJECT_SPEC.md §16.3
State is runtime-only (destroyed after each graph run).
Data models (Mastery / Question / etc.) are the persistent layer.
"""

from typing import TypedDict, Literal, Optional, List


Level = Literal["weak", "mid", "strong"]
ErrorType = Literal["审题", "概念", "计算", "跳步", "粗心", "无错"]


# ---------- 数据模型（落库/题库文件）----------

class Mastery(TypedDict):
    kp_id: str
    level: Level
    confidence: float
    evidence: str


class Question(TypedDict):
    id: str
    kp_id: str
    dep_kp_ids: List[str]
    difficulty: Level
    stem: str
    answer: str
    analysis: str
    images: List[str]
    source: Literal["public", "private", "ai_generated"]


class StudentStep(TypedDict):
    basis: str
    result: str


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


class QuestionResult(TypedDict):
    question_id: str
    is_correct: bool
    error: ErrorAnalysis
    steps: List[StudentStep]


class RecheckResult(TypedDict):
    answer: str
    analysis: str
    process: List[str]


# ---------- LangGraph 运行时 State ----------

class TutorState(TypedDict):
    student_id: str
    session_id: Optional[str]
    kp_id: str
    kp_name: Optional[str]
    profile_snapshot: Mastery
    question: Question
    question_status: Literal["pending_teacher", "approved", "rejected", "edited"]
    teacher_instruction: Optional[str]
    teacher_edited_stem: Optional[str]
    teacher_filled_answer: Optional[str]
    recheck: Optional[RecheckResult]
    cross_check: Optional[Literal["match", "mismatch"]]
    student_steps: List[StudentStep]
    result: QuestionResult
    batch_profile: dict  # 批级画像建议（SPEC §16.7）；V1 单题阶段即题级建议原样上抛
    teacher_decision: Literal["accept", "reject", "edit"]
    teacher_note: Optional[str]
    phase: Literal["generate", "answer", "grade", "profile"]
