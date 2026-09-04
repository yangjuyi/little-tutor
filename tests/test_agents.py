"""Unit tests for agents.py (program layer only, no LLM calls).

Run with: .venv/Scripts/python -m unittest tests.test_agents -v
"""

import unittest
from collections import Counter

from app.agents import (
    pick_difficulty,
    compute_answer,
    validate_params,
    extract_numbers,
    check_is_correct,
    grade_question,
)


class TestPickDifficulty(unittest.TestCase):
    """测试难度混合矩阵（spec §16.5）"""

    def test_weak_never_returns_hard(self):
        """weak 不应该出难题"""
        for _ in range(100):
            self.assertNotEqual(pick_difficulty("weak"), "hard")

    def test_weak_distribution(self):
        """weak 1000 次采样，simple 约 60% / mid 约 40%（允许 ±10%）"""
        results = [pick_difficulty("weak") for _ in range(1000)]
        counts = Counter(results)
        simple_ratio = counts["simple"] / 1000
        mid_ratio = counts["mid"] / 1000
        self.assertAlmostEqual(simple_ratio, 0.6, delta=0.1)
        self.assertAlmostEqual(mid_ratio, 0.4, delta=0.1)

    def test_strong_can_return_hard(self):
        """strong 应该可能返回 hard"""
        results = [pick_difficulty("strong") for _ in range(100)]
        self.assertIn("hard", results)

    def test_invalid_level_raises(self):
        """不合法的掌握度应该报 KeyError"""
        with self.assertRaises(KeyError):
            pick_difficulty("expert")


class TestComputeAnswer(unittest.TestCase):
    """测试程序计算答案（spec §7：不让 LLM 算）"""

    def test_two_real_roots(self):
        """x² - 5x + 6 = 0 → (x-2)(x-3) → x=2, x=3"""
        x1, x2 = compute_answer(1, -5, 6)
        self.assertEqual(x1, 3.0)
        self.assertEqual(x2, 2.0)

    def test_repeated_root(self):
        """x² - 4x + 4 = 0 → (x-2)² → x=2（重根）"""
        x1, x2 = compute_answer(1, -4, 4)
        self.assertEqual(x1, 2.0)
        self.assertEqual(x2, 2.0)

    def test_no_real_solution(self):
        """x² + 2x + 5 = 0 → 判别式 -16 < 0 → 无实数解"""
        with self.assertRaises(ValueError) as ctx:
            compute_answer(1, 2, 5)
        self.assertIn("无实数解", str(ctx.exception))

    def test_a_is_zero(self):
        """a=0 不是二次方程"""
        with self.assertRaises(ValueError) as ctx:
            compute_answer(0, 2, 3)
        self.assertIn("a 不能为 0", str(ctx.exception))

    def test_fractional_roots(self):
        """2x² + 3x - 2 = 0 → x = 0.5, x = -2"""
        x1, x2 = compute_answer(2, 3, -2)
        self.assertEqual(x1, 0.5)
        self.assertEqual(x2, -2.0)


class TestValidateParams(unittest.TestCase):
    """测试参数校验（spec §7：先校验再计算）"""

    def test_valid_params_returns_none(self):
        self.assertIsNone(validate_params(1, -5, 6))

    def test_a_zero_returns_error(self):
        result = validate_params(0, 2, 3)
        self.assertIsNotNone(result)
        self.assertIn("a 不能为 0", result)

    def test_no_solution_returns_error(self):
        result = validate_params(1, 2, 5)
        self.assertIsNotNone(result)
        self.assertIn("无实数解", result)


