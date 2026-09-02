"""Unit tests for agents.py (program layer only, no LLM calls).

Run with: .venv/Scripts/python -m unittest tests.test_agents -v
"""

import unittest
from collections import Counter

from app.agents import pick_difficulty, compute_answer, validate_params


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


if __name__ == "__main__":
    unittest.main()
