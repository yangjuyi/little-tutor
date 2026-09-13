"""§16.5 掌握度计算规则测试：会话聚合正确率 → 建议等级（离线，临时库）"""

import os
import tempfile
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.adapters.persistence as db
import app.adapters.session_store as session_store
import app.application.profile_evidence as mastery


class TestMasteryRules(unittest.TestCase):
    """strong 防单次碰对 / mid 阈值 / 会话聚合 / 主 kp 隔离"""

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
        self.session = Session
        self._patches = [
            patch.object(mastery, "SessionLocal", Session),
            patch.object(session_store, "SessionLocal", Session),
        ]
        for p in self._patches:
            p.start()

        with Session() as s:
            stu = db.Student(name="测试学生")
            kp = db.KnowledgePoint(
                subject="数学", chapter="一元二次方程",
                kp_name="配方法解一元二次方程", concept="c",
            )
            kp_other = db.KnowledgePoint(
                subject="数学", chapter="因式分解",
                kp_name="十字相乘法", concept="c",
            )
            s.add_all([stu, kp, kp_other])
            s.flush()
            q1 = db.Question(kp_id=kp.id, stem="s", answer="a", source="ai_generated")
            q2 = db.Question(kp_id=kp.id, stem="s", answer="a", source="ai_generated")
            q_other = db.Question(
                kp_id=kp_other.id, stem="s", answer="a", source="ai_generated",
            )
            s.add_all([q1, q2, q_other])
            s.commit()
            self.student_id, self.kp_id = stu.id, kp.id
            self.q1, self.q2, self.q_other = q1.id, q2.id, q_other.id

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self.engine.dispose()
        os.unlink(self.db_path)

    def _answer(
        self,
        question_id,
        correct,
        session_id,
        *,
        evidence_weight=None,
        assistance_level="independent",
        hint_count=0,
    ):
        with self.session() as s:
            if s.get(db.PracticeSessionRecord, session_id) is None:
                s.add(db.PracticeSessionRecord(
                    session_id=session_id,
                    student_id=self.student_id,
                    kp_id=self.kp_id,
                    status="completed",
                    review_status="accepted",
                    data_source="real",
                ))
            s.add(db.AnswerRecord(
                student_id=self.student_id,
                question_id=question_id,
                answer="x1=3",
                is_correct=correct,
                evidence_weight=(
                    float(evidence_weight)
                    if evidence_weight is not None
                    else (1.0 if correct else 0.0)
                ),
                assistance_level=assistance_level,
                hint_count=hint_count,
                session_id=session_id,
            ))
            s.commit()

    def test_strong_requires_two_recent_strong_sessions(self):
        # 会话 s1、s2 全对（session_id 倒序 → s2 是"最近"）
        self._answer(self.q1, True, "s1")
        self._answer(self.q1, True, "s2")
        proposal = mastery.propose_mastery_change(self.student_id, self.kp_id)
        self.assertEqual(proposal["suggest_level"], "strong")
        self.assertEqual(proposal["confidence"], 1.0)

    def test_single_perfect_session_is_mid(self):
        self._answer(self.q1, True, "s1")
        proposal = mastery.propose_mastery_change(self.student_id, self.kp_id)
        self.assertEqual(proposal["suggest_level"], "mid")

    def test_hinted_history_uses_evidence_weight(self):
        self._answer(
            self.q1,
            True,
            "s1",
            evidence_weight=0.5,
            assistance_level="hinted",
            hint_count=1,
        )
        proposal = mastery.propose_mastery_change(self.student_id, self.kp_id)
        self.assertEqual(proposal["confidence"], 0.5)
        self.assertEqual(proposal["suggest_level"], "weak")

    def test_recent_weak_session_blocks_strong(self):
        # 次近 1.0 但最近只有 0.5：防"以前强最近崩"被误判 strong
        self._answer(self.q1, True, "s1")
        self._answer(self.q1, True, "s2")
        self._answer(self.q2, False, "s2")
        proposal = mastery.propose_mastery_change(self.student_id, self.kp_id)
        self.assertEqual(proposal["suggest_level"], "weak")

    def test_in_progress_answer_counts_as_current_session(self):
        self._answer(self.q1, True, "s1")
        proposal = mastery.propose_mastery_change(
            self.student_id, self.kp_id,
            current={"session_id": "s3", "correct": True},
        )
        self.assertEqual(proposal["suggest_level"], "strong")
        self.assertEqual(proposal["sessions"], 2)

    def test_first_answer_in_new_session(self):
        proposal = mastery.propose_mastery_change(
            self.student_id, self.kp_id,
            current={"session_id": "s1", "correct": True},
        )
        self.assertEqual(proposal["suggest_level"], "mid")
        self.assertEqual(proposal["sessions"], 1)

    def test_other_kp_records_do_not_count(self):
        self._answer(self.q_other, True, "s1")
        proposal = mastery.propose_mastery_change(
            self.student_id, self.kp_id,
            current={"session_id": "s2", "correct": True},
        )
        self.assertEqual(proposal["sessions"], 1)

    def test_invalid_session_states_do_not_enter_history(self):
        invalid_sessions = (
            ("pending", "completed", "pending", "real"),
            ("rejected", "completed", "rejected", "real"),
            ("test", "completed", "accepted", "test"),
            ("aborted", "aborted", "pending", "real"),
            ("started", "started", "pending", "real"),
        )
        with self.session() as s:
            for session_id, status, review_status, data_source in invalid_sessions:
                s.add(db.PracticeSessionRecord(
                    session_id=session_id,
                    student_id=self.student_id,
                    kp_id=self.kp_id,
                    status=status,
                    review_status=review_status,
                    data_source=data_source,
                ))
                s.add(db.AnswerRecord(
                    student_id=self.student_id,
                    question_id=self.q1,
                    answer="x1=3",
                    is_correct=True,
                    session_id=session_id,
                ))
            s.commit()

        proposal = mastery.propose_mastery_change(
            self.student_id, self.kp_id,
            current={"session_id": "current", "correct": True},
        )
        self.assertEqual(proposal["sessions"], 1)

    def test_no_records_and_no_current(self):
        proposal = mastery.propose_mastery_change(self.student_id, self.kp_id)
        self.assertEqual(proposal["suggest_level"], "weak")
        self.assertEqual(proposal["evidence"], "无作答记录")


if __name__ == "__main__":
    unittest.main()
