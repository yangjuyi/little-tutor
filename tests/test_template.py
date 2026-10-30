"""A 模板填空测试：程序生成模板 + 逐空判定 + 断点定位（离线）"""

import unittest
from unittest.mock import patch

from langgraph.checkpoint.memory import InMemorySaver

from app.domain.answer_template import (
    build_template,
    judge_blanks,
    first_wrong_blank,
)
from app.application.student_practice import _build_student_steps
from app.domain.program_grading import compute_program_grade
from app.harness.legacy_graph import build_tutor_graph
_FAKE_MASTERY = {
    "suggest_level": "weak", "confidence": 0.0, "evidence": "test", "sessions": 0,
}


class TestBuildTemplate(unittest.TestCase):
    """按 (a,b,c) 程序生成配方法模板"""

    def test_simple_template_blanks(self):
        tpl = build_template({"a": 1, "b": -6, "c": 8})
        blanks = tpl["blanks"]
        self.assertEqual(len(blanks), 6)
        self.assertEqual(blanks[0]["kind"], "choice")
        self.assertEqual(set(blanks[0]["options"]), {"常数项", "一次项", "二次项"})
        self.assertEqual(
            blanks[0]["options"][blanks[0]["answer_index"]], "常数项",
        )
        # 移项右值 -c/a；配方加项 (b/2a)²；开方前 (b/2a)²-c/a；两根
        self.assertEqual(blanks[1]["expected"], -8)
        self.assertEqual(blanks[2]["expected"], 9)
        self.assertEqual(blanks[3]["expected"], 1)
        self.assertEqual(blanks[4]["expected"], 2.0)
        self.assertEqual(blanks[5]["expected"], 4.0)
        self.assertEqual(tpl["answer_blank_ids"], ["b5", "b6"])

    def test_mid_template_needs_normalize(self):
        tpl = build_template({"a": 2, "b": -8, "c": 6})
        blanks = tpl["blanks"]
        self.assertEqual(
            set(blanks[0]["options"]),
            {"两边同时除以 2", "两边同时乘以 2", "直接开平方"},
        )
        self.assertEqual(blanks[1]["expected"], -3)
        self.assertEqual(blanks[4]["expected"], 1)
        self.assertEqual(blanks[5]["expected"], 3.0)

    def test_prompts_do_not_leak_intermediate_expressions(self):
        """后续空位只描述操作，不回显前序步骤算出的式子。"""
        for params in ({"a": 1, "b": -5, "c": 6}, {"a": 2, "b": -7, "c": 3}):
            with self.subTest(params=params):
                bases = [b["basis"] for b in build_template(params)["blanks"]]
                text = "\n".join(bases)
                self.assertNotIn("x²", text)
                self.assertNotIn("(x +", text)
                self.assertNotIn("² =", text)

    def test_application_templates_include_equation_setup(self):
        rectangle = build_template({
            "a": 2, "b": 4, "c": -30, "design_id": "rectangle",
        })["blanks"]
        self.assertIn("应列出的方程", rectangle[1]["basis"])
        self.assertEqual(rectangle[1]["kind"], "choice")
        self.assertEqual(len(rectangle), 6)
        self.assertEqual(
            build_template({
                "a": 2, "b": 4, "c": -30, "design_id": "rectangle",
            })["answer_blank_ids"],
            ["b6"],
        )

        consecutive = build_template({
            "a": 1, "b": 2, "c": -24, "design_id": "consecutive_even",
        })["blanks"]
        self.assertIn("应列出的方程", consecutive[1]["basis"])
        self.assertEqual(len(consecutive), 7)

    def test_root_relation_template_uses_vieta_then_roots(self):
        blanks = build_template({
            "a": 3, "b": -18, "c": 24, "design_id": "root_relation",
        })["blanks"]
        self.assertEqual(len(blanks), 4)
        self.assertIn("x₁+x₂", blanks[0]["basis"])
        self.assertIn("x₁x₂", blanks[1]["basis"])
        self.assertIn("较小的根", blanks[2]["basis"])
        self.assertIn("较大的根", blanks[3]["basis"])


