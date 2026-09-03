"""自动化测试：画像更新 HITL + 串图路由（离线，不调 LLM）

Run with: .venv/Scripts/python -m unittest tests.test_l5_l6 -v
"""

import unittest
from unittest.mock import patch

from langgraph.types import Command

from app.graph import route_by_phase, build_tutor_graph
from app.profile_update import build_profile_graph, propose_profile_change


FAKE_GRADE_WRONG = {
    "question_id": "q-1",
    "is_correct": False,
    "error": {
        "error_type": "计算",
        "error_kp_id": "39",
        "confidence": 0.9,
        "evidence": "第2步符号错",
        "evidence_source": "llm",
        "ai_certain": True,
        "teacher_reviewed": False,
        "steps_analyzed": 2,
        "insufficient_evidence": False,
    },
    "steps": [],
}


class TestProposeProfileChange(unittest.TestCase):
    """纯函数测试：批改结果 → 画像建议"""

    def test_wrong_answer_proposes_weak(self):
        p = propose_profile_change(FAKE_GRADE_WRONG)
        self.assertEqual(p["confirmed_wrong_count_delta"], 1)
        self.assertEqual(p["suggest_level"], "weak")
        self.assertEqual(p["reason"], "计算")

    def test_correct_answer_proposes_no_change(self):
        import copy
        g = copy.deepcopy(FAKE_GRADE_WRONG)
        g["is_correct"] = True
        g["error"]["error_type"] = "无错"
        p = propose_profile_change(g)
        self.assertEqual(p["confirmed_wrong_count_delta"], 0)
        self.assertEqual(p["suggest_level"], "mid")


class TestRouteByPhase(unittest.TestCase):
    """串图路由测试"""

    def test_generate_phase(self):
        self.assertEqual(route_by_phase({"phase": "generate"}), "generate")

    def test_grade_phase(self):
        self.assertEqual(route_by_phase({"phase": "grade"}), "grade")

    def test_default_is_generate(self):
        self.assertEqual(route_by_phase({}), "generate")


class TestProfileUpdateGraph(unittest.TestCase):
    """HITL 端到端：暂停 → 审批 → 按决定分流（不写真库，mock 全部落库函数）"""

    def _invoke_grade(self, graph, config):
        # mock 掉批改的 LLM 调用，从 grade 入口走完整链路（离线）
        with patch("app.graph.grade_question", return_value=FAKE_GRADE_WRONG):
            graph.invoke(
                {
                    "student_id": "999",
                    "question": {"id": "q-1", "kp_id": "39", "answer": "x1=1"},
                    "student_steps": [{"basis": "最终作答", "result": "x1=2"}],
                    "phase": "grade",
                },
                config,
            )

    def test_accept_persists_once(self):
        with patch("app.profile_update.apply_to_db") as mock_db, \
             patch("app.profile_update.record_answer"), \
             patch("app.profile_update.record_teacher_decision"):
            graph = build_tutor_graph()
            config = {"configurable": {"thread_id": "ut-accept"}}
            self._invoke_grade(graph, config)
            mock_db.assert_not_called()  # 暂停时绝不能提前落库
            final = graph.invoke(Command(resume="accept"), config)
            mock_db.assert_called_once()  # accept 恰好写一次
            self.assertEqual(final["teacher_decision"], "accept")

    def test_reject_never_persists(self):
        with patch("app.profile_update.apply_to_db") as mock_db, \
             patch("app.profile_update.record_answer") as mock_record, \
             patch("app.profile_update.record_teacher_decision") as mock_decision:
            graph = build_tutor_graph()
            config = {"configurable": {"thread_id": "ut-reject"}}
            self._invoke_grade(graph, config)
            final = graph.invoke(Command(resume="reject"), config)
            mock_db.assert_not_called()      # 老师否决 → mastery 不写
            mock_record.assert_called_once() # 但做题事实要留痕
            mock_decision.assert_called_once()  # 仲裁决定也留痕（reject 可追溯）
            self.assertEqual(final["teacher_decision"], "reject")

    def test_pause_payload_contains_proposal(self):
        graph = build_tutor_graph()
        config = {"configurable": {"thread_id": "ut-payload"}}
        self._invoke_grade(graph, config)
        snap = graph.get_state(config)
        payload = snap.tasks[0].interrupts[0].value
        self.assertIn("proposal", payload)
        self.assertEqual(payload["proposal"]["kp_id"], "39")
        self.assertEqual(snap.next, ("profile_update",))

    def test_missing_question_fails_before_interrupt(self):
        """缺 question 必须在打扰老师之前报错，而不是拍板后落库时崩"""
        graph = build_profile_graph()
        config = {"configurable": {"thread_id": "ut-no-question"}}
        with self.assertRaises(ValueError), \
             patch("app.profile_update.record_answer"), \
             patch("app.profile_update.record_teacher_decision"), \
             patch("app.profile_update.apply_to_db"):
            graph.invoke(
                {
                    "student_id": "999",
                    "result": dict(FAKE_GRADE_WRONG),
                },
                config,
            )


if __name__ == "__main__":
    unittest.main()
