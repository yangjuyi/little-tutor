"""过程诊断垂直切片测试：一元方程相邻步骤转换。"""

import unittest

from app.domain.process_diagnosis import (
    diagnose_submission,
    diagnose_transitions,
    first_invalid_transition,
)


def _step(step_no: int, raw_latex: str) -> dict:
    return {
        "step_no": step_no,
        "raw_latex": raw_latex,
        "operation": "",
        "source": "typed",
        "confidence": 1.0,
    }


class TestProcessDiagnosis(unittest.TestCase):
    def test_equivalent_linear_transition_is_valid(self):
        checks = diagnose_transitions([
            _step(1, "2x + 3 = 7"),
            _step(2, "2x = 4"),
        ])
        self.assertEqual(len(checks), 1)
        self.assertTrue(checks[0]["is_valid"])
        self.assertEqual(checks[0]["rule"], "等价变形")
        self.assertFalse(checks[0]["insufficient_evidence"])

    def test_wrong_linear_transition_changes_root_set(self):
        checks = diagnose_transitions([
            _step(1, "2x + 3 = 7"),
            _step(2, "2x = 10"),
        ])
        self.assertFalse(checks[0]["is_valid"])
        self.assertEqual(checks[0]["error_type"], "计算")
        self.assertIn("原方程根=2", checks[0]["evidence"])
        self.assertIn("下一步根=5", checks[0]["evidence"])

    def test_missing_root_is_classified(self):
        checks = diagnose_transitions([
            _step(1, "x^2 - 5x + 6 = 0"),
            _step(2, "x = 2"),
        ])
        self.assertFalse(checks[0]["is_valid"])
        self.assertEqual(checks[0]["error_type"], "漏根")
        self.assertIn("原方程根=2, 3", checks[0]["evidence"])

    def test_direct_roots_mark_insufficient_evidence(self):
        checks = diagnose_transitions([
            _step(1, "x^2 - 5x + 6 = 0"),
            _step(2, "x = 2 or x = 3"),
        ])
        self.assertTrue(checks[0]["is_valid"])
        self.assertEqual(checks[0]["rule"], "直接给出根")
        self.assertTrue(checks[0]["insufficient_evidence"])

    def test_root_label_variants_are_supported(self):
        checks = diagnose_transitions([
            _step(1, "x^2 - 5x + 6 = 0"),
            _step(2, "x1 = 2, x2 = 3"),
        ])
        self.assertTrue(checks[0]["is_valid"])

    def test_unsupported_expression_does_not_fabricate_error(self):
        checks = diagnose_transitions([
            _step(1, "sin(x) = 0"),
            _step(2, "x = 0"),
        ])
        self.assertFalse(checks[0]["is_valid"])
        self.assertIsNone(checks[0]["error_type"])
        self.assertTrue(checks[0]["insufficient_evidence"])
        self.assertEqual(checks[0]["rule"], "无法判断")

    def test_first_invalid_transition_locates_breakpoint(self):
        checks = diagnose_transitions([
            _step(1, "2x + 3 = 7"),
            _step(2, "2x = 4"),
            _step(3, "x = 4"),
        ])
        breakpoint = first_invalid_transition(checks)
        self.assertIsNotNone(breakpoint)
        self.assertEqual(breakpoint["from_step"], 2)
        self.assertEqual(breakpoint["to_step"], 3)
        self.assertEqual(breakpoint["error_type"], "计算")

    def test_final_answer_only_has_no_transition_checks(self):
        checks = diagnose_submission({
            "mode": "final_answer_only",
            "steps": [],
            "final_answer": "x1=2, x2=3",
        })
        self.assertEqual(checks, [])


if __name__ == "__main__":
    unittest.main()
