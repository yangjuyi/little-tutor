"""Discriminant and real-root-count choice handler."""

from __future__ import annotations

from app.domain.exam.main_chain import (
    check_structured_exam_answer,
    materialize_structured_exam,
    solve_question_spec,
)


class DiscriminantChoiceHandler:
    kind = "discriminant_choice"

    def supports(self, params: dict | None) -> bool:
        payload = dict(params or {})
        return (
            payload.get("question_type") == self.kind
            and bool(payload.get("exam_spec"))
        )

    def materialize(
        self,
        question: dict,
        *,
        regenerate_analysis: bool = False,
    ) -> dict:
        materialized = materialize_structured_exam(question)
        if regenerate_analysis:
            materialized["analysis"] = ""
            materialized = materialize_structured_exam(materialized)
        return materialized

    def supports_template(self, params: dict | None) -> bool:
        payload = dict(params or {})
        return (
            payload.get("response_type") == "multiple_choice"
            or payload.get("presentation") == "stepwise"
        )

    def build_template(self, params: dict) -> dict:
        spec = dict(params.get("exam_spec") or {})
        choices = dict(spec.get("choices") or {})
        labels = [
            label
            for label in ("A", "B", "C", "D")
            if label in choices
        ]
        if len(labels) < 2:
            raise ValueError("判别式选择题至少需要两个选项")
        solution = solve_question_spec({"params": dict(params)})
        matched = list(solution.get("answer") or [])
        if len(matched) != 1 or matched[0] not in labels:
            raise ValueError("判别式选择题必须只有一个正确选项")
        correct_label = str(matched[0])
        options = [str(choices[label]) for label in labels]
        return {
            "blanks": [{
                "id": "b1",
                "kind": "choice",
                "basis": "选择正确的方程或根的情况",
                "options": options,
                "answer_index": labels.index(correct_label),
                "option_labels": labels,
            }],
            "answer_blank_ids": ["b1"],
            "final_answer_builder": "choice_text",
            "computed_final_answer": str(choices[correct_label]),
        }

    def check_answer(self, question: dict, student_answer: str) -> bool:
        return check_structured_exam_answer(question, student_answer)

    def question_roots(self, question: dict) -> list[float]:
        return []
