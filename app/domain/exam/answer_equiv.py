"""Symbolic answer normalization and equivalence checks."""

from __future__ import annotations

import re
from fractions import Fraction

from sympy import Symbol, simplify
from sympy.parsing.sympy_parser import parse_expr


_LABELLED_VALUE = re.compile(
    r"(?<![A-Za-z0-9_])([A-Za-z])\s*_?\s*[0-9₁₂₃₄₅₆₇₈₉₀]*\s*="
)
_VALUE_SEPARATOR = re.compile(r"(?:或|、|，|,|;|；)+")


def _normalize_math_text(text: str) -> str:
    return (
        str(text)
        .replace("（", "(")
        .replace("）", ")")
        .replace("＋", "+")
        .replace("－", "-")
        .replace("＝", "=")
        .replace("＊", "*")
        .replace("×", "*")
        .replace("²", "**2")
        .replace("^", "**")
    )


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
    normalized = _normalize_math_text(text)
    normalized = re.sub(r"(\d)\s*\(", r"\1*(", normalized)
    normalized = re.sub(r"(\d)\s*([A-Za-z])", r"\1*\2", normalized)
    return parse_expr(
        normalized,
        local_dict={symbol: variable},
        evaluate=True,
    )


def equation_expression(text: str, symbol: str):
    normalized = _normalize_math_text(text)
    if "=" not in normalized:
        raise ValueError("方程必须包含等号")
    left, right = normalized.split("=", 1)
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


def extract_labelled_values(text: str) -> list[str]:
    """Extract values following labels such as x=, x1=, x₂=, a=."""
    matches = list(_LABELLED_VALUE.finditer(str(text or "")))
    if not matches:
        return []
    values: list[str] = []
    for index, match in enumerate(matches):
        end = (
            matches[index + 1].start()
            if index + 1 < len(matches)
            else len(text)
        )
        segment = text[match.end():end]
        segment = re.split(
            r"[（(]\s*(?:舍去|舍|不成立|不符合题意).*?[）)]",
            segment,
            maxsplit=1,
        )[0]
        for value in _VALUE_SEPARATOR.split(segment):
            candidate = value.strip().strip(".。")
            if candidate:
                values.append(candidate)
    return values


def values_equivalent(
    actual_values: list[str],
    expected_values: list[str],
    *,
    symbol: str = "x",
) -> bool:
    """Compare exact value sets, allowing symbolic equivalences."""
    actual = [str(value).strip() for value in actual_values if str(value).strip()]
    expected = [
        str(value).strip() for value in expected_values if str(value).strip()
    ]
    if len(actual) != len(expected):
        return False
    remaining = list(expected)
    for actual_value in actual:
        for index, expected_value in enumerate(remaining):
            if expression_equivalent(
                actual_value,
                expected_value,
                symbol=symbol,
            ):
                remaining.pop(index)
                break
        else:
            return False
    return not remaining


def choice_equivalent(actual: str, expected: list[str]) -> bool:
    """Compare choice labels while accepting either letters or 1-based numbers."""
    text = str(actual or "").strip().upper().strip("。.")
    expected_labels = [
        str(value).strip().upper().strip("。.")
        for value in expected
        if str(value).strip()
    ]
    if not expected_labels:
        return False
    if len(expected_labels) == 1:
        expected_label = expected_labels[0]
        if len(expected_label) == 1 and expected_label.isalpha():
            number = str(ord(expected_label) - ord("A") + 1)
            return text in {expected_label, number}
    return text in expected_labels
