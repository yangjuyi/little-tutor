"""老师审核、作答事实与画像写入的持久化适配器。"""

from __future__ import annotations

import hashlib
import json

from app.adapters.persistence import (
    AnswerRecord,
    Mastery,
    PracticeSessionRecord,
    SessionLocal,
    TeacherDecision,
)
from app.domain.adaptation import evidence_weight_for


def _decision_dedupe_key(
    student_id: str,
    kp_id: str,
    session_id: str | None,
    question_id: str | None,
    decision: str,
    proposal: dict,
) -> str:
    payload = {
        "student_id": str(student_id),
        "kp_id": str(kp_id),
        "session_id": session_id,
        "question_id": str(question_id) if question_id else None,
        "decision": decision,
        "proposal": proposal,
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def apply_to_db(student_id: str, proposal: dict) -> None:
    """老师接受后写入掌握度。"""
    with SessionLocal() as s:
        _apply_to_db_in_session(s, student_id, proposal)
        s.commit()


def _apply_to_db_in_session(session, student_id: str, proposal: dict) -> None:
    row = (
        session.query(Mastery)
        .filter_by(
            student_id=int(student_id),
            kp_id=int(proposal["kp_id"]),
        )
        .first()
    )
    if row is None:
        row = Mastery(
            student_id=int(student_id),
            kp_id=int(proposal["kp_id"]),
        )
        session.add(row)
    row.confirmed_wrong_count = (
        row.confirmed_wrong_count or 0
    ) + proposal["confirmed_wrong_count_delta"]
    row.level = proposal["suggest_level"]
    row.confidence = proposal.get("confidence", row.confidence)
    row.last_status = (
        f"{proposal.get('evidence', '')}；批改归因："
        f"{proposal['reason']}（老师已确认）"
    )


def _answer_record_in_session(
    session,
    student_id: str,
    question_id: str,
    session_id: str | None,
) -> AnswerRecord | None:
    return (
        session.query(AnswerRecord)
        .filter(
            AnswerRecord.student_id == int(student_id),
            AnswerRecord.question_id == int(question_id),
            AnswerRecord.session_id == session_id,
        )
        .order_by(AnswerRecord.id.desc())
        .first()
    )


def _override_answer_result_in_session(
    session,
    student_id: str,
    question_id: str,
    kp_id: str,
    session_id: str | None,
    after: bool,
    subquestion_results: list[dict] | None = None,
    note: str | None = None,
) -> bool:
    record = _answer_record_in_session(
        session, student_id, question_id, session_id
    )
    if record is None:
        raise ValueError("找不到对应的作答记录")
    before = bool(record.is_correct)
    if record.teacher_is_correct == after:
        return False
    record.teacher_is_correct = after
    if subquestion_results is not None:
        record.subquestion_results = list(subquestion_results)
    record.evidence_weight = evidence_weight_for(
        after,
        record.assistance_level,
    )
    proposal_payload = {
        "program_is_correct": before,
        "teacher_is_correct": after,
        "reason": "teacher_result_override",
    }
    session.add(TeacherDecision(
        student_id=int(student_id),
        kp_id=int(kp_id),
        session_id=session_id,
        question_id=int(question_id),
        decision="override",
        proposal=proposal_payload,
        dedupe_key=_decision_dedupe_key(
            student_id,
            kp_id,
            session_id,
            question_id,
            "override",
            proposal_payload,
        ),
        note=note,
    ))
    return True


def _persist_teacher_review_in_session(
    session,
    student_id: str,
    proposals: list[dict],
    decision: str,
    session_id: str | None,
    *,
    question_id: str | None = None,
    note: str | None = None,
    apply_mastery: bool = True,
) -> None:
    for proposal in proposals:
        existing = (
            session.query(TeacherDecision)
            .filter(
                TeacherDecision.student_id == int(student_id),
                TeacherDecision.session_id == session_id,
                TeacherDecision.kp_id == int(proposal["kp_id"]),
                TeacherDecision.question_id == (
                    int(question_id) if question_id else None
                ),
                TeacherDecision.decision == decision,
            )
            .order_by(TeacherDecision.id.desc())
            .first()
        )
        if existing is not None and existing.proposal == dict(proposal):
            continue
        proposal_payload = dict(proposal)
        session.add(TeacherDecision(
            student_id=int(student_id),
            kp_id=int(proposal["kp_id"]),
            session_id=session_id,
            question_id=int(question_id) if question_id else None,
            decision=decision,
            proposal=proposal_payload,
            dedupe_key=_decision_dedupe_key(
                student_id,
                proposal["kp_id"],
                session_id,
                question_id,
                decision,
                proposal_payload,
            ),
            note=note,
        ))
        if decision == "accept" and apply_mastery:
            _apply_to_db_in_session(session, student_id, proposal)


def _correct_error_type_in_session(
    session,
    student_id: str,
    question_id: str,
    kp_id: str,
    session_id: str | None,
    before: str | None,
    after: str,
    note: str | None = None,
) -> None:
    record = _answer_record_in_session(
        session, student_id, question_id, session_id
    )
    if record is None:
        raise ValueError("找不到对应的作答记录")
    record.error_type = after
    proposal_payload = {
        "error_type_before": before,
        "error_type_after": after,
        "reason": "teacher_error_type_correction",
    }
    session.add(TeacherDecision(
        student_id=int(student_id),
        kp_id=int(kp_id),
        session_id=session_id,
        question_id=int(question_id),
        decision="edit",
        proposal=proposal_payload,
        dedupe_key=_decision_dedupe_key(
            student_id,
            kp_id,
            session_id,
            question_id,
            "edit",
            proposal_payload,
        ),
        note=note,
    ))


def record_answer(
    student_id: str,
    question: dict,
    result: dict,
    session_id: str | None,
    attempt_no: int = 1,
    hint_count: int = 0,
    scaffold_level: int = 0,
) -> bool:
    """作答事实无条件留痕。"""
    steps = result.get("steps") or []
    assistance_level = result.get("assistance_level") or (
        "scaffolded" if scaffold_level > 0
        else "hinted" if hint_count > 0
        else "independent"
    )
    with SessionLocal() as s:
        existing = (
            s.query(AnswerRecord.id)
            .filter(
                AnswerRecord.student_id == int(student_id),
                AnswerRecord.question_id == int(question["id"]),
                AnswerRecord.session_id == session_id,
                AnswerRecord.attempt_no == attempt_no,
            )
            .first()
        )
        if existing is not None:
            return False
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
            subquestion_results=result.get("subquestion_results"),
            session_id=session_id,
        ))
        s.commit()
        return True


