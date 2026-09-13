"""由题干契约和结构化参数派生题目的所有可计算字段。"""

from __future__ import annotations

from app.domain.grading import compute_answer
from app.domain.stem_contract import validate_stem_contract


def _format_equation(a: float, b: float, c: float) -> str:
    return f"{a:g}x² {b:+g}x {c:+g} = 0"


def valid_roots_for(
    design_id: str,
    a: float,
    b: float,
    c: float,
) -> list[float]:
    """按题型确定有效根；应用题只保留符合题意的根。"""
    roots = list(compute_answer(a, b, c))
    if design_id == "rectangle":
        roots = [root for root in roots if root > 0]
        if not roots:
            raise ValueError("面积应用题必须至少有一个正根")
    return roots


def format_answer(valid_roots: list[float]) -> str:
    if len(valid_roots) == 1:
        return f"x={valid_roots[0]:g}"
    return f"x₁={valid_roots[0]:g}, x₂={valid_roots[1]:g}"


def _build_analysis(
    design_id: str,
    a: float,
    b: float,
    c: float,
    valid_roots: list[float],
) -> str:
    answer = format_answer(valid_roots)
    if design_id == "rectangle":
        return (
            f"由面积关系得到 {_format_equation(a, b, c)}，"
            f"程序计算有效解为 {answer}。"
        )
    if design_id == "consecutive_even":
        return (
            f"由连续偶数关系得到 {_format_equation(a, b, c)}，"
            f"程序计算方程根为 {answer}。"
        )
    if design_id == "root_relation":
        root_sum = -b / a
        root_product = c / a
        return (
            f"由根与系数关系得到和 {root_sum:g}、积 {root_product:g}，"
            f"对应方程为 {_format_equation(a, b, c)}，程序解得 {answer}。"
        )
    return f"方程为 {_format_equation(a, b, c)}，程序解得 {answer}。"


def materialize_question(question: dict, *, regenerate_analysis: bool = False) -> dict:
    """校验语义并重算答案、有效根和参数验证元数据。"""
    stem = str(question.get("stem") or "").strip()
    params = dict(question.get("params") or {})
    design_id = str(params.get("design_id") or "")
    try:
        a = float(params["a"])
        b = float(params["b"])
        c = float(params["c"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("题目缺少合法的 a/b/c 参数") from exc

    semantic_validation = validate_stem_contract(
        stem, design_id=design_id, a=a, b=b, c=c
    )
    valid_roots = valid_roots_for(design_id, a, b, c)
    params.update({
        "valid_roots": valid_roots,
        "stem_contract": semantic_validation["facts"],
        "semantic_validation": {
            "status": semantic_validation["status"],
            "source": semantic_validation["source"],
            "issues": semantic_validation["issues"],
        },
    })
    materialized = dict(question)
    materialized.update({
        "stem": stem,
        "answer": format_answer(valid_roots),
        "params": params,
    })
    if regenerate_analysis or not materialized.get("analysis"):
        materialized["analysis"] = _build_analysis(
            design_id, a, b, c, valid_roots
        )
    return materialized
