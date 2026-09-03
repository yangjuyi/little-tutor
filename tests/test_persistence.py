"""落库行为测试：answer_records / teacher_decisions / mastery 3 级（离线，临时库）

Run with: .venv/Scripts/python -m unittest tests.test_persistence -v
"""

import os
import tempfile
import unittest
from unittest.mock import patch

from langgraph.types import Command
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.db as db
import app.profile_update as pu
from app.graph import build_tutor_graph


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
            patch.object(pu, "SessionLocal", Session),
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
        with patch("app.graph.grade_question", return_value=self._fake_grade()):
            graph = build_tutor_graph()
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

        Session = pu.SessionLocal
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

        Session = pu.SessionLocal
        with Session() as s:
            self.assertEqual(s.query(db.Mastery).count(), 0)  # 否决 → 画像不写
            self.assertEqual(s.query(db.AnswerRecord).count(), 1)  # 做题事实保留
            td = s.query(db.TeacherDecision).one()
            self.assertEqual(td.decision, "reject")


if __name__ == "__main__":
    unittest.main()
