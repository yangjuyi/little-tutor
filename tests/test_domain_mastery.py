"""掌握度纯领域规则测试。"""

import unittest

from app.domain.mastery import propose_from_rates


class TestMasteryRules(unittest.TestCase):
    def test_no_evidence_is_weak(self):
        proposal = propose_from_rates([])
        self.assertEqual(proposal["suggest_level"], "weak")
        self.assertEqual(proposal["confidence"], 0.0)
        self.assertEqual(proposal["sessions"], 0)

    def test_single_session_uses_mid_threshold(self):
        self.assertEqual(
            propose_from_rates([0.6])["suggest_level"],
            "mid",
        )
        self.assertEqual(
            propose_from_rates([0.59])["suggest_level"],
            "weak",
        )

    def test_strong_requires_two_strong_sessions(self):
        self.assertEqual(
            propose_from_rates([0.9, 0.8])["suggest_level"],
            "strong",
        )
        self.assertEqual(
            propose_from_rates([0.9, 0.79])["suggest_level"],
            "mid",
        )

    def test_latest_session_drives_confidence_and_ordering(self):
        proposal = propose_from_rates([0.75, 1.0])
        self.assertEqual(proposal["suggest_level"], "mid")
        self.assertEqual(proposal["confidence"], 0.75)
        self.assertIn("100%→75%", proposal["evidence"])


if __name__ == "__main__":
    unittest.main()