class TestExtractNumbers(unittest.TestCase):
    """数值提取：分数、负号、上标不误提取"""

    def test_plain_numbers(self):
        self.assertEqual(extract_numbers("x1=3, x2=2"), {3.0, 2.0})

    def test_fraction(self):
        self.assertEqual(extract_numbers("x = 1/2"), {0.5})

    def test_negative(self):
        self.assertEqual(extract_numbers("x = -3"), {-3.0})

    def test_superscript_not_extracted(self):
        # x² 的 ² 是 Unicode 上标不提取；"=0" 的 0 属于方程，会被提取为额外值
        self.assertEqual(extract_numbers("x²-5x+6=0"), {-5.0, 6.0, 0.0})

    def test_variable_subscripts_stripped(self):
        # x1/x2 的下标不是数值，剥掉后只剩真正的值
        self.assertEqual(extract_numbers("x1=3, x2=2"), {3.0, 2.0})
        self.assertEqual(extract_numbers("x₁=3.0, x₂=2.0"), {3.0, 2.0})

    def test_multi_character_subscript_stripped(self):
        # 连续下标必须整体剥掉，否则残留数字会污染根集合
        self.assertEqual(extract_numbers("x₁₂=3"), {3.0})

    def test_empty(self):
        self.assertEqual(extract_numbers(""), set())


class TestCheckIsCorrect(unittest.TestCase):
    """数值集合判对错：堵旧子串比对的假阳性/假阴性"""

    def test_both_roots_normal_keyboard(self):
        self.assertTrue(check_is_correct("x1=3, x2=2", [3.0, 2.0]))

    def test_swapped_order(self):
        self.assertTrue(check_is_correct("x1=2, x2=3", [3.0, 2.0]))

    def test_partial_answer_is_wrong(self):
        # 旧子串比对的假阳性：两根只答一个
        self.assertFalse(check_is_correct("3", [3.0, 2.0]))

    def test_wrong_value(self):
        self.assertFalse(check_is_correct("x1=3, x2=4", [3.0, 2.0]))

    def test_label_digit_not_counted_as_root(self):
        # "x2=4" 里的下标 2 不能冒充根 2
        self.assertFalse(check_is_correct("x1=3, x2=4", [3.0, 2.0]))

    def test_fraction_matches_decimal(self):
        self.assertTrue(check_is_correct("x = 1/2", [0.5]))

    def test_negative_root_needs_sign(self):
        self.assertTrue(check_is_correct("x = -3", [-3.0]))
        self.assertFalse(check_is_correct("x = 3", [-3.0]))

    def test_extra_process_numbers_ok(self):
        self.assertTrue(check_is_correct("x²-5x+6=0，所以 x=2 或 x=3", [3.0, 2.0]))

    def test_repeated_root(self):
        self.assertTrue(check_is_correct("x = 2", [2.0, 2.0]))

    def test_empty_answer(self):
        self.assertFalse(check_is_correct("", [3.0, 2.0]))
        self.assertFalse(check_is_correct("   ", [3.0, 2.0]))


class _FakeStructuredLLM:
    """离线替身：with_structured_output 返回固定 payload，不调真实 LLM"""

    def __init__(self, payload):
        self._payload = payload

    def with_structured_output(self, model, method=None):
        outer = self

        class _Stub:
            @staticmethod
            def invoke(prompt):
                return model(**outer._payload)

        return _Stub()


class TestGradeQuestionIntegration(unittest.TestCase):
    """grade_question 端到端（离线）：params 重算 + 数值判分"""

    QUESTION = {
        "id": "q-1",
        "kp_id": "39",
        "stem": "已知方程 x² - 5x + 6 = 0",
        "answer": "x₁=3.0, x₂=2.0",
        "params": {"a": 1.0, "b": -5.0, "c": 6.0},
    }

    AI_PAYLOAD = {
        "is_correct": True,
        "error_type": "无错",
        "confidence": 1.0,
        "evidence": "ok",
        "steps_analyzed": 1,
        "insufficient_evidence": False,
    }

    def _grade(self, student_result):
        return grade_question(
            dict(self.QUESTION),
            [{"basis": "求解", "result": student_result}],
            _FakeStructuredLLM(self.AI_PAYLOAD),
        )

    def test_partial_answer_rejected_even_if_ai_says_correct(self):
        # 子串时代这里会假阳性：AI 说对，程序必须推翻
        result = self._grade("3")
        self.assertFalse(result["is_correct"])

    def test_full_answer_accepted_normal_format(self):
        result = self._grade("x1=3, x2=2")
        self.assertTrue(result["is_correct"])


if __name__ == "__main__":
    unittest.main()
