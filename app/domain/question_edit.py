"""老师修订题目的程序重算规则。"""

from __future__ import annotations

from app.domain.grading import validate_difficulty_params
from app.domain.question_materialization import materialize_question


def recompute_edited_question(
    question: dict,
    *,
    stem: str,
    a: float,
    b: float,
    c: float,
    structure_tag: str | None = None,
) -> dict:
    """校验修订参数并重新生成答案、解析和有效根。"""
    stem = stem.strip()
    if not stem:
        raise ValueError("修改后的题干不能为空")
    difficulty = question["difficulty"]
    params = dict(question.get("params") or {})
    resolved_tag = (
        structure_tag
        if structure_tag is not None
        else params.get("structure_tag", "")
    )
    error = validate_difficulty_params(
        a, b, c, difficulty, resolved_tag
    )
    if error:
        raise ValueError(error)

    params.update({
        "a": a,
        "b": b,
        "c": c,
        "structure_tag": resolved_tag,
    })
    edited = dict(question)
    edited.update({
        "stem": stem,
        "params": params,
    })
    return materialize_question(edited, regenerate_analysis=True)
