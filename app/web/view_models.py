"""页面展示数据组装。"""


_ERROR_TYPES = ("审题", "概念", "计算", "跳步", "粗心", "漏根")
_MASTERY_LABELS = {
    "weak": "需要加强",
    "mid": "基本掌握",
    "strong": "掌握较好",
}
_MASTERY_SCORES = {
    "weak": 0.3,
    "mid": 0.65,
    "strong": 0.9,
}


def _effective_is_correct(result: dict) -> bool:
    return bool(
        result.get(
            "effective_is_correct",
            result.get("is_correct"),
        )
    )


def build_done_context(values: dict) -> dict:
    """把会话事实整理为完成页图表数据。"""
    rounds = list(values.get("round_results") or [])
    proposals = list(values.get("session_proposals") or [])
    proposal = proposals[0] if proposals else {}
    total = len(rounds)
    correct = sum(1 for result in rounds if _effective_is_correct(result))
    wrong = total - correct
    process_error_count = sum(
        1
        for result in rounds
        if result.get("final_answer_correct")
        and not result.get("process_correct", True)
    )
    skipped_count = sum(
        1
        for result in rounds
        if (result.get("assistance_level") or "") == "skipped"
    )
    session_rate = correct / total if total else 0.0

    error_counts = {error_type: 0 for error_type in _ERROR_TYPES}
    unattributed_count = 0
    for result in rounds:
        if _effective_is_correct(result):
            continue
        error = result.get("error") or {}
        if error.get("evidence_source") != "llm":
            unattributed_count += 1
            continue
        error_type = error.get("error_type")
        if error_type in error_counts:
            error_counts[error_type] += 1
        else:
            unattributed_count += 1

    blank_results = [
        blank
        for result in rounds
        for blank in (result.get("blank_results") or [])
    ]
    blank_rate = (
        sum(1 for blank in blank_results if blank.get("is_correct"))
        / len(blank_results)
        if blank_results else session_rate
    )
    evidence_rate = (
        sum(
            1 for result in rounds
            if not (result.get("error") or {}).get("insufficient_evidence", False)
        ) / total
        if total else 0.0
    )

    mastery_level = proposal.get("suggest_level") or "weak"
    max_error = max(error_counts.values()) if error_counts else 0
    return {
        "total": total,
        "correct": correct,
        "wrong": wrong,
        "process_error_count": process_error_count,
        "skipped_count": skipped_count,
        "session_rate": session_rate,
        "mastery_level": mastery_level,
        "mastery_label": _MASTERY_LABELS[mastery_level],
        "kp_name": proposal.get("kp_name") or "当前知识点",
        "profile_values": [
            _MASTERY_SCORES[mastery_level],
            session_rate,
            blank_rate,
            evidence_rate,
        ],
        "error_counts": error_counts,
        "unattributed_count": unattributed_count,
        "error_values": [
            (error_counts[error_type] / max_error) if max_error else 0.0
            for error_type in _ERROR_TYPES
        ],
    }
