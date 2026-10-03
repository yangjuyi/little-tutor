"""Reusable response elements and their program judges."""

from __future__ import annotations

from typing import Protocol

from app.domain.exam.answer_equiv import equation_equivalent


class ResponseElement(Protocol):
    kinds: tuple[str, ...]

    def judge(self, block: dict, student_result: str) -> bool:
        ...


class ChoiceElement:
    kinds = ("choice",)

    def judge(self, block: dict, student_result: str) -> bool:
        text = str(student_result or "").strip().upper()
        letters = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
        answer_index = int(block["answer_index"])
        accepted = {str(answer_index + 1), letters[answer_index]}
        return text in accepted


class NumericElement:
    kinds = ("expression", "numeric")

    def judge(self, block: dict, student_result: str) -> bool:
        from app.domain.grading import extract_numbers

        accepted = block.get("accepted") or [block["expected"]]
        tolerance = float(block.get("tolerance", 0.01))
        return any(
            abs(value - float(expected)) < tolerance
            for value in extract_numbers(str(student_result or ""))
            for expected in accepted
        )


class SymbolicElement:
    kinds = ("symbolic", "equation")

    def judge(self, block: dict, student_result: str) -> bool:
        return equation_equivalent(
            str(student_result or ""),
            str(block["expected"]),
        )


_ELEMENTS: tuple[ResponseElement, ...] = (
    ChoiceElement(),
    NumericElement(),
    SymbolicElement(),
)


def get_response_element(kind: str) -> ResponseElement | None:
    for element in _ELEMENTS:
        if kind in element.kinds:
            return element
    return None


def judge_block(block: dict, student_result: str) -> bool:
    element = get_response_element(str(block.get("kind") or ""))
    if element is None:
        raise ValueError(f"未注册的作答元素：{block.get('kind')}")
    return element.judge(block, student_result)
