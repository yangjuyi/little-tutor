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
import app.web.auth as web_auth
import app.application.profile_evidence as profile_evidence
import app.application.student_practice as student_practice
import app.harness.question_assembly as question_assembly
import app.harness.session_graph as sg
from app.web.view_models import build_done_context
from app.domain.answer_template import build_template
from tests.test_session_graph import SEEDS, conflicting_stem, seed_stem


class TestWebFlow(unittest.TestCase):
    """index → review → answer/result ×N → summary → done"""

    def setUp(self):
        web_auth.reset_teacher_login_attempts()
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
        web_auth.reset_teacher_login_attempts()
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

    def _correct_answer_data(self, idx):
        values = student_practice.get_graph().get_state(
            {"configurable": {"thread_id": self.client.cookies["thread_id"]}}
        ).values
        question = values["approved_questions"][idx]
        template = build_template(question["params"])
        data = {}
        for blank in template["blanks"]:
            if blank["kind"] == "choice":
                data[blank["id"]] = str(blank["answer_index"] + 1)
            else:
                data[blank["id"]] = f"{blank['expected']:g}"
        return data

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
        self.assertEqual(resp.headers["location"], "/teacher/review-done")
        for idx in range(2):
            page = self.client.get(f"/answer/{idx}")
            self.assertIn('name="b1"', page.text)
            if idx == 1:
                self.assertNotIn("程序初评", page.text)
                self.assertIn("第 2 / 2 题", page.text)
            data = self._correct_answer_data(idx)
            resp = self.client.post(f"/answer/{idx}", data=data, follow_redirects=False)
            next_url = (
                f"/answer/{idx + 1}"
                if idx + 1 < 2
                else "/answer/2"
            )
            self.assertEqual(resp.headers["location"], next_url)
            feedback = self.client.get(f"/feedback/{idx}")
            self.assertIn("程序判分：正确", feedback.text)
            self.assertNotIn("AI 归因", feedback.text)
        completed = self.client.get("/answer/2")
        self.assertIn("本次作答汇总", completed.text)
        self.assertEqual(completed.text.count("程序初评正确"), 2)
        result = self.client.get("/result/1")
        self.assertIn("程序初评", result.text)
        resp = self.client.post("/summarize", follow_redirects=False)
        self.assertEqual(
            resp.headers["location"], "/waiting-confirmation"
        )
        student_wait = self.client.get("/waiting-confirmation")
        self.assertIn("已提交给老师确认", student_wait.text)
        old_review = self.client.get(
            "/teacher/review", follow_redirects=False
        )
        self.assertEqual(
            old_review.headers["location"], "/teacher/summary"
        )
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
        self.assertEqual(resp.headers["location"], "/teacher/completed")
        return self.client.get("/done")

    def test_full_flow_accept_writes_mastery(self):
        with patch.object(sg, "grade_question", return_value=self._fake_grade()):
            done = self._full_flow("accept")
        self.assertIn("学生画像已更新", done.text)
        self.assertIn("学生画像", done.text)
        self.assertIn("错因分析", done.text)
        self.assertIn('id="profileRadar"', done.text)
        self.assertIn('id="errorRadar"', done.text)
        review_done = self.client.get("/teacher/review-done")
        self.assertEqual(review_done.status_code, 200)
        self.assertIn("题目预审完成", review_done.text)
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

    def test_start_rejects_invalid_question_count(self):
        for raw in ("-1", "0", "abc", "31"):
            with self.subTest(count=raw):
                resp = self.client.post(
                    "/start",
                    data={"count": raw},
                    follow_redirects=False,
                )
                self.assertEqual(resp.status_code, 303)
                self.assertTrue(
                    resp.headers["location"].startswith("/?error=")
                )
        with self.session() as s:
            self.assertEqual(s.query(db.PracticeSessionRecord).count(), 0)
        page = self.client.get("/?error=题量必须是 1-30 的整数")
        self.assertIn("题量必须是 1-30 的整数", page.text)

    def test_empty_question_count_uses_default(self):
        for raw in ("", "   "):
            with self.subTest(count=repr(raw)):
                resp = self.client.post(
                    "/start",
                    data={"count": raw},
                    follow_redirects=False,
                )
                self.assertEqual(resp.status_code, 303)
                self.assertEqual(resp.headers["location"], "/waiting")
                values = student_practice.get_graph().get_state(
                    {
                        "configurable": {
                            "thread_id": resp.cookies["thread_id"]
                        }
                    }
                ).values
                self.assertEqual(values["question_count"], 10)

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
            data = self._correct_answer_data(0)
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
            self.client.post("/hint/0", follow_redirects=False)
            page = self.client.get("/answer/0")
            self.assertIn("还是不会，升级为分步帮助", page.text)
            resp = self.client.post("/scaffold/0", follow_redirects=False)
            self.assertEqual(resp.headers["location"], "/answer/0")
            page = self.client.get("/answer/0")
            self.assertIn("分步帮助 1/2", page.text)
            data = self._correct_answer_data(0)
            self.client.post("/answer/0", data=data)
        with self.session() as s:
            answer = s.query(db.AnswerRecord).one()
            self.assertEqual(answer.hint_count, 2)
            self.assertEqual(answer.scaffold_level, 1)
            self.assertEqual(answer.assistance_level, "scaffolded")
            self.assertEqual(answer.evidence_weight, 0.25)

    def test_wrong_process_with_correct_final_answer_is_not_marked_correct(self):
        with patch.object(sg, "grade_question", return_value=self._fake_grade()):
            self.client.post("/start", data={"count": "2"})
            self.client.post(
                "/teacher/review", data={"decision": "approve"}
            )
            data = self._correct_answer_data(0)
            values = student_practice.get_graph().get_state(
                {"configurable": {"thread_id": self.client.cookies["thread_id"]}}
            ).values
            template = build_template(values["approved_questions"][0]["params"])
            expression = next(
                blank for blank in template["blanks"]
                if blank["kind"] == "expression"
            )
            data[expression["id"]] = "999"
            self.client.post("/answer/0", data=data)
            feedback = self.client.get("/feedback/0")
        self.assertIn("过程错误", feedback.text)
        with self.session() as s:
            answer = s.query(db.AnswerRecord).one()
            self.assertFalse(answer.is_correct)

    def test_student_can_skip_without_forced_answer(self):
        self.client.post("/start", data={"count": "2"})
        self.client.post("/teacher/review", data={"decision": "approve"})
        page = self.client.get("/answer/0")
        self.assertIn("这题不会，先跳过", page.text)
        resp = self.client.post("/skip/0", follow_redirects=False)
        self.assertEqual(resp.headers["location"], "/answer/1")
        feedback = self.client.get("/feedback/0")
        self.assertIn("本题已跳过", feedback.text)
        next_page = self.client.get("/answer/1")
        self.assertIn("第 2 / 2 题", next_page.text)
        with self.session() as s:
            answer = s.query(db.AnswerRecord).one()
            self.assertFalse(answer.is_correct)
            self.assertEqual(answer.answer, "")
            self.assertEqual(answer.assistance_level, "skipped")
            self.assertEqual(answer.evidence_weight, 0.0)
            self.assertEqual(answer.error_type, "未归因")

    def test_done_page_does_not_show_pending_after_teacher_review(self):
        self.client.post("/start", data={"count": "1"})
        self.client.post("/teacher/review", data={"decision": "approve"})
        self.client.post("/skip/0")
        self.client.post("/summarize")
        self.client.post(
            "/teacher/summary",
            data={"decision": "reject"},
            follow_redirects=False,
        )
        done = self.client.get("/done")
        self.assertIn("老师已确认", done.text)
        self.assertNotIn("错因尚待老师确认", done.text)

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
        updated = student_practice.get_graph().get_state({
            "configurable": {
                "thread_id": self.client.cookies.get("thread_id")
            }
        }).values["candidates"][0]
        self.assertIsInstance(updated["params"]["a"], int)
        self.assertIsInstance(updated["params"]["b"], int)
        self.assertIsInstance(updated["params"]["c"], int)
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
                    f"/answer/{idx}", data=self._correct_answer_data(idx)
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
        self.assertEqual(first.headers["location"], "/waiting")
        first_student = first.cookies["student_id"]
        first_thread = first.cookies["thread_id"]
        self.assertTrue(first_student)
        self.assertRegex(first_thread, r"^web-[0-9a-f]{8}$")

        second = self.client.post(
            "/start", data={"count": "2"}, follow_redirects=False,
        )
        self.assertEqual(second.cookies["student_id"], first_student)
        self.assertNotEqual(second.cookies["thread_id"], first_thread)

    def test_waiting_page_moves_to_answer_after_teacher_approval(self):
        self.client.post("/start", data={"count": "2"})
        waiting = self.client.get("/waiting")
        self.assertIn("已提交给老师审核", waiting.text)
        approved = self.client.post(
            "/teacher/review",
            data={"decision": "approve"},
            follow_redirects=False,
        )
        self.assertEqual(
            approved.headers["location"], "/teacher/review-done"
        )
        done = self.client.get("/teacher/review-done")
        self.assertIn("题目预审完成", done.text)
        waiting_summary = self.client.get("/teacher/summary")
        self.assertIn("等待学生完成练习", waiting_summary.text)
        self.assertIn('http-equiv="refresh"', waiting_summary.text)
        moved = self.client.get("/waiting", follow_redirects=False)
        self.assertEqual(moved.headers["location"], "/answer/0")

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
            self.assertEqual(resp.headers["location"], "/teacher/sessions")
            self.assertIn("teacher_token=", resp.headers["set-cookie"])

    def test_teacher_login_locks_after_repeated_failures(self):
        with patch.dict(os.environ, {"TUTOR_TEACHER_TOKEN": "secret"}):
            for attempt in range(web_auth.MAX_LOGIN_FAILURES):
                resp = self.client.post(
                    "/teacher/login",
                    data={"token": f"wrong-{attempt}"},
                    follow_redirects=False,
                )
            self.assertEqual(
                resp.headers["location"], "/teacher/login?error=locked"
            )
            page = self.client.get("/teacher/login?error=locked")
            self.assertIn("尝试次数过多", page.text)
            self.assertIn("30 秒", page.text)
            correct = self.client.post(
                "/teacher/login",
                data={"token": "secret"},
                follow_redirects=False,
            )
            self.assertEqual(
                correct.headers["location"], "/teacher/login?error=locked"
            )

    def test_teacher_can_select_session_from_another_browser(self):
        self.client.post("/start", data={"count": "2"})
        session_id = self.client.cookies["thread_id"]
        other = TestClient(web.app)
        with patch.dict(os.environ, {"TUTOR_TEACHER_TOKEN": "secret"}):
            login = other.post(
                "/teacher/login",
                data={"token": "secret"},
                follow_redirects=False,
            )
            self.assertEqual(login.headers["location"], "/teacher/sessions")
            dashboard = other.get("/teacher/sessions")
            self.assertIn("待预审", dashboard.text)
            self.assertIn(session_id, dashboard.text)
            selected = other.get(
                f"/teacher/session/{session_id}",
                follow_redirects=False,
            )
            self.assertEqual(selected.headers["location"], "/teacher/review")
            self.assertIn(
                "teacher_thread_id=", selected.headers["set-cookie"]
            )
            review = other.get("/teacher/review")
            self.assertIn("组卷预审", review.text)

    def test_error_page_retries_without_manual_thread_id(self):
        self.client.cookies.set("thread_id", "t-error-page")
        with patch.object(
            student_practice,
            "load_review",
            return_value={"kind": "error", "message": "组卷失败"},
        ):
            page = self.client.get("/teacher/review")
        self.assertEqual(page.status_code, 200)
        self.assertIn("组卷失败", page.text)
        self.assertIn('href="/teacher/review"', page.text)
        self.assertNotIn("原会话 ID", page.text)


if __name__ == "__main__":
    unittest.main()
