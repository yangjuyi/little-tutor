"""练习会话生命周期持久化测试。"""

import os
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.adapters.session_store as session_store
import app.adapters.persistence as db
import app.application.student_practice as student_practice


class TestSessionStore(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        self.db_path = tmp.name
        self.engine = create_engine(
            f"sqlite:///{self.db_path}",
            connect_args={"check_same_thread": False},
        )
        db.Base.metadata.create_all(self.engine)
        Session = sessionmaker(
            bind=self.engine, autoflush=False, expire_on_commit=False
        )
        self.session = Session
        self.patch = patch.object(session_store, "SessionLocal", Session)
        self.patch.start()

        with Session() as s:
            student = db.Student(name="测试学生")
            kp = db.KnowledgePoint(
                subject="数学",
                chapter="一元二次方程",
                kp_name="配方法解一元二次方程",
                concept="c",
            )
            s.add_all([student, kp])
            s.flush()
            question = db.Question(
                kp_id=kp.id,
                stem="x² - 5x + 6 = 0",
                answer="x₁=2, x₂=3",
                source="ai_generated",
            )
            s.add(question)
            s.commit()
            self.student_id = student.id
            self.kp_id = kp.id
            self.question_id = question.id

    def tearDown(self):
        self.patch.stop()
        self.engine.dispose()
        os.unlink(self.db_path)

    def test_lifecycle_controls_mastery_eligibility(self):
        session_store.start_practice_session(
            "S20260912-001", self.student_id, self.kp_id
        )
        self.assertEqual(
            session_store.eligible_session_ids(self.student_id, self.kp_id),
            set(),
        )

        session_store.complete_practice_session("S20260912-001")
        self.assertEqual(
            session_store.eligible_session_ids(self.student_id, self.kp_id),
            set(),
        )

        session_store.review_practice_session(
            "S20260912-001", "accepted"
        )
        self.assertEqual(
            session_store.eligible_session_ids(self.student_id, self.kp_id),
            {"S20260912-001"},
        )

    def test_rejected_aborted_and_test_sessions_are_ineligible(self):
        cases = (
            ("pending", "completed", "pending", "real"),
            ("rejected", "completed", "rejected", "real"),
            ("test-data", "completed", "accepted", "test"),
            ("aborted", "aborted", "pending", "real"),
        )
        with self.session() as s:
            for session_id, status, review_status, data_source in cases:
                s.add(db.PracticeSessionRecord(
                    session_id=session_id,
                    student_id=self.student_id,
                    kp_id=self.kp_id,
                    status=status,
                    review_status=review_status,
                    data_source=data_source,
                ))
            s.commit()

        self.assertEqual(
            session_store.eligible_session_ids(self.student_id, self.kp_id),
            set(),
        )

    def test_mark_session_test_excludes_mastery_evidence(self):
        session_store.start_practice_session(
            "S20260912-004", self.student_id, self.kp_id
        )
        session_store.complete_practice_session("S20260912-004")
        session_store.review_practice_session(
            "S20260912-004", "accepted"
        )
        self.assertEqual(
            session_store.eligible_session_ids(self.student_id, self.kp_id),
            {"S20260912-004"},
        )

        session_store.mark_practice_session_test("S20260912-004")
        self.assertEqual(
            session_store.eligible_session_ids(self.student_id, self.kp_id),
            set(),
        )
        session_store.mark_practice_session_test("S20260912-004")
        with self.session() as s:
            row = s.get(db.PracticeSessionRecord, "S20260912-004")
            self.assertEqual(row.data_source, "test")
            self.assertEqual(row.review_status, "accepted")

    def test_lifecycle_operations_are_idempotent(self):
        session_store.start_practice_session(
            "S20260912-002", self.student_id, self.kp_id
        )
        session_store.start_practice_session(
            "S20260912-002", self.student_id, self.kp_id
        )
        session_store.complete_practice_session("S20260912-002")
        session_store.complete_practice_session("S20260912-002")
        session_store.review_practice_session(
            "S20260912-002", "accepted"
        )
        session_store.review_practice_session(
            "S20260912-002", "accepted"
        )

        with self.session() as s:
            rows = s.query(db.PracticeSessionRecord).all()
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0].status, "completed")
            self.assertEqual(rows[0].review_status, "accepted")

    def test_session_lease_blocks_other_worker_and_expires(self):
        session_store.start_practice_session(
            "S20260912-003", self.student_id, self.kp_id
        )
        self.assertTrue(
            session_store.acquire_practice_lease(
                "S20260912-003", owner="worker-a"
            )
        )
        self.assertFalse(
            session_store.acquire_practice_lease(
                "S20260912-003", owner="worker-b"
            )
        )

        with self.session() as s:
            row = s.get(db.PracticeSessionRecord, "S20260912-003")
            row.lease_expires_at = datetime.now() - timedelta(seconds=1)
            s.commit()

        self.assertTrue(
            session_store.acquire_practice_lease(
                "S20260912-003", owner="worker-b"
            )
        )
        session_store.release_practice_lease(
            "S20260912-003", owner="worker-b"
        )

    def test_concurrent_lease_acquisition_is_exclusive(self):
        session_store.start_practice_session(
            "S20260912-004", self.student_id, self.kp_id
        )

        def acquire(owner):
            return session_store.acquire_practice_lease(
                "S20260912-004", owner=owner
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(acquire, ("worker-a", "worker-b")))
        self.assertEqual(sorted(results), [False, True])

    def test_renew_practice_lease_extends_expiry_only_for_owner(self):
        session_store.start_practice_session(
            "S20260912-005", self.student_id, self.kp_id
        )
        self.assertTrue(
            session_store.acquire_practice_lease(
                "S20260912-005",
                owner="worker-a",
                ttl_seconds=30,
            )
        )
        with self.session() as s:
            before = s.get(
                db.PracticeSessionRecord, "S20260912-005"
            ).lease_expires_at

        self.assertFalse(
            session_store.renew_practice_lease(
                "S20260912-005",
                owner="worker-b",
                ttl_seconds=120,
            )
        )
        self.assertTrue(
            session_store.renew_practice_lease(
                "S20260912-005",
                owner="worker-a",
                ttl_seconds=120,
            )
        )
        with self.session() as s:
            after = s.get(
                db.PracticeSessionRecord, "S20260912-005"
            ).lease_expires_at
        self.assertGreater(after, before)

    def test_session_guard_renews_lease_during_long_operation(self):
        session_store.start_practice_session(
            "S20260912-006", self.student_id, self.kp_id
        )
        with patch.dict(
            os.environ,
            {"TUTOR_LEASE_TTL_SECONDS": "1"},
            clear=False,
        ):
            with student_practice._session_guard("S20260912-006"):
                time.sleep(1.3)
                with self.session() as s:
                    row = s.get(
                        db.PracticeSessionRecord,
                        "S20260912-006",
                    )
                    self.assertGreater(row.lease_expires_at, datetime.now())

    def test_backfill_legacy_session_uses_recorded_decision(self):
        with self.session() as s:
            s.add(db.AnswerRecord(
                student_id=self.student_id,
                question_id=self.question_id,
                answer="x1=2, x2=3",
                is_correct=True,
                session_id="legacy-real",
            ))
            s.add(db.TeacherDecision(
                student_id=self.student_id,
                kp_id=self.kp_id,
                session_id="legacy-real",
                decision="accept",
                proposal={},
            ))
            s.commit()

        self.assertTrue(
            session_store.backfill_legacy_session("legacy-real")
        )
        self.assertEqual(
            session_store.eligible_session_ids(self.student_id, self.kp_id),
            {"legacy-real"},
        )


if __name__ == "__main__":
    unittest.main()
