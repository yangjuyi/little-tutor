"""Tests for the private exam-corpus classifier."""

from __future__ import annotations

import unittest

from evals.audit_shijuan1_corpus import (
    _architecture_requirements,
    _classify_families,
)


class TestShijuan1CorpusAudit(unittest.TestCase):
    def test_compound_growth_is_detected(self):
        families = _classify_families(
            "某商品连续两次降价，设月平均增长率为x，则可列方程。"
        )
        self.assertIn("growth_rate", families)

    def test_statistics_growth_percentage_is_not_compound_growth(self):
        families = _classify_families(
            "比较两个班的成绩，并计算15分以上人数的增长百分率。"
        )
        self.assertNotIn("growth_rate", families)

    def test_profit_requires_profit_and_sales_context(self):
        self.assertIn(
            "profit_sales",
            _classify_families("每件进价40元，售价60元，求每天利润。"),
        )
        self.assertNotIn(
            "profit_sales",
            _classify_families("某商品的售价为60元。"),
        )

    def test_generic_range_is_not_discriminant(self):
        families = _classify_families(
            "一次函数中x的取值范围是全体实数。"
        )
        self.assertNotIn("discriminant_parameter", families)

    def test_explicit_discriminant_is_detected(self):
        families = _classify_families(
            "关于x的一元二次方程有两个不相等的实数根，求m的取值范围。"
        )
        self.assertIn("discriminant_parameter", families)

    def test_function_area_is_not_geometry_modeling(self):
        families = _classify_families(
            "二次函数的图象与坐标轴交于A、B，求三角形OAB的面积。"
        )
        self.assertNotIn("geometry_area", families)

    def test_rectangle_area_is_geometry_modeling(self):
        families = _classify_families(
            "用篱笆围成一个矩形花圃，已知长为x米，求面积。"
        )
        self.assertIn("geometry_area", families)

    def test_multi_label_question_keeps_all_architecture_requirements(self):
        requirements = _architecture_requirements({
            "growth_rate",
            "profit_sales",
            "geometry_area",
        })
        self.assertEqual(
            requirements,
            ["current_handler", "next_handler", "geometry_model"],
        )


if __name__ == "__main__":
    unittest.main()
