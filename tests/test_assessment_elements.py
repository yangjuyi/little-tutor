"""Tests for reusable assessment response elements."""

from __future__ import annotations

import unittest

from app.domain.assessment.contracts import (
    Evaluation,
    EvaluationPart,
    ResponseSpec,
    Submission,
    SubmissionPart,
    SubquestionSpec,
)
from app.domain.assessment.elements import get_response_element, judge_block
from app.domain.assessment.subquestions import (
    build_subquestion_results,
    combine_subquestion_results,
)


class TestAssessmentElements(unittest.TestCase):
    def test_choice_accepts_letter_or_number(self):
        block = {
            "kind": "choice",
            "options": ["x", "y", "z", "w"],
            "answer_index": 1,
        }
        self.assertTrue(judge_block(block, "B"))
        self.assertTrue(judge_block(block, "2"))
        self.assertFalse(judge_block(block, "A"))

    def test_numeric_accepts_configured_equivalents(self):
        block = {
            "kind": "numeric",
            "expected": 0.25,
            "accepted": [0.25, 25],
        }
        self.assertTrue(judge_block(block, "0.25"))
        self.assertTrue(judge_block(block, "25%"))
        self.assertFalse(judge_block(block, "20%"))

    def test_symbolic_uses_equation_equivalence(self):
        block = {
            "kind": "symbolic",
            "expected": "1000(1+x)^2=1440",
        }
        self.assertTrue(judge_block(block, "1000*(1+x)**2 = 1440"))
        self.assertFalse(judge_block(block, "1000(1+x)=1440"))

    def test_unknown_response_element_fails_fast(self):
        with self.assertRaisesRegex(ValueError, "未注册"):
            judge_block({"kind": "proof"}, "anything")
        self.assertIsNone(get_response_element("proof"))

    def test_structured_contracts_are_independent(self):
        response = ResponseSpec(
            id="r1",
            kind="numeric",
            params={"expected": 10},
        )
        subquestion = SubquestionSpec(
            id="1",
            prompt="求增长率",
            response=response,
        )
        submission = Submission(parts=(SubmissionPart("1", "10%"),))
        evaluation = Evaluation(parts=(
            EvaluationPart(id="1", status="correct", earned=1, total=1),
        ))
        self.assertEqual(subquestion.response.kind, "numeric")
        self.assertEqual(submission.parts[0].value, "10%")
        self.assertTrue(evaluation.correct)

    def test_subquestion_results_group_parts_and_combine(self):
        template = {
            "subquestions": [
                {"id": "1", "prompt": "求增长率", "answer_blank_ids": ["b1"]},
                {"id": "2", "prompt": "求下期金额", "answer_blank_ids": ["b2"]},
            ],
        }
        results = build_subquestion_results(template, [
            {"blank_id": "b1", "is_correct": True},
            {"blank_id": "b2", "is_correct": False},
        ])
        self.assertEqual(len(results), 2)
        self.assertFalse(combine_subquestion_results(results))
        results[1]["effective_is_correct"] = True
        self.assertTrue(combine_subquestion_results(results))


if __name__ == "__main__":
    unittest.main()
