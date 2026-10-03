"""Assessment question-element registry."""

from app.domain.assessment.handlers.growth_rate import GrowthRateHandler
from app.domain.assessment.handlers.growth_application import (
    GrowthApplicationHandler,
)
from app.domain.assessment.handlers.discriminant_choice import (
    DiscriminantChoiceHandler,
)
from app.domain.assessment.registry import (
    get_question_handler,
    register_question_handler,
)


def register_builtin_handlers() -> None:
    register_question_handler(DiscriminantChoiceHandler())
    register_question_handler(GrowthRateHandler())
    register_question_handler(GrowthApplicationHandler())


register_builtin_handlers()

__all__ = [
    "get_question_handler",
    "register_question_handler",
]
