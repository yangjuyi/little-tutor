"""Structured real-exam solving capabilities."""

from app.domain.exam.registry import solve_exam_spec
from app.domain.exam.specs import (
    DiscriminantChoiceSpec,
    ExpressionFromRootSpec,
    GrowthRateSpec,
    QuadraticRootsSpec,
    RootParameterSpec,
    RootReconstructionSpec,
)

__all__ = [
    "DiscriminantChoiceSpec",
    "ExpressionFromRootSpec",
    "GrowthRateSpec",
    "QuadraticRootsSpec",
    "RootParameterSpec",
    "RootReconstructionSpec",
    "solve_exam_spec",
]
