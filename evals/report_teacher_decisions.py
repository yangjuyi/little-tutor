r"""Read-only summary of teacher decisions and attribution corrections.

This report deliberately distinguishes reliable counts from metrics whose
denominator is not recorded. It never reports answer-to-decision delay as
human review duration.

Run:
    .\.venv\Scripts\python.exe -X utf8 evals\report_teacher_decisions.py
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path

from sqlalchemy import inspect, text

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.adapters.persistence import SessionLocal, TeacherDecision


DEFAULT_OUTPUT = ROOT / "outputs" / "evals" / "teacher_decisions.json"


def _as_datetime(value):
    if value is None or isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def _decision_delay_seconds(decision: dict, answers: list[dict]) -> float | None:
    decided_at = _as_datetime(decision.get("created_at"))
    if decided_at is None:
        return None
    session_id = decision.get("session_id")
    question_id = decision.get("question_id")
    candidates = []
    for answer in answers:
        if session_id is not None and answer.get("session_id") != session_id:
            continue
        if (
            question_id is not None
            and answer.get("question_id") != question_id
        ):
            continue
        answer_at = _as_datetime(answer.get("created_at"))
        if answer_at is not None and answer_at <= decided_at:
            candidates.append(answer_at)
    if not candidates:
        return None
    return (decided_at - max(candidates)).total_seconds()


def summarize_teacher_decisions(
    decisions: list[dict],
    answers: list[dict],
) -> dict:
    """Summarize already-loaded rows without claiming unavailable rates."""
    decision_counts = Counter(str(row.get("decision") or "") for row in decisions)
    correction_rows = [
        row for row in decisions
        if (row.get("proposal") or {}).get("reason")
        == "teacher_error_type_correction"
    ]
    override_rows = [
        row for row in decisions if row.get("decision") == "override"
    ]
    delays = [
        delay for row in decisions
        if (delay := _decision_delay_seconds(row, answers)) is not None
    ]
    delay_stats = None
    if delays:
        delay_stats = {
            "sample_count": len(delays),
            "average_seconds": round(statistics.mean(delays), 3),
            "median_seconds": round(statistics.median(delays), 3),
            "min_seconds": round(min(delays), 3),
            "max_seconds": round(max(delays), 3),
        }

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "totals": {
            "decisions": len(decisions),
            "decision_counts": dict(sorted(decision_counts.items())),
            "sessions": len({
                row.get("session_id")
                for row in decisions
                if row.get("session_id") is not None
            }),
            "questions": len({
                row.get("question_id")
                for row in decisions
                if row.get("question_id") is not None
            }),
        },
        "attribution": {
            "error_type_correction_count": len(correction_rows),
            "correction_rate": None,
            "rate_status": "unavailable",
            "rate_reason": (
                "当前记录没有“已审核但未修正”的逐题分母；"
                "只能确认修正次数，不能计算可靠的采纳率或修正率。"
            ),
        },
        "result_review": {
            "teacher_override_count": len(override_rows),
            "override_rate": None,
            "rate_status": "unavailable",
            "rate_reason": (
                "当前记录没有逐题程序结果审阅分母，不能计算可靠的推翻率。"
            ),
        },
        "decision_delay": {
            "meaning": "最后一条相关作答记录到老师决定之间的延迟，不是人工审核耗时。",
            "resolved_decisions": len(delays),
            "unresolved_decisions": len(decisions) - len(delays),
            "stats": delay_stats,
        },
        "limitations": [
            "当前库不能计算老师采纳率或修正率，因为缺少逐题审核分母。",
            "decision_delay 不能替代人工审核耗时。",
            "没有真实老师样本时，不对外宣称老师可用性已经验证。",
        ],
    }


def _load_answer_rows(session) -> list[dict]:
    bind = session.get_bind()
    inspector = inspect(bind)
    if "answer_records" not in inspector.get_table_names():
        return []
    columns = {
        column["name"]
        for column in inspector.get_columns("answer_records")
    }
    selected = [
        column for column in ("session_id", "question_id", "created_at")
        if column in columns
    ]
    if len(selected) < 2:
        return []
    rows = session.execute(
        text(f"SELECT {', '.join(selected)} FROM answer_records")
    ).mappings()
    return [dict(row) for row in rows]


def collect_teacher_decision_report(session) -> dict:
    decision_rows = []
    for row in session.query(TeacherDecision).all():
        decision_rows.append({
            "decision": row.decision,
            "session_id": row.session_id,
            "question_id": row.question_id,
            "proposal": row.proposal or {},
            "created_at": row.created_at,
        })
    return summarize_teacher_decisions(
        decision_rows,
        _load_answer_rows(session),
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    with SessionLocal() as session:
        report = collect_teacher_decision_report(session)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"\nReport written to: {args.output}")


if __name__ == "__main__":
    main()
