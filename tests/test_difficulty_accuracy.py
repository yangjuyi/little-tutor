"""B3 正确率归因测试：answer_records JOIN questions 按 difficulty 聚合（离线，临时库）"""

import os
import tempfile
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.adapters.persistence as db


class TestAccuracyByDifficulty(unittest.TestCase):
    """各难度正确率聚合与过滤（B3）"""

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
        self._patch = patch.object(db, "SessionLocal", Session)
        self._patch.start()

        with Session() as s:
            stu_a = db.Student(name="学生A")
            stu_b = db.Student(name="学生B")
            kp = db.KnowledgePoint(
                subject="数学", chapter="一元二次方程",
                kp_name="配方法解一元二次方程", concept="c",
            )
            s.add_all([stu_a, stu_b, kp])
            s.flush()
            questions = {}
            for difficulty in ("simple", "mid", "hard"):
                q = db.Question(
                    kp_id=kp.id, stem="stem", answer="ans",
                    difficulty=difficulty, source="ai_generated",
                )
                s.add(q)
                s.flush()
                questions[difficulty] = q.id
            s.commit()
            self.session = Session
            self.student_a, self.student_b = stu_a.id, stu_b.id
            self.kp_id = kp.id
            self.questions = questions

    def tearDown(self):
        self._patch.stop()
        self.engine.dispose()
        os.unlink(self.db_path)

    def _record(self, student_id, difficulty, is_correct, session_id="sess-1"):
        with self.session() as s:
            attempt_no = (
                s.query(db.AnswerRecord)
                .filter_by(
                    student_id=student_id,
                    question_id=self.questions[difficulty],
                    session_id=session_id,
                )
                .count()
                + 1
            )
            s.add(db.AnswerRecord(
                student_id=student_id,
                question_id=self.questions[difficulty],
                answer="x1=3",
                is_correct=is_correct,
                session_id=session_id,
                attempt_no=attempt_no,
            ))
            s.commit()

    def test_aggregates_by_difficulty(self):
        self._record(self.student_a, "simple", True)
        self._record(self.student_a, "mid", True)
        self._record(self.student_a, "mid", False)
        self._record(self.student_a, "hard", False)
        stats = db.accuracy_by_difficulty(kp_id=self.kp_id)
        self.assertEqual(stats["simple"], {"total": 1, "correct": 1, "accuracy": 1.0})
        self.assertEqual(stats["mid"]["total"], 2)
        self.assertEqual(stats["mid"]["accuracy"], 0.5)
        self.assertEqual(stats["hard"]["accuracy"], 0.0)

    def test_filter_by_student(self):
        self._record(self.student_a, "simple", True)
        self._record(self.student_b, "simple", False)
        stats = db.accuracy_by_difficulty(student_id=self.student_a)
        self.assertEqual(stats["simple"]["total"], 1)
        self.assertEqual(stats["simple"]["accuracy"], 1.0)

    def test_filter_by_session(self):
        self._record(self.student_a, "mid", True, session_id="s1")
        self._record(self.student_a, "mid", False, session_id="s2")
        stats = db.accuracy_by_difficulty(session_id="s1")
        self.assertEqual(stats["mid"], {"total": 1, "correct": 1, "accuracy": 1.0})

    def test_kp_filter_excludes_other_kp(self):
        with self.session() as s:
            kp2 = db.KnowledgePoint(
                subject="数学", chapter="因式分解",
                kp_name="十字相乘法", concept="c",
            )
            s.add(kp2)
            s.flush()
            q2 = db.Question(
                kp_id=kp2.id, stem="stem", answer="ans",
                difficulty="simple", source="ai_generated",
            )
            s.add(q2)
            s.flush()
            s.add(db.AnswerRecord(
                student_id=self.student_a, question_id=q2.id,
                answer="ans", is_correct=True, session_id="sess-1",
            ))
            s.commit()
        self._record(self.student_a, "mid", True)
        stats = db.accuracy_by_difficulty(kp_id=self.kp_id)
        self.assertEqual(set(stats.keys()), {"mid"})

    def test_no_records_returns_empty(self):
        self.assertEqual(db.accuracy_by_difficulty(), {})


if __name__ == "__main__":
    unittest.main()
