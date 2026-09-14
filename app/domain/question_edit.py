"""老师修订题目的程序重算规则。"""

from __future__ import annotations

import math
from decimal import Decimal, InvalidOperation

from app.domain.grading import validate_difficulty_params
from app.domain.question_materialization import materialize_question


def _normalize_coefficient(
    value: str | int | float,
    name: str,
) -> int | float:
    """整数系数存 int，非整数才保留 float，避免 2 被显示成 2.0。"""
    if isinstance(value, bool):
        raise ValueError(f"{name} 必须是数字")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"{name} 必须是有限数字")
        return int(value) if value.is_integer() else value
    text = str(value).strip()
    if not text:
        raise ValueError(f"{name} 不能为空")
    try:
        number = Decimal(text)
    except InvalidOperation as exc:
        raise ValueError(f"{name} 必须是数字") from exc
    if not number.is_finite():
        raise ValueError(f"{name} 必须是有限数字")
    if number == number.to_integral_value():
        return int(number)
    return float(number)


def recompute_edited_question(
    question: dict,
    *,
    stem: str,
    a: str | int | float,
    b: str | int | float,
    c: str | int | float,
    structure_tag: str | None = None,
) -> dict:
    """校验修订参数并重新生成答案、解析和有效根。"""
    stem = stem.strip()
    if not stem:
        raise ValueError("修改后的题干不能为空")
    a = _normalize_coefficient(a, "a")
    b = _normalize_coefficient(b, "b")
    c = _normalize_coefficient(c, "c")
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
