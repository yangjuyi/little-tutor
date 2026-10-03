"""Subquestion result aggregation from flat response blocks."""

from __future__ import annotations

from typing import Any


def build_subquestion_results(
    template: dict | None,
    blank_results: list[dict],
) -> list[dict[str, Any]]:
    """Group response-element results by declared subquestion."""
    if not template:
        return []
    subquestions = list(template.get("subquestions") or [])
    if not subquestions:
        return []
    by_id = {str(item["blank_id"]): item for item in blank_results}
    results: list[dict[str, Any]] = []
    for subquestion in subquestions:
        part_results = [
            by_id[blank_id]
            for blank_id in subquestion.get("answer_blank_ids") or []
            if blank_id in by_id
        ]
        is_correct = bool(part_results) and all(
            bool(item.get("is_correct")) for item in part_results
        )
        results.append({
            "id": str(subquestion["id"]),
            "prompt": str(subquestion.get("prompt") or ""),
            "is_correct": is_correct,
            "teacher_is_correct": None,
            "effective_is_correct": is_correct,
            "parts": part_results,
        })
    return results


def combine_subquestion_results(results: list[dict[str, Any]]) -> bool:
    """Question correctness derived from teacher-confirmed subquestions."""
    if not results:
        return False
    return all(
        bool(
            item.get(
                "effective_is_correct",
                item.get("is_correct"),
            )
        )
        for item in results
    )
