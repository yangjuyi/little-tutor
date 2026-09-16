"""Symbolic answer normalization and equivalence checks."""

from __future__ import annotations

import re
from fractions import Fraction

from sympy import Symbol, simplify, sympify
from sympy.parsing.sympy_parser import parse_expr


def parse_number(text: str) -> Fraction:
    raw = text.strip().replace(",", "")
    if raw.endswith("%"):
        return Fraction(raw[:-1]) / 100
    return Fraction(raw)


def numeric_equivalent(actual: str, expected: str) -> bool:
    try:
        return parse_number(actual) == parse_number(expected)
    except (ValueError, ZeroDivisionError):
        return False


def parse_math_expression(text: str, symbol: str):
    variable = Symbol(symbol)
    normalized = re.sub(r"(\d)\s*\(", r"\1*(", text)
    normalized = re.sub(r"(\d)\s*([A-Za-z])", r"\1*\2", normalized)
    normalized = (
        normalized.replace("²", "**2")
        .replace("^", "**")
        .replace("×", "*")
    )
    return parse_expr(
        normalized,
        local_dict={symbol: variable},
        evaluate=True,
    )


def equation_expression(text: str, symbol: str):
    if "=" not in text:
        raise ValueError("方程必须包含等号")
    left, right = text.split("=", 1)
    return (
        parse_math_expression(left, symbol)
        - parse_math_expression(right, symbol)
    )


def equation_equivalent(
    actual: str,
    expected: str,
    *,
    symbol: str = "x",
) -> bool:
    try:
        actual_expr = equation_expression(actual, symbol)
        expected_expr = equation_expression(expected, symbol)
    except Exception:
        return False
    return simplify(actual_expr - expected_expr) == 0


def expression_equivalent(
    actual: str,
    expected: str,
    *,
    symbol: str = "x",
) -> bool:
    try:
        actual_expr = parse_math_expression(actual, symbol)
        expected_expr = parse_math_expression(expected, symbol)
    except Exception:
        return False
    return simplify(actual_expr - expected_expr) == 0
