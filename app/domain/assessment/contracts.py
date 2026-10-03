"""Contracts for pluggable assessment question handlers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class ResponseSpec:
    """One student-answer response expected by a subquestion."""

    id: str
    kind: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SubquestionSpec:
    """One independently presented and graded part of a question."""

    id: str
    prompt: str
    response: ResponseSpec


@dataclass(frozen=True)
class SubmissionPart:
    """One submitted response keyed to its subquestion/response id."""

    id: str
    value: Any


@dataclass(frozen=True)
class Submission:
    """A complete structured submission for one question."""

    parts: tuple[SubmissionPart, ...] = ()


@dataclass(frozen=True)
class EvaluationPart:
    """One independently verifiable part of a submission."""

    id: str
    status: str
    earned: float = 0.0
    total: float = 1.0
    feedback: str = ""
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Evaluation:
    """Structured program evaluation before human confirmation."""

    parts: tuple[EvaluationPart, ...] = ()
    invalid: bool = False
    feedback: str = ""

    @property
    def earned(self) -> float:
        return sum(part.earned for part in self.parts)

    @property
    def total(self) -> float:
        return sum(part.total for part in self.parts)

    @property
    def correct(self) -> bool:
        return (
            not self.invalid
            and bool(self.parts)
            and all(part.status == "correct" for part in self.parts)
        )


class QuestionHandler(Protocol):
    """A question family plugin used by materialization, UI and grading."""

    kind: str

    def supports(self, params: dict | None) -> bool:
        ...

    def materialize(
        self,
        question: dict,
        *,
        regenerate_analysis: bool = False,
    ) -> dict:
        ...

    def supports_template(self, params: dict | None) -> bool:
        ...

    def build_template(self, params: dict) -> dict:
        ...

    def check_answer(self, question: dict, student_answer: str) -> bool:
        ...

    def question_roots(self, question: dict) -> list[float]:
        ...
