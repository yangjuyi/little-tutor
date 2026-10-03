"""Coarse error-type driven training focus.

This is a small, explainable bridge between attribution and question
selection. It is intentionally not a full curriculum planner.
"""

from __future__ import annotations

from typing import Iterable


ERROR_TYPE_TAGS: dict[str, tuple[str, ...]] = {
    "审题": ("reading", "modeling"),
    "概念": ("concept", "formula"),
    "计算": ("calculation", "basic_operation"),
    "跳步": ("process", "multi_step"),
    "粗心": ("calculation", "careful_check"),
    "无错": (),
    "未归因": (),
}

DESIGN_TAGS: dict[str, tuple[str, ...]] = {
    "direct": ("basic_operation", "calculation"),
    "consecutive_even": ("reading", "modeling", "equation_setup"),
    "rectangle": ("reading", "modeling", "equation_setup"),
    "root_relation": ("concept", "formula", "calculation"),
    "multi_step": ("process", "multi_step", "calculation"),
}

QUESTION_TYPE_TAGS: dict[str, tuple[str, ...]] = {
    "growth_rate": ("reading", "modeling", "equation_setup", "calculation"),
    "discriminant_choice": ("concept", "formula", "calculation"),
}

TAG_LABELS: dict[str, str] = {
    "reading": "审题与条件提取",
    "modeling": "情境建模",
    "equation_setup": "列方程",
    "concept": "概念理解",
    "formula": "公式选择",
    "calculation": "计算稳定性",
    "basic_operation": "基础运算",
    "process": "过程完整性",
    "multi_step": "多步推理",
    "careful_check": "检查习惯",
}


def question_training_tags(question: dict) -> tuple[str, ...]:
    """Return explicit tags first, then fall back to the design family."""
    params = dict(question.get("params") or {})
    explicit = params.get("training_tags")
    if isinstance(explicit, (list, tuple)) and explicit:
        return tuple(str(tag) for tag in explicit)
    design_id = str(params.get("design_id") or "")
    if design_id in DESIGN_TAGS:
        return DESIGN_TAGS[design_id]
    return QUESTION_TYPE_TAGS.get(str(params.get("question_type") or ""), ())


def build_training_focus(
    error_type: str | None,
    design_id: str | None = None,
) -> dict | None:
    """Convert one attribution into a coarse next-question focus."""
    normalized = str(error_type or "").strip()
    tags = ERROR_TYPE_TAGS.get(normalized, ())
    if not tags:
        return None
    return {
        "error_type": normalized,
        "source_design_id": str(design_id or ""),
        "tags": list(tags),
        "provisional": True,
    }


def build_teaching_plan(focus: dict | None) -> dict | None:
    """Build the minimal teacher-reviewable plan from a training focus."""
    if not focus or not focus.get("tags"):
        return None
    tags = [str(tag) for tag in focus["tags"]]
    target_skill = "、".join(TAG_LABELS.get(tag, tag) for tag in tags)
    scaffold_strategy = (
        "先独立作答；若连续错误，再提供概念提示，最后才给步骤提示。"
    )
    return {
        "target_skill": target_skill,
        "weak_reasons": [str(focus.get("error_type") or "未归因")],
        "recommended_tags": tags,
        "recommended_question_count": 2,
        "scaffold_strategy": scaffold_strategy,
        "needs_verification": True,
        "confidence": 0.6,
        "teacher_review_status": "pending",
        "teacher_note": None,
    }


def rank_questions_for_focus(
    questions: Iterable[dict],
    focus: dict | None,
) -> list[dict]:
    """Stable rank: matching training tags first, original order second."""
    items = list(questions)
    if not focus or not focus.get("tags"):
        return items
    wanted = set(str(tag) for tag in focus["tags"])
    source_design = str(focus.get("source_design_id") or "")

    def score(question: dict) -> tuple[int, int]:
        tags = set(question_training_tags(question))
        match_count = len(tags & wanted)
        question_design = str(
            (question.get("params") or {}).get("design_id") or ""
        )
        same_design = int(bool(source_design) and question_design == source_design)
        return match_count, same_design

    return [
        item
        for _, item in sorted(
            enumerate(items),
            key=lambda pair: (-score(pair[1])[0], -score(pair[1])[1], pair[0]),
        )
    ]
