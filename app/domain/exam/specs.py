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
