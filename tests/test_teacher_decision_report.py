"""Tests for the read-only teacher decision summary."""

import unittest
from datetime import datetime

from evals.report_teacher_decisions import summarize_teacher_decisions


class TestTeacherDecisionReport(unittest.TestCase):
    def test_empty_report_does_not_invent_rates(self):
        report = summarize_teacher_decisions([], [])
        self.assertEqual(report["totals"]["decisions"], 0)
        self.assertIsNone(report["attribution"]["correction_rate"])
        self.assertIsNone(report["result_review"]["override_rate"])
        self.assertIsNone(report["decision_delay"]["stats"])

    def test_counts_corrections_overrides_and_delay(self):
        decisions = [
            {
                "decision": "accept",
                "session_id": "s1",
                "question_id": None,
                "proposal": {"reason": "会话正确率汇总"},
                "created_at": datetime(2026, 10, 1, 10, 0, 10),
            },
            {
                "decision": "edit",
                "session_id": "s1",
                "question_id": 7,
                "proposal": {"reason": "teacher_error_type_correction"},
                "created_at": datetime(2026, 10, 1, 10, 0, 20),
            },
            {
                "decision": "override",
                "session_id": "s2",
                "question_id": 8,
                "proposal": {"reason": "teacher_result_override"},
                "created_at": datetime(2026, 10, 1, 10, 1, 0),
            },
        ]
        answers = [
            {
                "session_id": "s1",
                "question_id": 7,
                "created_at": datetime(2026, 10, 1, 10, 0, 0),
            },
            {
                "session_id": "s2",
                "question_id": 8,
                "created_at": datetime(2026, 10, 1, 10, 0, 30),
            },
        ]
        report = summarize_teacher_decisions(decisions, answers)
        self.assertEqual(report["totals"]["decision_counts"]["edit"], 1)
        self.assertEqual(
            report["attribution"]["error_type_correction_count"],
            1,
        )
        self.assertEqual(report["result_review"]["teacher_override_count"], 1)
        self.assertEqual(report["decision_delay"]["resolved_decisions"], 3)
        self.assertEqual(
            report["decision_delay"]["stats"]["average_seconds"],
            20.0,
        )
        self.assertIn("不能计算", report["attribution"]["rate_reason"])


if __name__ == "__main__":
    unittest.main()
