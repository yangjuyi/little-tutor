"""Tests for the structured real-exam growth-rate solver."""

from __future__ import annotations

import unittest

from app.domain.exam.answer_equiv import equation_equivalent, numeric_equivalent
from app.domain.exam.registry import solve_exam_spec
from app.domain.exam.specs import GrowthRateSpec
from app.domain.exam.solvers import verify_growth_rate_result


class TestGrowthRateSolver(unittest.TestCase):
    def test_growth_rate_decimal_target(self):
        spec = GrowthRateSpec(initial=40, final=48.4, periods=2)
        result = solve_exam_spec(spec)
        self.assertEqual(result["answer"], "10%")
        self.assertTrue(
            verify_growth_rate_result(result, expected="10%", target="rate")
        )

    def test_decay_rate_uses_positive_percentage(self):
        spec = GrowthRateSpec(
            initial=48,
            final=27,
            periods=2,
            mode="decay",
        )
        result = solve_exam_spec(spec)
        self.assertEqual(result["answer"], "25%")

    def test_growth_rate_equation_target(self):
        spec = GrowthRateSpec(
            initial=670,
            final=780,
            periods=2,
            target="equation",
        )
        result = solve_exam_spec(spec)
        self.assertEqual(result["answer"], "670(1+x)^2=780")
        self.assertTrue(
            verify_growth_rate_result(
                result,
                expected="670*(1+x)**2=780",
                target="equation",
            )
        )

    def test_numeric_equivalence_accepts_percent_fraction_and_decimal(self):
        self.assertTrue(numeric_equivalent("20%", "1/5"))
        self.assertTrue(numeric_equivalent("10%", "0.1"))
        self.assertFalse(numeric_equivalent("25%", "0.2"))

    def test_equation_equivalence_normalizes_spacing_and_power(self):
        self.assertTrue(
            equation_equivalent(
                "670(1+x)²=780",
                "670*(1+x)**2 = 780",
            )
        )
        self.assertFalse(
            equation_equivalent(
                "670(1+x)=780",
                "670*(1+x)**2 = 780",
            )
        )

    def test_invalid_direction_is_rejected(self):
        with self.assertRaises(ValueError):
            GrowthRateSpec(initial=48, final=27, periods=2, mode="growth")


if __name__ == "__main__":
    unittest.main()
