"""Growth-rate assessment handler."""

from __future__ import annotations

from fractions import Fraction

from app.domain.exam.answer_equiv import equation_equivalent, numeric_equivalent
from app.domain.exam.main_chain import (
    check_structured_exam_answer,
    materialize_structured_exam,
    solve_question_spec,
)


def _choice(
    basis: str,
    options: list[str],
    correct_index: int,
    seed: int,
) -> dict:
    correct_text = options[correct_index]
    offset = seed % len(options)
    ordered = options[offset:] + options[:offset]
    return {
        "kind": "choice",
        "basis": basis,
        "options": ordered,
        "answer_index": ordered.index(correct_text),
    }


class GrowthRateHandler:
    kind = "growth_rate"

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
        if params.get("response_type") == "multiple_choice":
            return self._multiple_choice_template(params)
        if params.get("presentation") == "stepwise":
            return self._stepwise_template(params)
        raise ValueError("真实考试模式不使用分步模板")

    def check_answer(self, question: dict, student_answer: str) -> bool:
        return check_structured_exam_answer(question, student_answer)

    def question_roots(self, question: dict) -> list[float]:
        from app.domain.grading import extract_numbers

        solution = solve_question_spec(question)
        params = dict(question.get("params") or {})
        target = (
            params.get("target")
            or (params.get("exam_spec") or {}).get("target")
            or "rate"
        )
        if target == "equation":
            return []
        return sorted(extract_numbers(str(solution["answer"])))

    @staticmethod
    def _multiple_choice_template(params: dict) -> dict:
        choices = [str(value) for value in params.get("choices") or []]
        correct_label = str(params.get("correct_choice") or "").strip().upper()
        if len(choices) != 4 or correct_label not in ("A", "B", "C", "D"):
            raise ValueError("选择题模板缺少合法的选项或正确项")
        return {
            "blanks": [{
                "id": "b1",
                "kind": "choice",
                "basis": "选择正确选项",
                "options": choices,
                "answer_index": "ABCD".index(correct_label),
                "option_labels": list("ABCD"),
            }],
            "answer_blank_ids": ["b1"],
            "final_answer_builder": "choice_text",
            "computed_final_answer": "",
        }

    @staticmethod
    def _stepwise_template(params: dict) -> dict:
        solution = solve_question_spec({"params": dict(params)})
        spec = dict(params.get("exam_spec") or {})
        target = str(params.get("target") or spec.get("target") or "rate")
        initial = float(spec["initial"])
        final = float(spec["final"])
        periods = int(spec["periods"])
        mode = str(spec.get("mode") or "growth")
        operator = "+" if mode == "growth" else "-"
        relation = f"(1{operator}x)^{periods}"
        wrong_operator = "-" if operator == "+" else "+"
        seed = sum(ord(char) for char in str(params.get("source_question_id") or ""))
        relation_choice = _choice(
            "连续变化应使用哪种关系？",
            [
                relation,
                f"(1{wrong_operator}x)^{periods}",
                f"(1{operator}{periods}x)",
            ],
            0,
            seed,
        )
        blanks = [
            {
                "id": "b1",
                "kind": "expression",
                "basis": "题目中的初始量是多少？",
                "expected": initial,
            },
            {
                "id": "b2",
                "kind": "expression",
                "basis": "从初始量到最终量连续变化了几次？",
                "expected": periods,
            },
            {"id": "b3", **relation_choice},
            {
                "id": "b4",
                "kind": "expression",
                "basis": "题目中的最终量是多少？",
                "expected": final,
            },
        ]
        builder = "growth_equation"
        answer_blank_ids: list[str] = []
        if target == "rate":
            rate_fraction = Fraction(str(solution["rate"]))
            rate_percent = float(rate_fraction * 100)
            rate_decimal = float(rate_fraction)
            blanks.append({
                "id": "b5",
                "kind": "expression",
                "basis": "符合实际意义的变化率 x 是多少？可填百分数或小数。",
                "expected": rate_decimal,
                "accepted": [rate_percent, rate_decimal],
            })
            builder = "growth_rate"
            answer_blank_ids = ["b5"]
        return {
            "blanks": blanks,
            "answer_blank_ids": answer_blank_ids,
            "final_answer_builder": builder,
            "computed_final_answer": str(solution["answer"]),
        }
