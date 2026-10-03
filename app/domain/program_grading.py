"""Deterministic grading facts computed without any LLM involvement."""

from __future__ import annotations

from app.domain.answer_template import breakpoint_label, judge_blanks
from app.domain.assessment import get_question_handler
from app.domain.assessment.subquestions import (
    build_subquestion_results,
    combine_subquestion_results,
)
from app.domain.grading import check_is_correct, question_roots


def compute_program_grade(
    question: dict,
    student_steps: list,
    template: dict | None = None,
) -> dict:
    """Return authoritative answer/process facts for one question."""
    student_final = (
        str(student_steps[-1].get("result") or "").strip()
        if student_steps
        else ""
    )
    handler = get_question_handler(question.get("params"))
    if handler is not None:
        final_answer_correct = handler.check_answer(question, student_final)
    else:
        final_answer_correct = check_is_correct(
            student_final,
            question_roots(question),
        )

    result = {
        "question_id": question["id"],
        "kp_id": question["kp_id"],
        "is_correct": final_answer_correct,
        "final_answer_correct": final_answer_correct,
        "process_correct": True,
        "steps": student_steps,
    }
    if template:
        blank_results = judge_blanks(template, student_steps)
        result["blank_results"] = blank_results
        result["subquestion_results"] = build_subquestion_results(
            template,
            blank_results,
        )
        breakpoint = breakpoint_label(blank_results)
        result["process_correct"] = breakpoint is None
        if breakpoint:
            result["is_correct"] = False
            result["program_breakpoint"] = f"程序定位断点：{breakpoint}"
        if template.get("final_answer_builder") == "growth_equation":
            result["final_answer_correct"] = result["process_correct"]
            result["is_correct"] = result["process_correct"]
        if template.get("final_answer_builder") == "subquestions":
            final_answer_correct = combine_subquestion_results(
                result.get("subquestion_results") or []
            )
            result["final_answer_correct"] = final_answer_correct
            result["is_correct"] = (
                final_answer_correct and result["process_correct"]
            )
    return result
