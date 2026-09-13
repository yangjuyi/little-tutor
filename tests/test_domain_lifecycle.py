"""领域层会话生命周期与证据契约测试。"""

import unittest

from app.domain import (
    AnswerEvidence,
    PracticeSession,
    abandon_session,
    complete_session,
    is_mastery_evidence,
    review_session,
)


class TestPracticeSessionLifecycle(unittest.TestCase):
    def setUp(self):
        self.session = PracticeSession(
            session_id="S20260912-001",
            student_id=1,
            kp_id=2,
        )

    def test_only_completed_accepted_real_session_is_mastery_evidence(self):
        self.assertFalse(self.session.allows_mastery_evidence())

        completed = complete_session(self.session)
        self.assertFalse(completed.allows_mastery_evidence())

        accepted = review_session(completed, "accepted")
        self.assertTrue(accepted.allows_mastery_evidence())

    def test_rejected_and_test_sessions_never_enter_mastery(self):
        rejected = review_session(complete_session(self.session), "rejected")
        self.assertFalse(rejected.allows_mastery_evidence())

        test_session = PracticeSession(
            session_id="test-1",
            student_id=1,
            kp_id=2,
            status="completed",
            review_status="accepted",
            data_source="test",
        )
        self.assertFalse(test_session.allows_mastery_evidence())

    def test_aborted_session_cannot_enter_mastery(self):
        aborted = abandon_session(self.session)
        self.assertEqual(aborted.status, "aborted")
        self.assertFalse(aborted.allows_mastery_evidence())

    def test_session_transitions_are_one_way(self):
        completed = complete_session(self.session)
        with self.assertRaises(ValueError):
            complete_session(completed)
        with self.assertRaises(ValueError):
            abandon_session(completed)

        accepted = review_session(completed, "accepted")
        with self.assertRaises(ValueError):
            review_session(accepted, "rejected")

        with self.assertRaises(ValueError):
            review_session(self.session, "accepted")


class TestAnswerEvidence(unittest.TestCase):
    def setUp(self):
        self.session = review_session(
            complete_session(
                PracticeSession(
                    session_id="S20260912-002",
                    student_id=1,
                    kp_id=2,
                )
            ),
            "accepted",
        )

    def test_evidence_kind_tracks_assistance_level(self):
        independent = AnswerEvidence(
            question_id=1, attempt_no=1, is_correct=True, source="program"
        )
        hinted = AnswerEvidence(
            question_id=1, attempt_no=1, is_correct=True, source="program",
            hints_used=1,
        )
        scaffolded = AnswerEvidence(
            question_id=1, attempt_no=1, is_correct=True, source="program",
            scaffold_level=2,
        )

        self.assertEqual(independent.kind, "independent")
        self.assertTrue(independent.is_independent)
        self.assertEqual(hinted.kind, "hinted")
        self.assertFalse(hinted.is_independent)
        self.assertEqual(scaffolded.kind, "scaffolded")
        self.assertFalse(scaffolded.is_independent)

    def test_llm_attribution_cannot_drive_mastery(self):
        llm_evidence = AnswerEvidence(
            question_id=1, attempt_no=1, is_correct=False, source="llm"
        )
        program_evidence = AnswerEvidence(
            question_id=1, attempt_no=1, is_correct=False, source="program"
        )

        self.assertFalse(is_mastery_evidence(self.session, llm_evidence))
        self.assertTrue(is_mastery_evidence(self.session, program_evidence))

    def test_invalid_evidence_is_rejected(self):
        with self.assertRaises(ValueError):
            AnswerEvidence(
                question_id=1, attempt_no=0, is_correct=True, source="program"
            )
        with self.assertRaises(ValueError):
            AnswerEvidence(
                question_id=1, attempt_no=1, is_correct=True, source="program",
                hints_used=-1,
            )
        with self.assertRaises(ValueError):
            AnswerEvidence(
                question_id=1, attempt_no=1, is_correct=True, source="program",
                scaffold_level=-1,
            )


if __name__ == "__main__":
    unittest.main()
