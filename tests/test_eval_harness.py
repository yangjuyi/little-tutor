"""Offline tests for the evaluation harness."""

from __future__ import annotations

import unittest

from evals.harness import build_cases, program_only_grader, run_cases, summarize


class TestEvalHarness(unittest.TestCase):
    def test_public_cases_cover_expected_states(self):
        cases = build_cases()
        self.assertEqual(len(cases), 45)
        self.assertEqual(
            {case["tags"][-1] for case in cases},
            {"with_process", "final_only", "missing_root", "wrong_root", "no_steps"},
        )

    def test_private_cases_are_optional_and_separated(self):
        cases = build_cases(source="private", limit_questions=2)
        self.assertEqual(len(cases), 10)
        self.assertTrue(
            all(
                case["question"]["source"] == "private_drill"
                for case in cases
            )
        )

    def test_program_only_baseline_passes_contract_metrics(self):
        results = run_cases(build_cases(limit_questions=2), program_only_grader)
        summary = summarize(results)
        self.assertEqual(summary["total_cases"], 10)
        self.assertEqual(summary["program_accuracy"], 1.0)
        self.assertEqual(summary["correct_guard_pass_rate"], 1.0)
        self.assertEqual(summary["wrong_guard_pass_rate"], 1.0)
        self.assertEqual(summary["insufficient_evidence_rate"], 1.0)
        self.assertEqual(summary["no_evidence_over_attribution_rate"], 0.0)


if __name__ == "__main__":
    unittest.main()
