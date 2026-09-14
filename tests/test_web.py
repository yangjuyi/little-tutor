"""简易 Web 演示版测试：三段式页面流全链路（离线，临时库）"""

import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from langgraph.checkpoint.sqlite import SqliteSaver
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.adapters.persistence as db
import app.adapters.review_store as review_store
import app.adapters.session_store as session_store
import app.web as web
import app.application.profile_evidence as profile_evidence
import app.application.student_practice as student_practice
import app.harness.question_assembly as question_assembly
import app.harness.session_graph as sg
from app.web.view_models import build_done_context
from tests.test_session_graph import SEEDS, conflicting_stem, seed_stem


class TestWebFlow(unittest.TestCase):
    """index → review → answer/result ×N → summary → done"""

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
            patch.object(sg, "SessionLocal", Session),
            patch.object(question_assembly, "SessionLocal", Session),
            patch.object(review_store, "SessionLocal", Session),
            patch.object(profile_evidence, "SessionLocal", Session),
            patch.object(session_store, "SessionLocal", Session),
        ]
        for p in self._patches:
            p.start()

        with Session() as s:
            stu = db.Student(name="杨同学")
            kp = db.KnowledgePoint(
                subject="数学", chapter="一元二次方程",
                kp_name="配方法解一元二次方程", concept="c",
            )
            s.add_all([stu, kp])
            s.flush()
            for difficulty, params in SEEDS:
                s.add(db.Question(
                    kp_id=kp.id,
                    stem=seed_stem(params),
                    answer="x₁=2.0, x₂=3.0" if params["a"] == 1 else "x₁=3.0, x₂=0.5",
                    difficulty=difficulty, source="ai_generated", params=params,
                ))
            s.commit()
            self.student_id, self.kp_id = stu.id, kp.id

        ckpt = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        ckpt.close()
        self.ckpt_path = ckpt.name
        self._connections = []
        conn = sqlite3.connect(self.ckpt_path, check_same_thread=False)
        self._connections.append(conn)
        student_practice.reset_runtime()
        checkpointer_patch = patch.object(
            student_practice,
            "default_checkpointer",
            lambda: SqliteSaver(conn),
        )
        checkpointer_patch.start()
        self._patches.append(checkpointer_patch)
        self.client = TestClient(web.app)

    def tearDown(self):
        for p in self._patches:
            p.stop()
        student_practice.reset_runtime()
        self.engine.dispose()
        for conn in self._connections:
            conn.close()
        os.unlink(self.db_path)
        os.unlink(self.ckpt_path)

    def _fake_grade(self):
        return {
            "question_id": "q",
            "is_correct": True,
            "error": {
                "error_type": "无错", "error_kp_id": str(self.kp_id),
                "confidence": 1.0, "evidence": "test", "evidence_source": "llm",
                "ai_certain": True, "teacher_reviewed": False,
                "steps_analyzed": 1, "insufficient_evidence": False,
            },
            "steps": [],
        }

    def _full_flow(self, decision="accept", level=None, extra=None):
        resp = self.client.post("/start", data={"count": "2"}, follow_redirects=False)
        self.assertEqual(resp.status_code, 303)
        resp = self.client.get("/teacher/review")
        self.assertIn("H1 组卷预审", resp.text)
        resp = self.client.post(
            "/teacher/review",
            data={"decision": "approve"},
            follow_redirects=False,
        )
        self.assertEqual(resp.headers["location"], "/answer/0")
        for idx in range(2):
            page = self.client.get(f"/answer/{idx}")
            self.assertIn('name="b1"', page.text)
            if idx == 1:
                self.assertNotIn("程序初评", page.text)
                self.assertIn("第 2 / 2 题", page.text)
            data = {
                "b1": "1", "b2": "-6", "b3": "6.25", "b4": "0.25",
                "b5": "2", "b6": "3",
            }
            resp = self.client.post(f"/answer/{idx}", data=data, follow_redirects=False)
            self.assertEqual(resp.headers["location"], f"/feedback/{idx}")
            feedback = self.client.get(f"/feedback/{idx}")
            self.assertIn("程序判分：正确", feedback.text)
            self.assertNotIn("AI 归因", feedback.text)
            next_url = (
                f"/answer/{idx + 1}"
                if idx + 1 < 2
                else "/answer/2"
            )
            self.assertIn(next_url, feedback.text)
        completed = self.client.get("/answer/2")
        self.assertIn("本次作答汇总", completed.text)
        self.assertEqual(completed.text.count("程序初评正确"), 2)
        result = self.client.get("/result/1")
        self.assertIn("程序初评", result.text)
        resp = self.client.post("/summarize", follow_redirects=False)
        self.assertEqual(resp.headers["location"], "/teacher/summary")
        summary = self.client.get("/teacher/summary")
        self.assertIn("本次练习结果确认", summary.text)
        self.assertIn("确认并更新学生画像", summary.text)
        self.assertIn("题级归因证据", summary.text)
        self.assertIn("AI 归因", summary.text)
        self.assertIn('name="error_0"', summary.text)
        self.assertIn('name="test_session"', summary.text)
        summary_data = {"decision": decision}
        if level:
            summary_data[f"level_{self.kp_id}"] = level
        if extra:
            summary_data.update(extra)
        resp = self.client.post(
            "/teacher/summary",
            data=summary_data,
            follow_redirects=False,
        )
        self.assertEqual(resp.headers["location"], "/done")
        return self.client.get("/done")

    def test_full_flow_accept_writes_mastery(self):
        with patch.object(sg, "grade_question", return_value=self._fake_grade()):
            done = self._full_flow("accept")
        self.assertIn("学生画像已更新", done.text)
        self.assertIn("学生画像", done.text)
        self.assertIn("错因分析", done.text)
        self.assertIn('id="profileRadar"', done.text)
        self.assertIn('id="errorRadar"', done.text)
        with self.session() as s:
            m = s.query(db.Mastery).one()
            self.assertEqual(m.level, "mid")
            self.assertEqual(s.query(db.TeacherDecision).count(), 1)
            session = s.query(db.PracticeSessionRecord).one()
            self.assertEqual(session.status, "completed")
            self.assertEqual(session.review_status, "accepted")
            answer = s.query(db.AnswerRecord).first()
            self.assertEqual(answer.attempt_no, 1)
            self.assertTrue(answer.first_attempt_correct)
            self.assertEqual(answer.assistance_level, "independent")

    def test_full_flow_reject_keeps_mastery_clean(self):
        with patch.object(sg, "grade_question", return_value=self._fake_grade()):
            done = self._full_flow("reject")
        self.assertIn("本次未更新学生画像", done.text)
        with self.session() as s:
            self.assertEqual(s.query(db.Mastery).count(), 0)
            self.assertEqual(s.query(db.TeacherDecision).count(), 1)
            session = s.query(db.PracticeSessionRecord).one()
            self.assertEqual(session.status, "completed")
            self.assertEqual(session.review_status, "rejected")
            answer = s.query(db.AnswerRecord).first()
            self.assertEqual(answer.attempt_no, 1)
            self.assertEqual(answer.hint_count, 0)
            self.assertEqual(answer.scaffold_level, 0)

    def test_teacher_can_correct_mastery_before_accept(self):
        with patch.object(sg, "grade_question", return_value=self._fake_grade()):
            done = self._full_flow("accept", level="strong")
        self.assertIn("学生画像已更新", done.text)
        with self.session() as s:
            mastery = s.query(db.Mastery).one()
            self.assertEqual(mastery.level, "strong")
            decision = s.query(db.TeacherDecision).one()
            self.assertEqual(decision.proposal["suggest_level"], "strong")
            self.assertTrue(decision.proposal["teacher_corrected"])

    def test_teacher_can_correct_error_type_from_summary(self):
        with patch.object(sg, "grade_question", return_value=self._fake_grade()):
            self._full_flow("accept", extra={"error_0": "漏根"})
        with self.session() as s:
            answer = (
                s.query(db.AnswerRecord)
                .order_by(db.AnswerRecord.id)
                .first()
            )
            self.assertEqual(answer.error_type, "漏根")
            correction = (
                s.query(db.TeacherDecision)
                .filter_by(decision="edit")
                .one()
            )
            self.assertEqual(
                correction.proposal["error_type_after"], "漏根"
            )

    def test_full_flow_can_mark_test_session(self):
        with patch.object(sg, "grade_question", return_value=self._fake_grade()):
            done = self._full_flow(
                "accept", extra={"test_session": "1"}
            )
        self.assertIn("测试会话", done.text)
        with self.session() as s:
            self.assertEqual(s.query(db.Mastery).count(), 0)
            session = s.query(db.PracticeSessionRecord).one()
            self.assertEqual(session.data_source, "test")
            self.assertEqual(session.review_status, "accepted")

    def test_hint_is_recorded_and_resets_for_next_question(self):
        with patch.object(sg, "grade_question", return_value=self._fake_grade()):
            self.client.post("/start", data={"count": "2"})
            self.client.post(
                "/teacher/review", data={"decision": "approve"}
            )
            resp = self.client.post("/hint/0", follow_redirects=False)
            self.assertEqual(resp.headers["location"], "/answer/0")
            page = self.client.get("/answer/0")
            self.assertIn("提示 1/3", page.text)
            data = {
                "b1": "1", "b2": "-6", "b3": "6.25", "b4": "0.25",
                "b5": "2", "b6": "3",
            }
            self.client.post("/answer/0", data=data)
            next_page = self.client.get("/answer/1")
            self.assertNotIn("提示 1/3", next_page.text)
        with self.session() as s:
            answer = s.query(db.AnswerRecord).one()
            self.assertEqual(answer.hint_count, 1)
            self.assertEqual(answer.assistance_level, "hinted")

    def test_scaffold_is_recorded_and_enters_evidence_chain(self):
        with patch.object(sg, "grade_question", return_value=self._fake_grade()):
            self.client.post("/start", data={"count": "2"})
            self.client.post(
                "/teacher/review", data={"decision": "approve"}
            )
            resp = self.client.post("/hint/0", follow_redirects=False)
            self.assertEqual(resp.headers["location"], "/answer/0")
            page = self.client.get("/answer/0")
            self.assertIn("还是不会，给我分步帮助", page.text)
            resp = self.client.post("/scaffold/0", follow_redirects=False)
            self.assertEqual(resp.headers["location"], "/answer/0")
            page = self.client.get("/answer/0")
            self.assertIn("分步帮助 1/2", page.text)
            data = {
                "b1": "1", "b2": "-6", "b3": "6.25", "b4": "0.25",
                "b5": "2", "b6": "3",
            }
            self.client.post("/answer/0", data=data)
        with self.session() as s:
            answer = s.query(db.AnswerRecord).one()
            self.assertEqual(answer.hint_count, 1)
            self.assertEqual(answer.scaffold_level, 1)
            self.assertEqual(answer.assistance_level, "scaffolded")
            self.assertEqual(answer.evidence_weight, 0.25)

    def test_teacher_can_edit_stem_before_approval(self):
        self.client.post("/start", data={"count": "2"})
        values = student_practice.get_graph().get_state({
            "configurable": {
                "thread_id": self.client.cookies.get("thread_id")
            }
        }).values
        candidate = values["candidates"][0]
        params = candidate["params"]
        edited_stem = candidate["stem"] + "（老师已校对）"
        resp = self.client.post(
            "/teacher/review/edit",
            data={
                "no": "1",
                "stem": edited_stem,
                "a": params["a"],
                "b": params["b"],
                "c": params["c"],
                "structure_tag": params.get("structure_tag", ""),
            },
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 303)
        page = self.client.get("/teacher/review")
        self.assertIn(edited_stem, page.text)
        self.client.post(
            "/teacher/review", data={"decision": "approve"}
        )
        values = student_practice.get_graph().get_state({
            "configurable": {
                "thread_id": self.client.cookies.get("thread_id")
            }
        }).values
        self.assertIn(
            edited_stem,
            [question["stem"] for question in values["approved_pool"]],
        )

    def test_semantic_conflict_is_shown_without_losing_review_state(self):
        self.client.post("/start", data={"count": "2"})
        values = student_practice.get_graph().get_state({
            "configurable": {
                "thread_id": self.client.cookies.get("thread_id")
            }
        }).values
        candidate = values["candidates"][0]
        params = candidate["params"]
        resp = self.client.post(
            "/teacher/review/edit",
            data={
                "no": "1",
                "stem": conflicting_stem(params),
                "a": params["a"],
                "b": params["b"],
                "c": params["c"],
                "structure_tag": params.get("structure_tag", ""),
            },
            follow_redirects=False,
        )
        self.assertEqual(resp.headers["location"], "/teacher/review")
        page = self.client.get("/teacher/review")
        self.assertIn("题干与参数冲突", page.text)
        self.assertIn("第 1 题", page.text)

    def test_back_navigation_cannot_duplicate_answers(self):
        """浏览器后退到已答题：只能看结果，重答被拦截，不产生重复数据"""
        with patch.object(sg, "grade_question", return_value=self._fake_grade()):
            self.client.post("/start", data={"count": "2"})
            self.client.post(
                "/teacher/review", data={"decision": "approve"}
            )
            for idx in range(2):
                self.client.post(
                    f"/answer/{idx}",
                    data={"b1": "1", "b2": "-6", "b3": "6.25", "b4": "0.25",
                          "b5": "2", "b6": "3"},
                )
            # 后退到第 1 题：跳会话完成页，不允许重答
            resp = self.client.get("/answer/0", follow_redirects=False)
            self.assertEqual(resp.headers["location"], "/answer/2")
            resp = self.client.post("/answer/0", data={"b1": "1"}, follow_redirects=False)
            self.assertEqual(resp.headers["location"], "/answer/2")
        with self.session() as s:
            self.assertEqual(s.query(db.AnswerRecord).count(), 2)

    def test_done_context_aggregates_error_causes(self):
        def result(
            error_type,
            correct=False,
            blank_correct=True,
            evidence_source="llm",
        ):
            return {
                "is_correct": correct,
                "error": {
                    "error_type": error_type,
                    "insufficient_evidence": False,
                    "evidence_source": evidence_source,
                },
                "blank_results": [
                    {"is_correct": blank_correct},
                    {"is_correct": True},
                ],
            }

        context = build_done_context({
            "round_results": [
                result("计算"),
                result("计算"),
                result("概念"),
                result("未归因", evidence_source="program"),
                result("无错", correct=True),
            ],
            "session_proposals": [{"suggest_level": "weak", "kp_name": "配方法"}],
        })
        self.assertEqual(context["total"], 5)
        self.assertEqual(context["wrong"], 4)
        self.assertEqual(context["error_counts"]["计算"], 2)
        self.assertEqual(context["error_counts"]["概念"], 1)
        self.assertNotIn("未归因", context["error_counts"])
        self.assertEqual(context["unattributed_count"], 1)
        self.assertEqual(context["error_counts"]["审题"], 0)

    def test_ratio_sliders_keep_submitted_values_after_regroup(self):
        self.client.post("/start", data={"count": "4"})
        resp = self.client.post(
            "/teacher/review/regroup-ratios",
            data={"simple_r": "70", "mid_r": "20"},
            follow_redirects=False,
        )
        self.assertEqual(resp.status_code, 303)
        page = self.client.get("/teacher/review")
        self.assertIn('name="simple_r" min="0" max="100" step="5" value="70"', page.text)
        self.assertIn('name="mid_r" min="0" max="100" step="5" value="20"', page.text)
        self.assertIn('<output id="v-hard">10</output>', page.text)
        self.assertIn('rh.value = h;', page.text)
        self.assertIn('syncRatios();', page.text)

    def test_start_hides_thread_id_and_reuses_student_identity(self):
        page = self.client.get("/")
        self.assertNotIn('name="thread_id"', page.text)

        first = self.client.post(
            "/start", data={"count": "2"}, follow_redirects=False,
        )
        first_student = first.cookies["student_id"]
        first_thread = first.cookies["thread_id"]
        self.assertTrue(first_student)
        self.assertRegex(first_thread, r"^web-[0-9a-f]{8}$")

        second = self.client.post(
            "/start", data={"count": "2"}, follow_redirects=False,
        )
        self.assertEqual(second.cookies["student_id"], first_student)
        self.assertNotEqual(second.cookies["thread_id"], first_thread)

    def test_teacher_token_guards_teacher_routes(self):
        with patch.dict(os.environ, {"TUTOR_TEACHER_TOKEN": "secret"}):
            resp = self.client.get("/teacher/review", follow_redirects=False)
            self.assertEqual(resp.headers["location"], "/teacher/login")

            resp = self.client.post(
                "/teacher/login",
                data={"token": "wrong"},
                follow_redirects=False,
            )
            self.assertEqual(resp.headers["location"], "/teacher/login?error=1")

            resp = self.client.post(
                "/teacher/login",
                data={"token": "secret"},
                follow_redirects=False,
            )
            self.assertEqual(resp.headers["location"], "/teacher/review")
            self.assertIn("teacher_token=", resp.headers["set-cookie"])


if __name__ == "__main__":
    unittest.main()
