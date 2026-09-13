"""题干语义与结构化参数的一致性校验。"""

from __future__ import annotations

import math
import re


class StemContractError(ValueError):
    """题干事实与题目参数不一致，或题干无法按题型验证。"""


_NUMBER = r"[+-]?\d+(?:\.\d+)?"
_DESIGN_LABELS = {
    "direct": "直接求解题",
    "multi_step": "多步化简题",
    "rectangle": "长方形面积题",
    "consecutive_even": "连续偶数题",
    "root_relation": "根与系数题",
}


def _close(left: float, right: float) -> bool:
    return math.isclose(left, right, rel_tol=0.0, abs_tol=1e-9)


def _format_number(value: float) -> str:
    return f"{value:g}"


def _compare(
    label: str,
    actual: float,
    expected: float,
    issues: list[str],
) -> None:
    if not _close(actual, expected):
        issues.append(
            f"{label}不一致：题干为 {_format_number(actual)}，"
            f"参数要求为 {_format_number(expected)}"
        )


def _raise_issues(issues: list[str], design_id: str) -> None:
    if issues:
        raise StemContractError(
            f"{_DESIGN_LABELS.get(design_id, '当前题型')}题干与参数冲突："
            + "；".join(issues)
        )


def _coefficient(text: str) -> float:
    value = text.strip()
    if value in ("", "+"):
        return 1.0
    if value == "-":
        return -1.0
    return float(value)


def _parse_polynomial_equation(stem: str) -> dict[str, float]:
    text = (
        stem.replace("−", "-")
        .replace("－", "-")
        .replace("＝", "=")
        .replace("²", "^2")
    )
    match = re.search(
        r"(?P<expr>[+-]?\s*(?:\d+(?:\.\d+)?)?\s*x\s*\^2"
        r"[^，。；]*?=\s*0)",
        text,
    )
    if match is None:
        raise StemContractError("题干中未找到形如 ax^2+bx+c=0 的方程")

    left = match.group("expr").split("=", 1)[0].replace(" ", "")
    terms = re.findall(r"[+-]?[^+-]+", left)
    if not terms:
        raise StemContractError("题干方程无法解析")

    coefficients = {"a": 0.0, "b": 0.0, "c": 0.0}
    for term in terms:
        if "x^2" in term:
            coefficients["a"] += _coefficient(term.split("x", 1)[0])
        elif "x" in term:
            coefficients["b"] += _coefficient(term.split("x", 1)[0])
        else:
            coefficients["c"] += float(term)
    if _close(coefficients["a"], 0.0):
        raise StemContractError("题干方程缺少二次项")
    return {
        "equation_a": coefficients["a"],
        "equation_b": coefficients["b"],
        "equation_c": coefficients["c"],
    }


def _validate_polynomial(
    stem: str,
    *,
    a: float,
    b: float,
    c: float,
    design_id: str,
) -> dict[str, float]:
    facts = _parse_polynomial_equation(stem)
    issues: list[str] = []
    _compare("二次项系数", facts["equation_a"], a, issues)
    _compare("一次项系数", facts["equation_b"], b, issues)
    _compare("常数项", facts["equation_c"], c, issues)
    _raise_issues(issues, design_id)
    return facts


def _validate_rectangle(
    stem: str,
    *,
    a: float,
    b: float,
    c: float,
) -> dict[str, float]:
    if re.search(r"宽为\s*x\s*米", stem) is None:
        raise StemContractError("长方形题必须声明“宽为 x 米”")

    scaled = re.search(
        rf"长比宽的\s*({_NUMBER})\s*倍多\s*({_NUMBER})\s*米",
        stem,
    )
    simple = re.search(
        rf"长比宽多\s*({_NUMBER})\s*米",
        stem,
    )
    area_match = re.search(
        rf"面积为\s*({_NUMBER})\s*平方米",
        stem,
    )
    if area_match is None:
        raise StemContractError("长方形题必须声明“面积为 S 平方米”")

    if scaled:
        stem_a = float(scaled.group(1))
        stem_b = float(scaled.group(2))
    elif simple:
        stem_a = 1.0
        stem_b = float(simple.group(1))
    else:
        raise StemContractError("长方形题必须声明长与宽的数量关系")

    area = float(area_match.group(1))
    issues: list[str] = []
    _compare("长宽关系中的倍数", stem_a, a, issues)
    _compare("长比宽多出的长度", stem_b, b, issues)
    _compare("面积", area, -c, issues)
    _raise_issues(issues, "rectangle")
    return {
        "relation_scale": stem_a,
        "relation_offset": stem_b,
        "area": area,
    }


