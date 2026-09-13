"""画像证据读取与掌握度建议。"""

from datetime import datetime

from app.adapters.persistence import AnswerRecord, Question, SessionLocal
from app.adapters.session_store import eligible_session_ids
from app.domain.mastery import propose_from_rates


def session_rates(
    student_id: int, kp_id: int, current: dict | None = None
) -> list[float]:
    """各会话正确率，最近在前；仅接受真实、完成、老师已确认的会话。"""
    valid_sessions = eligible_session_ids(student_id, kp_id)
    if not valid_sessions and current is None:
        return []
    with SessionLocal() as s:
        rows = (
            s.query(
                AnswerRecord.session_id,
                AnswerRecord.is_correct,
                AnswerRecord.evidence_weight,
                AnswerRecord.created_at,
            )
            .join(Question, Question.id == AnswerRecord.question_id)
            .filter(
                AnswerRecord.student_id == student_id,
                Question.kp_id == kp_id,
                AnswerRecord.session_id.in_(valid_sessions),
            )
            .all()
        )
    buckets: dict[str, list[tuple[float, object]]] = {}
    for session_id, is_correct, evidence_weight, created_at in rows:
        bucket = buckets.setdefault(session_id, [])
        bucket.append(
            (
                float(evidence_weight) if is_correct else 0.0,
                created_at,
            )
        )
    if current and current.get("session_id") is not None:
        buckets.setdefault(current["session_id"], []).append(
            (float(current["correct"]), None)
        )

    def _last_time(item):
        timestamps = [timestamp for _, timestamp in item[1] if timestamp is not None]
        return max(timestamps) if timestamps else datetime.min

    ranked = sorted(buckets.items(), key=_last_time, reverse=True)
    if current and current.get("session_id") is not None:
        ranked.sort(key=lambda item: item[0] != current["session_id"])
    return [
        sum(weight for weight, _ in answers) / len(answers)
        for _, answers in ranked
    ]


def propose_mastery_change(
    student_id: int,
    kp_id: int,
    current: dict | None = None,
    current_rate: float | None = None,
) -> dict:
    """读取有效历史会话并交给纯领域规则计算建议。"""
    if current_rate is not None:
        rates = [float(current_rate)] + session_rates(student_id, kp_id)
    else:
        rates = session_rates(student_id, kp_id, current)
    return propose_from_rates(rates)
