"""P2 持久化测试：SqliteSaver 下老师审批跨图实例（模拟进程重启）可续跑.

InMemorySaver 重启即失；本文件用临时 checkpoint 库验证：
图实例 A 暂停在 interrupt → 全新连接 + 全新图实例 B 凭 thread_id resume →
审批落库恰好一次。
"""

import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from langgraph.types import Command
from langgraph.checkpoint.sqlite import SqliteSaver
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.adapters.persistence as db
import app.adapters.review_store as review_store
import app.adapters.session_store as session_store
import app.application.profile_evidence as profile_evidence
from app.harness.legacy_graph import build_tutor_graph


class TestCheckpointPersistence(unittest.TestCase):
    """跨实例 resume：checkpoints 落文件，业务数据落临时库"""

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
            patch.object(db, "SessionLocal", Session),
            patch.object(review_store, "SessionLocal", Session),
            patch.object(profile_evidence, "SessionLocal", Session),
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
            s.add_all([stu, kp])
            s.flush()
            q = db.Question(kp_id=kp.id, stem="stem", answer="x₁=3.0, x₂=2.0", source="ai_generated")
            s.add(q)
            s.commit()
            self.student_id, self.kp_id, self.question_id = stu.id, kp.id, q.id

        ckpt = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        ckpt.close()
        self.ckpt_path = ckpt.name
        self._connections = []

    def tearDown(self):
        for p in self._patches:
            p.stop()
        self.engine.dispose()
        for conn in self._connections:
            conn.close()
        os.unlink(self.db_path)
        os.unlink(self.ckpt_path)

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

    def test_teacher_review_resumes_after_graph_rebuild(self):
        conn_a = sqlite3.connect(self.ckpt_path, check_same_thread=False)
        self._connections.append(conn_a)
        saver_a = SqliteSaver(conn_a)
        graph_a = build_tutor_graph(saver_a)
        config = {"configurable": {"thread_id": "t-ckpt-restart"}}
        with patch(
            "app.harness.legacy_graph.grade_question",
            return_value=self._fake_grade(),
        ):
            graph_a.invoke(
                {
                    "student_id": str(self.student_id),
                    "question": {
                        "id": str(self.question_id),
                        "kp_id": str(self.kp_id),
                        "answer": "x₁=3.0, x₂=2.0",
                        "params": {"a": 1.0, "b": -5.0, "c": 6.0},
                    },
                    "student_steps": [{"basis": "求解", "result": "x1=3"}],
                    "session_id": "sess-ckpt",
                    "phase": "grade",
                },
                config,
            )

        # 模拟进程重启：全新连接 + 全新图实例，业务状态从 checkpoint 库恢复
        conn_b = sqlite3.connect(self.ckpt_path, check_same_thread=False)
        self._connections.append(conn_b)
        saver_b = SqliteSaver(conn_b)
        graph_b = build_tutor_graph(saver_b)
        final = graph_b.invoke(Command(resume="accept"), config)
        self.assertEqual(final["teacher_decision"], "accept")

        with self.session() as s:
            m = s.query(db.Mastery).filter_by(
                student_id=self.student_id, kp_id=self.kp_id
            ).one()
            self.assertEqual(m.level, "weak")
            self.assertEqual(s.query(db.AnswerRecord).count(), 1)
            self.assertEqual(s.query(db.TeacherDecision).count(), 1)


if __name__ == "__main__":
    unittest.main()
