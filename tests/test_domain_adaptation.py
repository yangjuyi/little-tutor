"""会话内自适应与证据权重测试。"""

import unittest

from app.domain.adaptation import (
    evidence_weighted_rate,
    order_questions_for_target,
    select_next_target,
)


class TestAdaptivePolicy(unittest.TestCase):
    def _result(
        self,
        difficulty: str,
        correct: bool,
        assistance: str = "independent",
    ) -> dict:
        return {
            "difficulty": difficulty,
            "is_correct": correct,
            "assistance_level": assistance,
        }

    def test_weighted_rate_penalizes_assistance(self):
        self.assertEqual(
            evidence_weighted_rate([
                self._result("mid", True, "independent"),
            ]),
            1.0,
        )
        self.assertEqual(
            evidence_weighted_rate([
                self._result("mid", True, "hinted"),
            ]),
            0.5,
        )
        self.assertEqual(
            evidence_weighted_rate([
                self._result("mid", True, "scaffolded"),
            ]),
            0.25,
        )
        self.assertEqual(
            evidence_weighted_rate([
                self._result("mid", True, "independent"),
                self._result("mid", False, "independent"),
            ]),
            0.5,
        )

    def test_two_independent_successes_promote_difficulty(self):
        results = [
            self._result("simple", True),
            self._result("mid", True),
        ]
        self.assertEqual(select_next_target("mid", results), "hard")

    def test_hinted_success_does_not_promote(self):
        results = [
            self._result("mid", True),
            self._result("mid", True, "hinted"),
        ]
        self.assertEqual(select_next_target("mid", results), "mid")

    def test_failure_demotes_one_level(self):
        self.assertEqual(
            select_next_target(
                "hard",
                [self._result("hard", False)],
            ),
            "mid",
        )
        self.assertEqual(
            select_next_target(
                "simple",
                [self._result("simple", False)],
            ),
            "simple",
        )

    def test_remaining_questions_order_toward_target(self):
        questions = [
            {"stem": "simple", "difficulty": "simple"},
            {"stem": "hard", "difficulty": "hard"},
            {"stem": "mid", "difficulty": "mid"},
        ]
        ordered = order_questions_for_target(questions, "hard")
        self.assertEqual(
            [question["difficulty"] for question in ordered],
            ["hard", "mid", "simple"],
        )
        self.assertEqual(
            {question["stem"] for question in ordered},
            {"simple", "mid", "hard"},
        )


if __name__ == "__main__":
    unittest.main()
