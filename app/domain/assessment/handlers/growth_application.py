"""Multi-part growth application handler."""

from __future__ import annotations

from fractions import Fraction
from typing import Any

from app.domain.assessment.handlers.growth_rate import (
    GrowthRateHandler,
    _choice,
)
from app.domain.exam.answer_equiv import numeric_equivalent
from app.domain.exam.solvers import solve_growth_rate
from app.domain.exam.specs import GrowthRateSpec


def _format_number(value: float) -> str:
    return format(value, ".15g")


def _solve_part(
    part: dict,
    solved: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    part_type = part["type"]
    if part_type == "growth_rate":
        spec = GrowthRateSpec(
            initial=part["initial"],
            final=part["final"],
            periods=part["periods"],
            mode=part.get("mode", "growth"),
            target=part.get("target", "rate"),
        )
        solution = solve_growth_rate(spec)
        return {
            "id": str(part["id"]),
            "type": part_type,
            "prompt": str(part["prompt"]),
            "answer": str(solution["answer"]),
            "rate": str(solution["rate"]),
            "equation": str(solution["equation"]),
            "spec": part,
        }
    if part_type == "next_value":
        rate_part = solved[str(part["rate_part"])]
        rate = Fraction(str(rate_part["rate"]))
        value = float(Fraction(str(part["base"])) * (1 + rate))
        return {
            "id": str(part["id"]),
            "type": part_type,
            "prompt": str(part["prompt"]),
            "answer": _format_number(value),
            "spec": part,
        }
    if part_type == "max_integer_after_growth":
        rate_part = solved[str(part["rate_part"])]
        rate = Fraction(str(rate_part["rate"]))
        available = Fraction(str(part["base"])) * (1 + rate)
        unit_cost = Fraction(str(part["unit_cost"]))
        value = int(available / unit_cost)
        return {
            "id": str(part["id"]),
            "type": part_type,
            "prompt": str(part["prompt"]),
            "answer": str(value),
            "spec": part,
        }
    raise ValueError(f"未知增长率应用子问题类型：{part_type}")


def solve_growth_application(params: dict) -> list[dict[str, Any]]:
    solved: dict[str, dict[str, Any]] = {}
    results: list[dict[str, Any]] = []
    for part in params.get("parts") or []:
        result = _solve_part(part, solved)
        solved[result["id"]] = result
        results.append(result)
    return results


class GrowthApplicationHandler:
    kind = "growth_application"

    def supports(self, params: dict | None) -> bool:
        payload = dict(params or {})
        return (
            payload.get("question_type") == self.kind
            and bool(payload.get("parts"))
        )

    def materialize(
        self,
        question: dict,
        *,
        regenerate_analysis: bool = False,
    ) -> dict:
        params = dict(question.get("params") or {})
        parts = solve_growth_application(params)
        answer = "；".join(
            f"({part['id']}) {part['answer']}"
            for part in parts
        )
        materialized = dict(question)
        materialized.update({
            "stem": str(question.get("stem") or "").strip(),
            "answer": answer,
            "params": params,
        })
        if regenerate_analysis or not materialized.get("analysis"):
            materialized["analysis"] = (
                "各子问题由程序按增长率模型和后续数量关系独立计算。"
            )
        return materialized

    def supports_template(self, params: dict | None) -> bool:
        return self.supports(params)

    def build_template(self, params: dict) -> dict:
        parts = solve_growth_application(params)
        blanks: list[dict] = []
        subquestions: list[dict] = []
        for part in parts:
            prefix = f"p{part['id']}_"
            part_blocks, final_blank_id = self._part_blocks(
                part,
                prefix,
            )
            blanks.extend(part_blocks)
            subquestions.append({
                "id": part["id"],
                "prompt": part["prompt"],
                "blank_ids": [block["id"] for block in part_blocks],
                "answer_blank_ids": [final_blank_id],
                "final_blank_id": final_blank_id,
                "expected_answer": part["answer"],
            })
        return {
            "blanks": blanks,
            "subquestions": subquestions,
            "answer_blank_ids": [
                item["final_blank_id"] for item in subquestions
            ],
            "final_answer_builder": "subquestions",
            "computed_final_answer": "；".join(
                f"({item['id']}) {item['expected_answer']}"
                for item in subquestions
            ),
        }

    @staticmethod
    def _part_blocks(
        part: dict[str, Any],
        prefix: str,
    ) -> tuple[list[dict], str]:
        if part["type"] == "growth_rate":
            spec = dict(part["spec"])
            initial = float(spec["initial"])
            final = float(spec["final"])
            periods = int(spec["periods"])
            mode = str(spec.get("mode") or "growth")
            operator = "+" if mode == "growth" else "-"
            wrong_operator = "-" if operator == "+" else "+"
            seed = sum(ord(char) for char in part["id"])
            blocks = [
                {
                    "id": prefix + "b1",
                    "kind": "expression",
                    "basis": "题目中的初始量是多少？",
                    "expected": initial,
                },
                {
                    "id": prefix + "b2",
                    "kind": "expression",
                    "basis": "连续变化了几次？",
                    "expected": periods,
                },
                {
                    "id": prefix + "b3",
                    **_choice(
                        "连续变化应使用哪种关系？",
                        [
                            f"(1{operator}x)^{periods}",
                            f"(1{wrong_operator}x)^{periods}",
                            f"(1{operator}{periods}x)",
                        ],
                        0,
                        seed,
                    ),
                },
                {
                    "id": prefix + "b4",
                    "kind": "expression",
                    "basis": "题目中的最终量是多少？",
                    "expected": final,
                },
            ]
            rate = Fraction(str(part["rate"]))
            blocks.append({
                "id": prefix + "b5",
                "kind": "expression",
                "basis": "符合实际意义的变化率是多少？",
                "expected": float(rate),
                "accepted": [float(rate), float(rate * 100)],
            })
            return blocks, prefix + "b5"

        block = {
            "id": prefix + "b1",
            "kind": "expression",
            "basis": f"第({part['id']})问的结果是多少？",
            "expected": float(part["answer"]),
        }
        return [block], block["id"]

    def check_answer(self, question: dict, student_answer: str) -> bool:
        parts = solve_growth_application(dict(question.get("params") or {}))
        segments: dict[str, str] = {}
        for segment in str(student_answer or "").split(";"):
            if "=" not in segment:
                continue
            key, value = segment.split("=", 1)
            segments[key.strip()] = value.strip()
        if len(segments) != len(parts):
            return False
        return all(
            numeric_equivalent(
                segments.get(part["id"], ""),
                part["answer"],
            )
            for part in parts
        )

    def question_roots(self, question: dict) -> list[float]:
        return []
