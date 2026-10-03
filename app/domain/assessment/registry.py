"""Question-handler registry used by the generic assessment pipeline."""

from __future__ import annotations

from app.domain.assessment.contracts import QuestionHandler


_HANDLERS: list[QuestionHandler] = []


def register_question_handler(handler: QuestionHandler) -> None:
    if any(existing.kind == handler.kind for existing in _HANDLERS):
        raise ValueError(f"题型 handler 已注册：{handler.kind}")
    _HANDLERS.append(handler)


def get_question_handler(params: dict | None) -> QuestionHandler | None:
    for handler in _HANDLERS:
        if handler.supports(params):
            return handler
    return None