def record_teacher_decision(
    student_id: str,
    proposal: dict,
    decision: str,
    session_id: str | None,
    question_id: str | None,
    note: str | None = None,
) -> bool:
    """记录 AI 建议与老师决定，reject 同样留痕。"""
    with SessionLocal() as s:
        existing = (
            s.query(TeacherDecision)
            .filter(
                TeacherDecision.student_id == int(student_id),
                TeacherDecision.session_id == session_id,
                TeacherDecision.kp_id == int(proposal["kp_id"]),
                TeacherDecision.question_id == (
                    int(question_id) if question_id else None
                ),
                TeacherDecision.decision == decision,
            )
            .order_by(TeacherDecision.id.desc())
            .first()
        )
        if existing is not None and existing.proposal == dict(proposal):
            return False
        proposal_payload = dict(proposal)
        s.add(TeacherDecision(
            student_id=int(student_id),
            kp_id=int(proposal["kp_id"]),
            session_id=session_id,
            question_id=int(question_id) if question_id else None,
            decision=decision,
            proposal=proposal_payload,
            dedupe_key=_decision_dedupe_key(
                student_id,
                proposal["kp_id"],
                session_id,
                question_id,
                decision,
                proposal_payload,
            ),
            note=note,
        ))
        s.commit()
        return True


def persist_teacher_review(
    student_id: str,
    proposals: list[dict],
    decision: str,
    session_id: str | None,
    *,
    question_id: str | None = None,
    note: str | None = None,
    apply_mastery: bool = True,
) -> None:
    """在同一业务库事务内写老师决定，并在 accept 时更新画像。"""
    with SessionLocal() as s:
        _persist_teacher_review_in_session(
            s,
            student_id,
            proposals,
            decision,
            session_id,
            question_id=question_id,
            note=note,
            apply_mastery=apply_mastery,
        )
        s.commit()


def correct_error_type(
    student_id: str,
    question_id: str,
    kp_id: str,
    session_id: str | None,
    before: str | None,
    after: str,
    note: str | None = None,
) -> None:
    """老师修正题级错因：更新事实字段并保留修正链。"""
    with SessionLocal() as s:
        _correct_error_type_in_session(
            s,
            student_id,
            question_id,
            kp_id,
            session_id,
            before,
            after,
            note=note,
        )
        s.commit()


def override_answer_result(
    student_id: str,
    question_id: str,
    kp_id: str,
    session_id: str | None,
    after: bool,
    subquestion_results: list[dict] | None = None,
    note: str | None = None,
) -> None:
    """老师确认题级最终结果；程序初评仍永久保留。"""
    with SessionLocal() as s:
        _override_answer_result_in_session(
            s,
            student_id,
            question_id,
            kp_id,
            session_id,
            after,
            subquestion_results=subquestion_results,
            note=note,
        )
        s.commit()
        return True


def persist_teacher_review_bundle(
    student_id: str,
    proposals: list[dict],
    decision: str,
    session_id: str | None,
    *,
    overrides: list[dict] | None = None,
    error_edits: list[dict] | None = None,
    note: str | None = None,
    apply_mastery: bool = True,
    test_mode: bool = False,
    review_decision: str | None = None,
) -> None:
    """在单一事务内完成全部 H3 写回。"""
    with SessionLocal() as s:
        for item in overrides or []:
            _override_answer_result_in_session(
                s,
                student_id,
                str(item["question_id"]),
                str(item["kp_id"]),
                session_id,
                bool(item["after"]),
                subquestion_results=item.get("subquestion_results"),
                note=note,
            )
        for item in error_edits or []:
            _correct_error_type_in_session(
                s,
                student_id,
                str(item["question_id"]),
                str(item["kp_id"]),
                session_id,
                item.get("before"),
                str(item["after"]),
                note=note,
            )
        _persist_teacher_review_in_session(
            s,
            student_id,
            proposals,
            decision,
            session_id,
            note=note,
            apply_mastery=apply_mastery,
        )
        if session_id:
            practice_session = s.get(PracticeSessionRecord, session_id)
            if practice_session is None:
                raise ValueError("找不到对应的练习会话")
            if test_mode:
                practice_session.data_source = "test"
            if review_decision:
                practice_session.review_status = review_decision
        s.commit()
