"""落库行为测试：answer_records / teacher_decisions / mastery 3 级（离线，临时库）

Run with: .venv/Scripts/python -m unittest tests.test_persistence -v
"""

import os
import tempfile
import unittest
from unittest.mock import patch

from langgraph.types import Command
from langgraph.checkpoint.memory import InMemorySaver
from sqlalchemy import create_engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

import app.adapters.persistence as db
import app.adapters.review_store as review_store
import app.adapters.session_store as session_store
import app.application.profile_evidence as profile_evidence
from app.harness.legacy_graph import build_tutor_graph


class TestPersistence(unittest.TestCase):
    """真实临时库验证：事实落库 + 仲裁留痕 + mastery 只在 accept 时写"""

    def setUp(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        self.db_path = tmp.name
        engine = create_engine(
            f"sqlite:///{self.db_path}",
            connect_args={"check_same_thread": False},
        )
        self.engine = engine
        db.Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        self._patches = [
            patch.object(db, "SessionLocal", Session),
            patch.object(review_store, "SessionLocal", Session),
            patch.object(profile_evidence, "SessionLocal", Session),
            patch.object(session_store, "SessionLocal", Session),
        ]
        for p in self._patches:
            p.start()

        with Session() as s:
            stu = db.Student(name="测试学生")
            s.add(stu)
            s.flush()
            kp = db.KnowledgePoint(
                subject="数学", chapter="一元二次方程",
                kp_name="配方法解一元二次方程", concept="c",
            )
            s.add(kp)
            s.flush()
            q = db.Question(kp_id=kp.id, stem="stem", answer="x₁=3.0, x₂=2.0", source="ai_generated")
            s.add(q)
            s.commit()
            self.student_id, self.kp_id, self.question_id = stu.id, kp.id, q.id

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self.engine.dispose()
        os.unlink(self.db_path)

    def _fake_grade(self) -> dict:
        return {
            "question_id": str(self.question_id),
            "is_correct": False,
            "error": {
                "error_type": "计算",
                "error_kp_id": str(self.kp_id),
                "confidence": 0.9,
                "evidence": "第2步符号错",
                "evidence_source": "llm",
                "ai_certain": True,
                "teacher_reviewed": False,
                "steps_analyzed": 2,
                "insufficient_evidence": False,
            },
            "steps": [{"basis": "求解", "result": "x1=3"}],
        }

    def _run(self, decision: str) -> dict:
        with patch(
            "app.harness.legacy_graph.grade_question",
            return_value=self._fake_grade(),
        ):
            graph = build_tutor_graph(InMemorySaver())
            config = {"configurable": {"thread_id": "t-persist"}}
            graph.invoke(
                {
                    "student_id": str(self.student_id),
                    "question": {
                        "id": str(self.question_id),
                        "kp_id": str(self.kp_id),
                        "answer": "x₁=3.0, x₂=2.0",
                        "params": {"a": 1.0, "b": -5.0, "c": 6.0},
                    },
                    "student_steps": [{"basis": "求解", "result": "x1=3"}],
                    "session_id": "sess-1",
                    "phase": "grade",
                },
                config,
            )
            return graph.invoke(Command(resume=decision), config)

    def test_accept_writes_mastery_answer_and_decision(self):
        final = self._run("accept")
        self.assertEqual(final["teacher_decision"], "accept")

        Session = review_store.SessionLocal
        with Session() as s:
            m = s.query(db.Mastery).filter_by(
                student_id=self.student_id, kp_id=self.kp_id
            ).one()
            self.assertEqual(m.level, "weak")       # 3 级词汇，合法枚举值
            self.assertEqual(m.confirmed_wrong_count, 1)

            rec = s.query(db.AnswerRecord).one()
            self.assertEqual(rec.question_id, self.question_id)
            self.assertEqual(rec.session_id, "sess-1")
            self.assertFalse(rec.is_correct)
            self.assertEqual(rec.error_type, "计算")
            self.assertEqual(rec.answer, "x1=3")

            td = s.query(db.TeacherDecision).one()
            self.assertEqual(td.decision, "accept")
            self.assertEqual(td.session_id, "sess-1")
            self.assertEqual(td.question_id, self.question_id)
            self.assertEqual(td.proposal["kp_id"], str(self.kp_id))

    def test_reject_keeps_mastery_clean_but_records_facts(self):
        final = self._run("reject")
        self.assertEqual(final["teacher_decision"], "reject")

        Session = review_store.SessionLocal
        with Session() as s:
            self.assertEqual(s.query(db.Mastery).count(), 0)  # 否决 → 画像不写
            self.assertEqual(s.query(db.AnswerRecord).count(), 1)  # 做题事实保留
            td = s.query(db.TeacherDecision).one()
            self.assertEqual(td.decision, "reject")

    def test_duplicate_accept_is_idempotent(self):
        question = {
            "id": str(self.question_id),
            "kp_id": str(self.kp_id),
        }
        result = self._fake_grade()
        proposal = {
            "kp_id": str(self.kp_id),
            "confirmed_wrong_count_delta": 1,
            "suggest_level": "weak",
            "confidence": 0.5,
            "evidence": "重复恢复测试",
            "reason": "计算",
        }

        self.assertTrue(
            review_store.record_answer(
                str(self.student_id),
                question,
                result,
                "sess-idempotent",
                attempt_no=1,
            )
        )
        self.assertFalse(
            review_store.record_answer(
                str(self.student_id),
                question,
                result,
                "sess-idempotent",
                attempt_no=1,
            )
        )
        review_store.persist_teacher_review(
            str(self.student_id),
            [proposal],
            "accept",
            "sess-idempotent",
        )
        review_store.persist_teacher_review(
            str(self.student_id),
            [proposal],
            "accept",
            "sess-idempotent",
        )

        Session = review_store.SessionLocal
        with Session() as s:
            self.assertEqual(s.query(db.AnswerRecord).count(), 1)
            self.assertEqual(s.query(db.TeacherDecision).count(), 1)
            mastery = s.query(db.Mastery).one()
            self.assertEqual(mastery.confirmed_wrong_count, 1)

    def test_h3_bundle_rolls_back_all_writes_on_failure(self):
        session_id = "sess-h3-atomic"
        session_store.start_practice_session(
            session_id,
            self.student_id,
            self.kp_id,
        )
        review_store.record_answer(
            str(self.student_id),
            {
                "id": str(self.question_id),
                "kp_id": str(self.kp_id),
            },
            self._fake_grade(),
            session_id,
        )
        proposal = {
            "kp_id": str(self.kp_id),
            "confirmed_wrong_count_delta": 0,
            "suggest_level": "mid",
            "confidence": 0.5,
            "evidence": "atomic test",
            "reason": "测试",
        }

        with patch.object(
            review_store,
            "_apply_to_db_in_session",
            side_effect=RuntimeError("write failed"),
        ):
            with self.assertRaises(RuntimeError):
                review_store.persist_teacher_review_bundle(
                    str(self.student_id),
                    [proposal],
                    "accept",
                    session_id,
                    overrides=[{
                        "question_id": str(self.question_id),
                        "kp_id": str(self.kp_id),
                        "after": True,
                    }],
                    error_edits=[{
                        "question_id": str(self.question_id),
                        "kp_id": str(self.kp_id),
                        "before": "计算",
                        "after": "审题",
                    }],
                    review_decision="accepted",
                )

        with review_store.SessionLocal() as s:
            answer = s.query(db.AnswerRecord).one()
            practice = s.get(db.PracticeSessionRecord, session_id)
            self.assertIsNone(answer.teacher_is_correct)
            self.assertEqual(answer.error_type, "计算")
            self.assertEqual(s.query(db.TeacherDecision).count(), 0)
            self.assertEqual(s.query(db.Mastery).count(), 0)
            self.assertEqual(practice.review_status, "pending")

    def test_database_rejects_duplicate_answer_attempt(self):
        Session = review_store.SessionLocal
        with self.assertRaises(IntegrityError):
            with Session() as s:
                for _ in range(2):
                    s.add(db.AnswerRecord(
                        student_id=self.student_id,
                        question_id=self.question_id,
                        answer="x1=3",
                        is_correct=False,
                        attempt_no=1,
                        session_id="sess-unique",
                    ))
                s.commit()


if __name__ == "__main__":
    unittest.main()