def _validate_consecutive_even(
    stem: str,
    *,
    a: float,
    b: float,
    c: float,
) -> dict[str, float]:
    if "连续偶数" not in stem or "较小的偶数为 x" not in stem:
        raise StemContractError(
            "连续偶数题必须声明“两个连续偶数”和“较小的偶数为 x”"
        )
    product_match = re.search(
        rf"积(?:是|为)\s*({_NUMBER})",
        stem,
    )
    if product_match is None:
        raise StemContractError("连续偶数题必须声明两个偶数的积")

    product = float(product_match.group(1))
    issues: list[str] = []
    _compare("二次项系数", 1.0, a, issues)
    _compare("一次项系数", 2.0, b, issues)
    _compare("常数项对应的乘积", product, -c, issues)
    if product <= 0:
        issues.append("两个连续偶数的积必须为正数")
        _raise_issues(issues, "consecutive_even")
    if not product.is_integer():
        issues.append("两个连续偶数的积必须为整数")
        _raise_issues(issues, "consecutive_even")

    root = math.isqrt(int(product + 1))
    if root * root != product + 1 or (root - 1) % 2 != 0:
        issues.append(f"积 {_format_number(product)} 不能对应两个连续偶数")
    _raise_issues(issues, "consecutive_even")
    return {"product": product, "smaller_even": float(root - 1)}


def _validate_root_relation(
    stem: str,
    *,
    a: float,
    b: float,
    c: float,
) -> dict[str, float]:
    try:
        return _validate_polynomial(
            stem, a=a, b=b, c=c, design_id="root_relation"
        )
    except StemContractError as equation_error:
        root_sum = re.search(rf"两个根的和为\s*({_NUMBER})", stem)
        root_product = re.search(rf"积为\s*({_NUMBER})", stem)
        leading = re.search(rf"二次项系数为\s*({_NUMBER})", stem)
        if root_sum is None or root_product is None or leading is None:
            raise equation_error

        stem_a = float(leading.group(1))
        stem_sum = float(root_sum.group(1))
        stem_product = float(root_product.group(1))
        issues: list[str] = []
        _compare("二次项系数", stem_a, a, issues)
        _compare("两根之和", stem_sum, -b / a, issues)
        _compare("两根之积", stem_product, c / a, issues)
        _raise_issues(issues, "root_relation")
        return {
            "leading_coefficient": stem_a,
            "root_sum": stem_sum,
            "root_product": stem_product,
        }


def validate_stem_contract(
    stem: str,
    *,
    design_id: str,
    a: float,
    b: float,
    c: float,
) -> dict:
    """提取题干事实并验证其与 a/b/c 一致，返回可审计的验证结果。"""
    if not stem.strip():
        raise StemContractError("题干不能为空")
    if design_id in ("direct", "multi_step"):
        facts = _validate_polynomial(
            stem, a=a, b=b, c=c, design_id=design_id
        )
    elif design_id == "rectangle":
        facts = _validate_rectangle(stem, a=a, b=b, c=c)
    elif design_id == "consecutive_even":
        facts = _validate_consecutive_even(stem, a=a, b=b, c=c)
    elif design_id == "root_relation":
        facts = _validate_root_relation(stem, a=a, b=b, c=c)
    else:
        raise StemContractError(
            f"题型 {design_id or '<缺失>'} 暂无程序化题干校验契约"
        )
    return {
        "status": "verified",
        "source": "program",
        "issues": [],
        "facts": facts,
    }
