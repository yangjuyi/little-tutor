"""过程诊断：检查学生相邻步骤之间的数学转换是否成立。

当前垂直切片只覆盖一元一次/二次方程。判定器只依据程序可验证的事实，
无法解析或证据不足时返回“无法判断”，不伪造错因。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal, Sequence

from sympy import Eq, Expr, FiniteSet, S, Symbol, sympify
from sympy.parsing.sympy_parser import (
    convert_xor,
    implicit_multiplication_application,
    parse_expr,
    standard_transformations,
)
from sympy.solvers.solveset import solveset

from app.domain.models import StudentStepV2, Submission, TransitionCheck
from app.domain.types import ErrorType

_X = Symbol("x")
_TRANSFORMS = standard_transformations + (
    convert_xor,
    implicit_multiplication_application,
)
_LATEX_FRAC = re.compile(r"\\frac\{([^{}]+)\}\{([^{}]+)\}")
_LATEX_SQRT = re.compile(r"\\sqrt\{([^{}]+)\}")
_ROOT_LABEL = re.compile(r"\b[xX]\s*_?\s*(?:[0-9₁₂₃₄₅₆₇₈₉]+)\s*=")
_PART_SPLIT = re.compile(r"\bor\b|\s+或\s+|,|，|;|；")
_SUPERSCRIPT = {
    "⁰": "**0",
    "¹": "**1",
    "²": "**2",
    "³": "**3",
    "⁴": "**4",
    "⁵": "**5",
    "⁶": "**6",
    "⁷": "**7",
    "⁸": "**8",
    "⁹": "**9",
}


class _ParseError(ValueError):
    pass


@dataclass(frozen=True)
class _StepAnalysis:
    kind: Literal["equation", "roots", "invalid"]
    expression: Expr | None = None
    roots: frozenset[Expr] = frozenset()
    evidence: str = ""


def _normalize(text: str) -> str:
    value = text.strip().strip("$")
    value = _LATEX_FRAC.sub(r"((\1)/(\2))", value)
    value = _LATEX_SQRT.sub(r"sqrt(\1)", value)
    value = value.replace("\\left", "").replace("\\right", "")
    value = value.replace("\\,", "").replace("\\!", "").replace("\\;", "")
    value = value.replace("\\ ", "")
    value = value.replace("×", "*").replace("·", "*")
    value = value.replace("÷", "/").replace("−", "-")
    value = value.replace("√", "sqrt")
    for superscript, power in _SUPERSCRIPT.items():
        value = value.replace(superscript, power)
    value = _ROOT_LABEL.sub("x=", value)
    value = value.replace("{", "").replace("}", "")
    return re.sub(r"\s+", " ", value).strip()


def _parse_expr(value: str) -> Expr:
    try:
        return parse_expr(
            value,
            transformations=_TRANSFORMS,
            local_dict={"x": _X},
        )
    except Exception as exc:  # SymPy 的解析异常类型较杂，统一转成领域错误
        raise _ParseError(str(exc)) from exc


def _parse_equations(text: str) -> list[Eq]:
    normalized = _normalize(text)
    if not normalized:
        raise _ParseError("空步骤")
    equations: list[Eq] = []
    for part in _PART_SPLIT.split(normalized):
        part = part.strip()
        if not part:
            continue
        if "=" in part:
            left, right = part.split("=", 1)
            equations.append(Eq(_parse_expr(left), _parse_expr(right)))
        else:
            equations.append(Eq(_parse_expr(part), S.Zero))
    if not equations:
        raise _ParseError("没有可解析的方程")
    return equations


def _only_x(expression: Expr) -> bool:
    return expression.free_symbols <= {_X}


def _polynomial_degree(expression: Expr) -> int | None:
    if not _only_x(expression):
        return None
    try:
        return int(expression.as_poly(_X).degree())
    except Exception:
        return None


def _roots_of(expression: Expr) -> frozenset[Expr] | None:
    try:
        roots = solveset(expression, _X, domain=S.Reals)
    except Exception:
        return None
    if isinstance(roots, FiniteSet):
        return frozenset(roots)
    if roots is S.EmptySet:
        return frozenset()
    return None


def _root_assignment(equation: Eq) -> Expr | None:
    left, right = equation.lhs, equation.rhs
    if left == _X and not right.has(_X):
        return right
    if right == _X and not left.has(_X):
        return left
    return None


def _analyze_step(text: str) -> _StepAnalysis:
    try:
        equations = _parse_equations(text)
    except _ParseError as exc:
        return _StepAnalysis(kind="invalid", evidence=f"无法解析：{exc}")

    for equation in equations:
        if not (_only_x(equation.lhs) and _only_x(equation.rhs)):
            return _StepAnalysis(
                kind="invalid",
                evidence="当前只支持含未知数 x 的一元方程",
            )

    root_values = [_root_assignment(equation) for equation in equations]
    if all(value is not None for value in root_values):
        return _StepAnalysis(
            kind="roots",
            roots=frozenset(value for value in root_values if value is not None),
            evidence="识别为根的集合",
        )

    if len(equations) != 1:
        return _StepAnalysis(
            kind="invalid",
            evidence="多方程步骤必须是 x=... 的根集合",
        )

    expression = equations[0].lhs - equations[0].rhs
    degree = _polynomial_degree(expression)
    if degree is None or degree > 2:
        return _StepAnalysis(
            kind="invalid",
            evidence="当前只支持一元一次/二次方程",
        )
    roots = _roots_of(expression)
    if roots is None:
        return _StepAnalysis(kind="invalid", evidence="无法求出方程的根")
    return _StepAnalysis(kind="equation", expression=expression, roots=roots)


def _equivalent(left: Expr, right: Expr) -> bool:
    try:
        return bool(sympify(left - right).equals(0))
    except Exception:
        return False


def _format_roots(roots: frozenset[Expr]) -> str:
    if not roots:
        return "∅"
    try:
        ordered = sorted(roots, key=lambda value: float(value))
    except Exception:
        ordered = sorted(roots, key=str)
    return ", ".join(str(value) for value in ordered)


def _root_mismatch_error(
    previous_roots: frozenset[Expr],
    current_roots: frozenset[Expr],
) -> ErrorType | None:
    lost = previous_roots - current_roots
    introduced = current_roots - previous_roots
    if lost and not introduced:
        return "漏根"
    if introduced:
        return "计算"
    return None


def _check_result(
    previous: StudentStepV2,
    current: StudentStepV2,
    *,
    is_valid: bool,
    rule: str,
    evidence: str,
    error_type: ErrorType | None = None,
    confidence: float,
    insufficient_evidence: bool,
) -> TransitionCheck:
    return {
        "from_step": previous["step_no"],
        "to_step": current["step_no"],
        "is_valid": is_valid,
        "rule": rule,
        "error_type": error_type,
        "evidence": evidence,
        "confidence": confidence,
        "insufficient_evidence": insufficient_evidence,
    }


def check_transition(
    previous: StudentStepV2,
    current: StudentStepV2,
) -> TransitionCheck:
    """检查两个相邻步骤之间的转换是否成立。"""
    previous_analysis = _analyze_step(previous["raw_latex"])
    current_analysis = _analyze_step(current["raw_latex"])

    if previous_analysis.kind == "invalid" or current_analysis.kind == "invalid":
        evidence = "；".join(
            part
            for part in (previous_analysis.evidence, current_analysis.evidence)
            if part
        )
        return _check_result(
            previous,
            current,
            is_valid=False,
            rule="无法判断",
            evidence=evidence or "当前诊断器无法解析该步骤",
            confidence=0.0,
            insufficient_evidence=True,
        )

    if (
        previous_analysis.kind == "equation"
        and current_analysis.kind == "equation"
        and previous_analysis.expression is not None
        and current_analysis.expression is not None
    ):
        if _equivalent(previous_analysis.expression, current_analysis.expression):
            return _check_result(
                previous,
                current,
                is_valid=True,
                rule="等价变形",
                evidence="两步方程同解",
                confidence=0.9,
                insufficient_evidence=False,
            )
        error_type = _root_mismatch_error(
            previous_analysis.roots, current_analysis.roots
        )
        if error_type is None:
            return _check_result(
                previous,
                current,
                is_valid=False,
                rule="方程变形不等价",
                evidence=(
                    f"原方程根={_format_roots(previous_analysis.roots)}，"
                    f"下一步根={_format_roots(current_analysis.roots)}"
                ),
                confidence=0.3,
                insufficient_evidence=True,
            )
        return _check_result(
            previous,
            current,
            is_valid=False,
            rule="方程变形改变了根集合",
            error_type=error_type,
            evidence=(
                f"原方程根={_format_roots(previous_analysis.roots)}，"
                f"下一步根={_format_roots(current_analysis.roots)}"
            ),
            confidence=0.8,
            insufficient_evidence=False,
        )

    if previous_analysis.kind == "equation" and current_analysis.kind == "roots":
        if previous_analysis.roots == current_analysis.roots:
            return _check_result(
                previous,
                current,
                is_valid=True,
                rule="直接给出根",
                evidence="根覆盖完整；未记录中间变形",
                confidence=0.6,
                insufficient_evidence=True,
            )
        error_type = _root_mismatch_error(
            previous_analysis.roots, current_analysis.roots
        )
        return _check_result(
            previous,
            current,
            is_valid=False,
            rule="根集合不完整",
            error_type=error_type,
            evidence=(
                f"原方程根={_format_roots(previous_analysis.roots)}，"
                f"学生给出={_format_roots(current_analysis.roots)}"
            ),
            confidence=0.8,
            insufficient_evidence=False,
        )

    if previous_analysis.kind == "roots" and current_analysis.kind == "roots":
        if previous_analysis.roots == current_analysis.roots:
            return _check_result(
                previous,
                current,
                is_valid=True,
                rule="根集合一致",
                evidence="根没有变化",
                confidence=0.8,
                insufficient_evidence=False,
            )
        return _check_result(
            previous,
            current,
            is_valid=False,
            rule="根集合发生变化",
            error_type=_root_mismatch_error(
                previous_analysis.roots, current_analysis.roots
            ),
            evidence=(
                f"上一步根={_format_roots(previous_analysis.roots)}，"
                f"这一步根={_format_roots(current_analysis.roots)}"
            ),
            confidence=0.8,
            insufficient_evidence=False,
        )

    return _check_result(
        previous,
        current,
        is_valid=False,
        rule="无法判断",
        evidence="当前诊断器不支持这种步骤转换",
        confidence=0.0,
        insufficient_evidence=True,
    )


def diagnose_transitions(
    steps: Sequence[StudentStepV2],
) -> list[TransitionCheck]:
    """按学生步骤顺序检查每一次相邻转换。"""
    ordered = sorted(steps, key=lambda step: step["step_no"])
    return [
        check_transition(previous, current)
        for previous, current in zip(ordered, ordered[1:])
    ]


def first_invalid_transition(
    checks: Sequence[TransitionCheck],
) -> TransitionCheck | None:
    return next((check for check in checks if not check["is_valid"]), None)


def diagnose_submission(submission: Submission) -> list[TransitionCheck]:
    if submission["mode"] == "final_answer_only":
        return []
    return diagnose_transitions(submission["steps"])
