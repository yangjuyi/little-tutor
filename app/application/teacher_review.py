"""老师审核画像建议的应用用例。"""

from app.adapters.review_store import (
    persist_teacher_review,
    record_answer,
)
from app.application.profile_evidence import propose_mastery_change


def propose_profile_change(
    result: dict,
    student_id: str | None = None,
    session_id: str | None = None,
) -> dict:
    """由批改结果生成可审核的画像变更建议。"""
    wrong = not result["is_correct"]
    proposal = {
        "kp_id": result["error"]["error_kp_id"],
        "confirmed_wrong_count_delta": 0 if result["is_correct"] else 1,
        "reason": result["error"]["error_type"],
    }
    if student_id is None:
        proposal.update(suggest_level="weak" if wrong else "mid", confidence=0.5)
        proposal["evidence"] = "无学生上下文，单题退化建议"
        return proposal
    proposal.update(propose_mastery_change(
        student_id=int(student_id),
        kp_id=int(result["error"]["error_kp_id"]),
        current={"session_id": session_id, "correct": result["is_correct"]},
    ))
    return proposal


def persist_review(
    student_id: str,
    question: dict,
    result: dict,
    proposal: dict,
    decision: str,
    session_id: str | None,
    attempt_no: int = 1,
) -> None:
    """事实、仲裁和掌握度按老师决定分别落库。"""
    record_answer(
        student_id,
        question,
        result,
        session_id,
        attempt_no=attempt_no,
    )
    persist_teacher_review(
        student_id,
        [proposal],
        decision,
        session_id,
        question_id=str(question.get("id") or "") or None,
    )