class TestJudgeBlanks(unittest.TestCase):
    """逐空判定：数值/分数/容差/点选"""

    SIMPLE = build_template({"a": 1, "b": -6, "c": 8})

    def _steps(self, answers=None):
        if answers is None:
            answers = [
                (
                    str(b["answer_index"] + 1)
                    if b["kind"] == "choice"
                    else f"{b['expected']:g}"
                )
                for b in self.SIMPLE["blanks"]
            ]
        return [
            {"basis": b["basis"], "result": answer}
            for b, answer in zip(self.SIMPLE["blanks"], answers)
        ]

    def test_all_correct(self):
        results = judge_blanks(self.SIMPLE, self._steps())
        self.assertTrue(all(r["is_correct"] for r in results))

    def test_first_wrong_blank_located(self):
        answers = [
            str(b["answer_index"] + 1) if b["kind"] == "choice" else f"{b['expected']:g}"
            for b in self.SIMPLE["blanks"]
        ]
        answers[2] = "999"
        results = judge_blanks(self.SIMPLE, self._steps(answers))
        wrong = first_wrong_blank(results)
        self.assertEqual(wrong["blank_id"], "b3")

    def test_expression_accepts_fraction(self):
        tpl = build_template({"a": 2, "b": -7, "c": 3, "design_id": "direct"})
        answers = ["1", "-3/2", "3.0625", "1.5625", "0.5", "3"]
        steps = [
            {"basis": b["basis"], "result": answer}
            for b, answer in zip(tpl["blanks"], answers)
        ]
        results = judge_blanks(tpl, steps)
        self.assertTrue(results[1]["is_correct"])

    def test_choice_accepts_digit_and_letter(self):
        index = self.SIMPLE["blanks"][0]["answer_index"]
        for answer in (str(index + 1), chr(ord("A") + index)):
            with self.subTest(answer=answer):
                results = judge_blanks(self.SIMPLE, [{"basis": "s", "result": answer}])
                self.assertTrue(results[0]["is_correct"])

    def test_choice_rejects_wrong_index(self):
        correct = self.SIMPLE["blanks"][0]["answer_index"]
        wrong = next(str(i + 1) for i in range(3) if i != correct)
        results = judge_blanks(self.SIMPLE, [{"basis": "s", "result": wrong}])
        self.assertFalse(results[0]["is_correct"])

    def test_tolerance_boundary(self):
        answers = [
            str(b["answer_index"] + 1) if b["kind"] == "choice" else f"{b['expected']:g}"
            for b in self.SIMPLE["blanks"]
        ]
        answers[4] = "2.004"
        steps = self._steps(answers)
        self.assertTrue(judge_blanks(self.SIMPLE, steps)[4]["is_correct"])
        answers[4] = "3.1"
        steps = self._steps(answers)
        self.assertFalse(judge_blanks(self.SIMPLE, steps)[4]["is_correct"])

    def test_all_correct_returns_no_breakpoint(self):
        results = judge_blanks(self.SIMPLE, self._steps())
        self.assertIsNone(first_wrong_blank(results))

    def test_unfilled_blank_is_not_marked_as_wrong_breakpoint(self):
        answers = ["", "", "", "", "", ""]
        results = judge_blanks(self.SIMPLE, self._steps(answers))
        self.assertTrue(all(result["unfilled"] for result in results))
        self.assertIsNone(first_wrong_blank(results))

    def test_partial_submission_builds_unfilled_steps_and_blocks_guessing(self):
        question = {
            "id": "q-partial",
            "kp_id": "1",
            "stem": "解方程 x² - 6x + 8 = 0",
            "answer": "x₁=4, x₂=2",
            "params": {"a": 1, "b": -6, "c": 8, "design_id": "direct"},
        }
        expected_template = build_template(question["params"])
        template, steps = _build_student_steps(
            question,
            {
                "b1": str(expected_template["blanks"][0]["answer_index"] + 1),
                "b2": "-8",
                "b5": "2",
            },
        )
        self.assertTrue(any(step.get("unfilled") for step in steps))
        self.assertEqual(steps[-1]["result"], "x=2")
        result = compute_program_grade(question, steps, template)
        self.assertTrue(result["submission_incomplete"])
        self.assertTrue(result["attribution_blocked_by_unfilled"])
        self.assertNotIn("program_breakpoint", result)
        self.assertFalse(result["final_answer_correct"])


class TestGradeNodeTemplateMerge(unittest.TestCase):
    """grade_node 合并逐空结果与程序断点（grade_question 打桩）"""

    def _grade_payload(self, steps):
        return {
            "question_id": "q-1",
            "is_correct": True,
            "error": {
                "error_type": "无错",
                "error_kp_id": "1",
                "confidence": 1.0,
                "evidence": "ok",
                "evidence_source": "llm",
                "ai_certain": True,
                "teacher_reviewed": False,
                "steps_analyzed": len(steps),
                "insufficient_evidence": False,
            },
            "steps": steps,
        }

    def _invoke(self, steps):
        template = build_template({"a": 1, "b": -6, "c": 8})
        graph = build_tutor_graph(InMemorySaver())
        config = {"configurable": {"thread_id": "t-template"}}
        with patch("app.harness.legacy_graph.grade_question", return_value=self._grade_payload(steps)), \
             patch("app.harness.profile_graph.propose_profile_change", return_value=dict(_FAKE_MASTERY)):
            graph.invoke(
                {
                    "student_id": "1",
                    "question": {"id": "q-1", "kp_id": "1"},
                    "template": template,
                    "student_steps": steps,
                    "session_id": "sess-template",
                    "phase": "grade",
                },
                config,
            )
        return graph.get_state(config).values["result"]

    def test_blank_results_merged(self):
        template = build_template({"a": 1, "b": -6, "c": 8})
        answers = [
            str(b["answer_index"] + 1) if b["kind"] == "choice" else f"{b['expected']:g}"
            for b in template["blanks"]
        ] + ["x1=2, x2=4"]
        steps = [{"basis": f"s{i}", "result": a} for i, a in enumerate(answers)]
        result = self._invoke(steps)
        self.assertEqual(len(result["blank_results"]), 6)
        self.assertNotIn("program_breakpoint", result["error"])
        self.assertTrue(result["final_answer_correct"])
        self.assertTrue(result["process_correct"])

    def test_program_breakpoint_on_wrong_blank(self):
        template = build_template({"a": 1, "b": -6, "c": 8})
        answers = [
            str(b["answer_index"] + 1) if b["kind"] == "choice" else f"{b['expected']:g}"
            for b in template["blanks"]
        ] + ["x1=2, x2=4"]
        answers[2] = "999"
        steps = [{"basis": f"s{i}", "result": a} for i, a in enumerate(answers)]
        result = self._invoke(steps)
        self.assertIn("第 3 个作答项", result["error"]["program_breakpoint"])
        self.assertFalse(result["is_correct"])
        self.assertTrue(result["final_answer_correct"])
        self.assertFalse(result["process_correct"])


if __name__ == "__main__":
    unittest.main()
