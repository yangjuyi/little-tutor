"""教学领域契约。"""

from app.domain.evidence import (
    AnswerEvidence,
    EvidenceKind,
    EvidenceSource,
    is_mastery_evidence,
)
from app.domain.mastery import MID_RATE, STRONG_RATE, propose_from_rates
from app.domain.session import (
    DataSource,
    PracticeSession,
    ReviewStatus,
    SessionStatus,
    abandon_session,
    complete_session,
    review_session,
)

__all__ = [
    "AnswerEvidence",
    "DataSource",
    "EvidenceKind",
    "EvidenceSource",
    "MID_RATE",
    "PracticeSession",
    "ReviewStatus",
    "STRONG_RATE",
    "SessionStatus",
    "abandon_session",
    "complete_session",
    "is_mastery_evidence",
    "propose_from_rates",
    "review_session",
]
