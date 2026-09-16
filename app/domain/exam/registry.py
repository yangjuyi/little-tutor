"""Registry for structured real-exam solvers."""

from __future__ import annotations

from typing import Any

from app.domain.exam.solvers import (
    solve_discriminant_choice,
    solve_expression_from_root,
    solve_growth_rate,
    solve_quadratic_roots,
    solve_root_parameter,
    solve_root_reconstruction,
)
from app.domain.exam.specs import (
    DiscriminantChoiceSpec,
    ExpressionFromRootSpec,
    GrowthRateSpec,
    QuadraticRootsSpec,
    RootParameterSpec,
    RootReconstructionSpec,
)


def solve_exam_spec(spec: Any) -> dict[str, Any]:
    if isinstance(spec, GrowthRateSpec):
        return solve_growth_rate(spec)
    if isinstance(spec, QuadraticRootsSpec):
        return solve_quadratic_roots(spec)
    if isinstance(spec, DiscriminantChoiceSpec):
        return solve_discriminant_choice(spec)
    if isinstance(spec, RootReconstructionSpec):
        return solve_root_reconstruction(spec)
    if isinstance(spec, RootParameterSpec):
        return solve_root_parameter(spec)
    if isinstance(spec, ExpressionFromRootSpec):
        return solve_expression_from_root(spec)
    raise TypeError(f"暂不支持题型：{type(spec).__name__}")
