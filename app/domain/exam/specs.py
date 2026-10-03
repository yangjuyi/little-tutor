"""Typed specifications for real-exam question families."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class GrowthRateSpec:
    initial: float
    final: float
    periods: int
    mode: Literal["growth", "decay"] = "growth"
    target: Literal["rate", "equation"] = "rate"
    unknown: str = "x"

    def __post_init__(self) -> None:
        if self.initial <= 0 or self.final <= 0:
            raise ValueError("initial 和 final 必须为正数")
        if self.periods <= 0:
            raise ValueError("periods 必须为正整数")
        if self.mode == "growth" and self.final <= self.initial:
            raise ValueError("growth 模式要求 final > initial")
        if self.mode == "decay" and self.final >= self.initial:
            raise ValueError("decay 模式要求 final < initial")
        if not self.unknown.isidentifier():
            raise ValueError("unknown 必须是合法变量名")


@dataclass(frozen=True)
class QuadraticRootsSpec:
    equation: str
    unknown: str = "x"
    root_filter: Literal["all", "positive", "negative", "nonzero"] = "all"


@dataclass(frozen=True)
class DiscriminantChoiceSpec:
    choices: dict[str, str]
    unknown: str = "x"
    select: Literal[
        "no_real",
        "one_distinct",
        "two_distinct",
    ] = "one_distinct"


@dataclass(frozen=True)
class RootReconstructionSpec:
    root_sum: float
    root_product: float
    leading: float = 1
    unknown: str = "x"


@dataclass(frozen=True)
class RootParameterSpec:
    equation: str
    root_assignment: str
    parameter: str
    leading_expression: str


@dataclass(frozen=True)
class ExpressionFromRootSpec:
    equation: str
    root_symbol: str
    target_expression: str


def build_exam_spec_from_dict(payload: dict):
    """Build a typed exam spec from a persisted JSON payload."""
    spec_type = payload["type"]
    if spec_type == "growth_rate":
        return GrowthRateSpec(
            initial=payload["initial"],
            final=payload["final"],
            periods=payload["periods"],
            mode=payload.get("mode", "growth"),
            target=payload.get("target", "rate"),
            unknown=payload.get("unknown", "x"),
        )
    if spec_type == "quadratic_roots":
        return QuadraticRootsSpec(
            equation=payload["equation"],
            unknown=payload.get("unknown", "x"),
            root_filter=payload.get("root_filter", "all"),
        )
    if spec_type == "discriminant_choice":
        return DiscriminantChoiceSpec(
            choices=payload["choices"],
            unknown=payload.get("unknown", "x"),
            select=payload.get("select", "one_distinct"),
        )
    if spec_type == "root_reconstruction":
        return RootReconstructionSpec(
            root_sum=payload["root_sum"],
            root_product=payload["root_product"],
            leading=payload.get("leading", 1),
            unknown=payload.get("unknown", "x"),
        )
    if spec_type == "root_parameter":
        return RootParameterSpec(
            equation=payload["equation"],
            root_assignment=payload["root_assignment"],
            parameter=payload["parameter"],
            leading_expression=payload["leading_expression"],
        )
    if spec_type == "expression_from_root":
        return ExpressionFromRootSpec(
            equation=payload["equation"],
            root_symbol=payload["root_symbol"],
            target_expression=payload["target_expression"],
        )
    raise ValueError(f"未知真实题 spec 类型：{spec_type}")
