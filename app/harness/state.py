"""LangGraph 运行时状态。"""

import operator
from typing import Annotated, List, Literal, Optional, TypedDict

from app.domain.models import (
    Mastery,
    Question,
    QuestionResult,
    QuestionTemplate,
    RecheckResult,
    StudentStep,
)


def _first_error(old: Optional[str], new: Optional[str]) -> Optional[str]:
    """并发 Send 任务同时失败时保留首条错误。"""
    return old if old is not None else new


class TutorState(TypedDict):
    student_id: str
    session_id: Optional[str]
    kp_id: str
    kp_name: Optional[str]
    profile_snapshot: Mastery
    question: Question
    template: Optional[QuestionTemplate]
    question_status: Literal["pending_teacher", "approved", "rejected", "edited"]
    teacher_instruction: Optional[str]
    teacher_edited_stem: Optional[str]
    teacher_filled_answer: Optional[str]
    recheck: Optional[RecheckResult]
    cross_check: Optional[Literal["match", "mismatch"]]
    student_steps: List[StudentStep]
    attempt_no: int
    result: QuestionResult
    batch_profile: dict
    teacher_decision: Literal["accept", "reject", "edit"]
    teacher_note: Optional[str]
    phase: Literal["generate", "answer", "grade", "profile"]


class SessionState(TypedDict):
    student_id: str
    session_id: Optional[str]
    kp_id: str
    kp_name: Optional[str]
    question_count: int
    profile_snapshot: Optional[Mastery]
    candidates: List[Question]
    plan: List[dict]
    generated: Annotated[List[dict], operator.add]
    plan_id: int
    llm_error: Annotated[Optional[str], _first_error]
    h1_decision: Literal["approve", "swap", "regroup", "edit", "edit_error"]
    teacher_instruction: Optional[str]
    h1_validation_error: Optional[str]
    difficulty_ratios: Optional[dict[str, int]]
    adaptive_target: Optional[Literal["simple", "mid", "hard"]]
    approved_pool: List[Question]
    approved_questions: List[Question]
    current_question: Optional[Question]
    hint_level: int
    template: Optional[QuestionTemplate]
    student_steps: List[StudentStep]
    attempt_no: int
    assistance_level: Optional[str]
    hint_count: int
    scaffold_level: int
    skip: bool
    result: Optional[QuestionResult]
    round_results: List[QuestionResult]
    session_proposals: List[dict]
    h3_decision: Literal["accept", "reject"]
    test_session: bool
    phase: Literal["assemble", "answer", "grade_round", "summarize", "done"]
