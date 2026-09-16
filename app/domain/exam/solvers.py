"""Program solvers for structured real-exam question families."""

from __future__ import annotations

from fractions import Fraction
from typing import Any

from sympy import (
    Eq,
    Poly,
    S,
    Symbol,
    FiniteSet,
    im,
    nsimplify,
    re,
    simplify,
    solve,
    solveset,
    sympify,
)

from app.domain.exam.answer_equiv import (
    equation_equivalent,
    equation_expression,
    numeric_equivalent,
    parse_math_expression,
)
from app.domain.exam.specs import (
    DiscriminantChoiceSpec,
    ExpressionFromRootSpec,
    GrowthRateSpec,
    QuadraticRootsSpec,
    RootParameterSpec,
    RootReconstructionSpec,
)


def _format_ratio(value: Fraction) -> str:
    if value.denominator == 1:
        return str(value.numerator)
    return f"{value.numerator}/{value.denominator}"


def _format_percent(value: Fraction) -> str:
    percent = value * 100
    return f"{_format_ratio(percent)}%"


def _equation_text(spec: GrowthRateSpec) -> str:
    operator = "+" if spec.mode == "growth" else "-"
    return (
        f"{spec.initial:g}(1{operator}{spec.unknown})"
        f"^{spec.periods}={spec.final:g}"
    )


def solve_growth_rate(spec: GrowthRateSpec) -> dict[str, Any]:
    variable = Symbol(spec.unknown)
    operator = "+" if spec.mode == "growth" else "-"
    equation = Eq(
        spec.initial * (1 + (variable if operator == "+" else -variable))
        ** spec.periods,
        spec.final,
    )
    solutions = solve(equation, variable)
    valid = []
    for solution in solutions:
        if im(solution) != 0:
            continue
        if spec.mode == "growth" and solution > 0:
            valid.append(solution)
        if spec.mode == "decay" and 0 < solution < 1:
            valid.append(solution)
    if len(valid) != 1:
        raise ValueError(f"增长率题有效解数量异常：{valid}")

    if spec.target == "rate":
        rate = Fraction(
            str(nsimplify(valid[0], rational=True, tolerance=1e-12))
        )
        rate_text = _format_ratio(rate)
        answer = _format_percent(rate)
        valid_solutions = [_format_percent(rate)]
    else:
        rate_text = str(valid[0])
        answer = _equation_text(spec)
        valid_solutions = [str(valid[0])]
    return {
        "type": "growth_rate",
        "equation": _equation_text(spec),
        "rate": rate_text,
        "target": spec.target,
        "answer": answer,
        "valid_solutions": valid_solutions,
        "all_solutions": [str(value) for value in solutions],
    }


def verify_growth_rate_result(
    result: dict[str, Any],
    *,
    expected: str,
    target: str,
) -> bool:
    if target == "rate":
        return numeric_equivalent(result["answer"], expected)
    if target == "equation":
        return equation_equivalent(result["answer"], expected)
    raise ValueError(f"未知 target: {target}")


def solve_quadratic_roots(spec: QuadraticRootsSpec) -> dict[str, Any]:
    variable = Symbol(spec.unknown)
    expression = equation_expression(spec.equation, spec.unknown)
    solution_set = solveset(
        Eq(expression, 0),
        variable,
        domain=S.Reals,
    )
    solutions = (
        list(solution_set)
        if isinstance(solution_set, FiniteSet)
        else [value for value in solve(expression, variable) if value.is_real]
    )
    if spec.root_filter == "positive":
        solutions = [value for value in solutions if value > 0]
    elif spec.root_filter == "negative":
        solutions = [value for value in solutions if value < 0]
    elif spec.root_filter == "nonzero":
        solutions = [value for value in solutions if value != 0]
    solutions = sorted(set(solutions), key=lambda value: float(value))
    return {
        "type": "quadratic_roots",
        "equation": spec.equation,
        "answer": [str(value) for value in solutions],
        "valid_solutions": [str(value) for value in solutions],
    }


def _distinct_real_root_count(expression, variable: Symbol) -> int:
    solution_set = solveset(
        Eq(expression, 0),
        variable,
        domain=S.Reals,
    )
    roots = (
        list(solution_set)
        if isinstance(solution_set, FiniteSet)
        else [value for value in solve(expression, variable) if value.is_real]
    )
    return len(set(roots))


def solve_discriminant_choice(
    spec: DiscriminantChoiceSpec,
) -> dict[str, Any]:
    variable = Symbol(spec.unknown)
    wanted = {
        "no_real": 0,
        "one_distinct": 1,
        "two_distinct": 2,
    }[spec.select]
    matched = []
    counts = {}
    for label, equation in spec.choices.items():
        count = _distinct_real_root_count(
            equation_expression(equation, spec.unknown),
            variable,
        )
        counts[label] = count
        if count == wanted:
            matched.append(label)
    return {
        "type": "discriminant_choice",
        "select": spec.select,
        "answer": matched,
        "root_counts": counts,
        "valid_solutions": matched,
    }


def solve_root_reconstruction(
    spec: RootReconstructionSpec,
) -> dict[str, Any]:
    a = sympify(spec.leading)
    root_sum = sympify(spec.root_sum)
    root_product = sympify(spec.root_product)
    equation = (
        f"{a}*{spec.unknown}**2"
        f"-{a * root_sum}*{spec.unknown}+{a * root_product}=0"
    )
    return {
        "type": "root_reconstruction",
        "answer": equation,
        "root_sum": str(root_sum),
        "root_product": str(root_product),
        "valid_solutions": [equation],
    }


def solve_root_parameter(spec: RootParameterSpec) -> dict[str, Any]:
    root_name, root_value = spec.root_assignment.split("=", 1)
    equation = equation_expression(spec.equation, root_name.strip())
    parameter = Symbol(spec.parameter)
    substituted = equation.subs(Symbol(root_name.strip()), sympify(root_value))
    candidates = solve(substituted, parameter)
    leading = parse_math_expression(
        spec.leading_expression,
        spec.parameter,
    )
    valid = [
        value
        for value in candidates
        if simplify(leading.subs(parameter, value)) != 0
    ]
    return {
        "type": "root_parameter",
        "answer": [f"{spec.parameter}={value}" for value in valid],
        "all_candidates": [str(value) for value in candidates],
        "valid_solutions": [str(value) for value in valid],
    }


def solve_expression_from_root(
    spec: ExpressionFromRootSpec,
) -> dict[str, Any]:
    variable = Symbol(spec.root_symbol)
    equation_poly = Poly(
        equation_expression(spec.equation, spec.root_symbol),
        variable,
    )
    target = parse_math_expression(
        spec.target_expression,
        spec.root_symbol,
    )
    target_poly = Poly(target, variable)
    remainder = target_poly.rem(equation_poly)
    reduced = simplify(remainder.as_expr())
    return {
        "type": "expression_from_root",
        "answer": str(reduced),
        "target_expression": spec.target_expression,
        "valid_solutions": [str(reduced)],
    }
