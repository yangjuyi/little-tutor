"""Availability checks for tests that depend on ignored private fixtures."""

from __future__ import annotations

from app.adapters.real_exam_bank import (
    DEFAULT_MULTIPART_SPECS,
    load_growth_main_chain_questions,
)
from evals.harness import PRIVATE_DRILLS_PATH


HAS_PRIVATE_DRILLS = PRIVATE_DRILLS_PATH.exists()
HAS_MULTIPART_SPECS = DEFAULT_MULTIPART_SPECS.exists()

_GROWTH_RECORDS = load_growth_main_chain_questions(0)
HAS_GROWTH_MAIN_CHAIN = any(
    record["params"].get("question_type") == "growth_rate"
    for record in _GROWTH_RECORDS
)
HAS_GROWTH_MULTIPLE_CHOICE = any(
    record["params"].get("question_type") == "growth_rate"
    and record["params"].get("response_type") == "multiple_choice"
    for record in _GROWTH_RECORDS
)
