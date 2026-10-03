"""Question materialization and grading for structured real-exam items."""

from __future__ import annotations

import re
from typing import Any

from app.domain.exam.answer_equiv import (
    choice_equivalent,
    equation_equivalent,
    expression_equivalent,
    extract_labelled_values,
    numeric_equivalent,
    values_equivalent,
)
from app.domain.exam.registry import solve_exam_spec
from app.domain.exam.specs import build_exam_spec_from_dict


DEFAULT_TARGETS = {
    "growth_rate": "rate",
    "discriminant_choice": "choice",
    "root_reconstruction": "equation",
    "root_parameter": "parameter",
    "expression_from_root": "expression",
    "quadratic_roots": "roots",
}


def solve_question_spec(question: dict) -> dict[str, Any]:
    params = dict(question.get("params") or {})
    payload = params.get("exam_spec")
    if not payload:
        raise ValueError("结构化真题缺少 exam_spec")
    return solve_exam_spec(build_exam_spec_from_dict(payload))


def _default_target(solution: dict[str, Any]) -> str:
    result_type = str(solution.get("type") or "")
    target = DEFAULT_TARGETS.get(result_type)
    if target:
        return target
    if "=" in str(solution.get("answer") or ""):
        return "equation"
    return "expression"


def _expected_values(answer: Any) -> list[str]:
    if isinstance(answer, (list, tuple)):
        return [str(value) for value in answer]
    return [str(answer)]


def _equation_symbol(expected: str) -> str:
    match = re.search(r"([A-Za-z])", expected)
    return match.group(1) if match else "x"


def _strip_parameter_labels(values: list[str]) -> tuple[list[str], str]:
    symbol = "x"
    stripped: list[str] = []
    for value in values:
        if "=" in value:
            left, right = value.split("=", 1)
            symbol = left.strip() or symbol
            stripped.append(right.strip())
        else:
            stripped.append(value)
    return stripped, symbol


def _answer_text(answer: Any, target: str) -> str:
    values = _expected_values(answer)
    if target == "roots":
        return " 或 ".join(values)
    if target in {"choice", "parameter"}:
        return "、".join(values)
    return values[0] if values else ""


def materialize_structured_exam(question: dict) -> dict:
    params = dict(question.get("params") or {})
    solution = solve_question_spec(question)
    params["target"] = (
        params.get("target")
        or solution.get("target")
        or (params.get("exam_spec") or {}).get("target")
        or _default_target(solution)
    )
    materialized = dict(question)
    materialized.update({
        "stem": str(question.get("stem") or "").strip(),
        "answer": _answer_text(solution["answer"], params["target"]),
        "params": params,
    })
    if not materialized.get("analysis"):
        equation = solution.get("equation")
        if solution.get("type") == "growth_rate" and equation:
            materialized["analysis"] = (
                f"按平均变化率模型列出 {equation}，"
                f"再由程序筛选符合实际意义的解。"
            )
        else:
            materialized["analysis"] = "由程序按结构化题型重算标准答案。"
    return materialized


def check_structured_exam_answer(question: dict, student_answer: str) -> bool:
    if not str(student_answer or "").strip():
        return False
    solution = solve_question_spec(question)
    params = dict(question.get("params") or {})
    target = (
        params.get("target")
        or solution.get("target")
        or (params.get("exam_spec") or {}).get("target")
        or _default_target(solution)
    )
    answer = solution["answer"]
    expected_values = _expected_values(answer)
    if target == "equation":
        return equation_equivalent(
            student_answer,
            expected_values[0],
            symbol=_equation_symbol(expected_values[0]),
        )
    if target == "rate":
        return numeric_equivalent(student_answer, expected_values[0])
    if target == "choice":
        return choice_equivalent(student_answer, expected_values)
    if target == "expression":
        return expression_equivalent(
            student_answer,
            expected_values[0],
        )
    if target == "parameter":
        actual_values = extract_labelled_values(student_answer) or [
            student_answer
        ]
        expected, symbol = _strip_parameter_labels(expected_values)
        return values_equivalent(actual_values, expected, symbol=symbol)
    if target == "roots":
        actual_values = extract_labelled_values(student_answer) or [
            student_answer
        ]
        return values_equivalent(actual_values, expected_values)
    raise ValueError(f"暂不支持的结构化真题作答目标：{target}")
