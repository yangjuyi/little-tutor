"""老师审核、作答事实与画像写入的持久化适配器。"""

from app.adapters.persistence import (
    AnswerRecord,
    Mastery,
    SessionLocal,
    TeacherDecision,
)
from app.domain.adaptation import evidence_weight_for


def apply_to_db(student_id: str, proposal: dict) -> None:
    """老师接受后写入掌握度。"""
    with SessionLocal() as s:
        row = (
            s.query(Mastery)
            .filter_by(student_id=int(student_id), kp_id=int(proposal["kp_id"]))
            .first()
        )
        if row is None:
            row = Mastery(student_id=int(student_id), kp_id=int(proposal["kp_id"]))
            s.add(row)
        row.confirmed_wrong_count = (
            row.confirmed_wrong_count or 0
        ) + proposal["confirmed_wrong_count_delta"]
        row.level = proposal["suggest_level"]
        row.confidence = proposal.get("confidence", row.confidence)
        row.last_status = (
            f"{proposal.get('evidence', '')}；批改归因："
            f"{proposal['reason']}（老师已确认）"
        )
        s.commit()


def record_answer(
    student_id: str,
    question: dict,
    result: dict,
    session_id: str | None,
    attempt_no: int = 1,
    hint_count: int = 0,
    scaffold_level: int = 0,
) -> None:
    """作答事实无条件留痕。"""
    steps = result.get("steps") or []
    assistance_level = (
        "scaffolded" if scaffold_level > 0
        else "hinted" if hint_count > 0
        else "independent"
    )
    with SessionLocal() as s:
        s.add(AnswerRecord(
            student_id=int(student_id),
            question_id=int(question["id"]),
            answer=steps[-1]["result"] if steps else "",
            is_correct=result["is_correct"],
            attempt_no=attempt_no,
            first_attempt_correct=(
                result["is_correct"] if attempt_no == 1 else False
            ),
            hint_count=hint_count,
            scaffold_level=scaffold_level,
            assistance_level=assistance_level,
            evidence_weight=evidence_weight_for(
                bool(result["is_correct"]),
                assistance_level,
            ),
            error_type=result["error"]["error_type"],
            session_id=session_id,
        ))
        s.commit()


def record_teacher_decision(
    student_id: str,
    proposal: dict,
    decision: str,
    session_id: str | None,
    question_id: str | None,
) -> None:
    """记录 AI 建议与老师决定，reject 同样留痕。"""
    with SessionLocal() as s:
        s.add(TeacherDecision(
            student_id=int(student_id),
            kp_id=int(proposal["kp_id"]),
            session_id=session_id,
            question_id=int(question_id) if question_id else None,
            decision=decision,
            proposal=dict(proposal),
        ))
        s.commit()
