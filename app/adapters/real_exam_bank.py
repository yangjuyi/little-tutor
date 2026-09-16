"""Load local real-exam data and structured specs."""

from __future__ import annotations

import json
from pathlib import Path

from app.domain.exam.specs import (
    DiscriminantChoiceSpec,
    ExpressionFromRootSpec,
    GrowthRateSpec,
    QuadraticRootsSpec,
    RootParameterSpec,
    RootReconstructionSpec,
)


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BANK = ROOT / "data" / "private_questions" / "middle_exam_math.json"
DEFAULT_GROWTH_SPECS = (
    ROOT / "data" / "private_questions" / "real_exam_growth_specs.json"
)
DEFAULT_ALGEBRA_SPECS = (
    ROOT / "data" / "private_questions" / "real_exam_algebra_specs.json"
)


def load_question_bank(path: Path = DEFAULT_BANK) -> dict:
    if not path.exists():
        return {"questions": []}
    return json.loads(path.read_text(encoding="utf-8"))


def load_growth_specs(path: Path = DEFAULT_GROWTH_SPECS) -> list[dict]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload.get("items") or []


def load_algebra_specs(path: Path = DEFAULT_ALGEBRA_SPECS) -> list[dict]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload.get("items") or []


def build_growth_rate_spec(item: dict) -> GrowthRateSpec:
    spec = item["spec"]
    return GrowthRateSpec(
        initial=spec["initial"],
        final=spec["final"],
        periods=spec["periods"],
        mode=spec.get("mode", "growth"),
        target=spec.get("target", "rate"),
        unknown=spec.get("unknown", "x"),
    )


def build_exam_spec(item: dict):
    spec = item["spec"]
    spec_type = spec["type"]
    if spec_type == "growth_rate":
        return build_growth_rate_spec(item)
    if spec_type == "quadratic_roots":
        return QuadraticRootsSpec(
            equation=spec["equation"],
            unknown=spec.get("unknown", "x"),
            root_filter=spec.get("root_filter", "all"),
        )
    if spec_type == "discriminant_choice":
        return DiscriminantChoiceSpec(
            choices=spec["choices"],
            unknown=spec.get("unknown", "x"),
            select=spec.get("select", "one_distinct"),
        )
    if spec_type == "root_reconstruction":
        return RootReconstructionSpec(
            root_sum=spec["root_sum"],
            root_product=spec["root_product"],
            leading=spec.get("leading", 1),
            unknown=spec.get("unknown", "x"),
        )
    if spec_type == "root_parameter":
        return RootParameterSpec(
            equation=spec["equation"],
            root_assignment=spec["root_assignment"],
            parameter=spec["parameter"],
            leading_expression=spec["leading_expression"],
        )
    if spec_type == "expression_from_root":
        return ExpressionFromRootSpec(
            equation=spec["equation"],
            root_symbol=spec["root_symbol"],
            target_expression=spec["target_expression"],
        )
    raise ValueError(f"未知真实题 spec 类型：{spec_type}")
