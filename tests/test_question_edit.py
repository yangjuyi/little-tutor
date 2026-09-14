"""老师改题后的程序重算测试。"""

import unittest

from app.domain.question_edit import recompute_edited_question


class TestQuestionEdit(unittest.TestCase):
    def test_edit_recomputes_answer_analysis_and_valid_roots(self):
        question = {
            "id": 1,
            "difficulty": "simple",
            "stem": "旧题干",
            "answer": "旧答案",
            "analysis": "旧解析",
            "params": {
                "a": 1,
                "b": 4,
                "c": -21,
                "design_id": "rectangle",
                "structure_tag": "",
                "valid_roots": [3],
            },
        }
        edited = recompute_edited_question(
            question,
            stem=(
                "一块长方形菜地的宽为 x 米，长比宽多 4 米，"
                "面积为 12 平方米。求这块菜地的宽。"
            ),
            a=1,
            b=4,
            c=-12,
            structure_tag="",
        )
        self.assertEqual(edited["params"]["c"], -12)
        self.assertEqual(edited["params"]["valid_roots"], [2])
        self.assertEqual(edited["answer"], "x=2")
        self.assertEqual(
            edited["params"]["semantic_validation"]["status"], "verified"
        )
        self.assertEqual(
            edited["params"]["stem_contract"]["area"], 12.0
        )
        self.assertIn("程序计算有效解", edited["analysis"])

    def test_semantic_conflict_is_rejected(self):
        question = {
            "id": 1,
            "difficulty": "simple",
            "stem": "旧题干",
            "answer": "旧答案",
            "analysis": "旧解析",
            "params": {
                "a": 1,
                "b": 4,
                "c": -21,
                "design_id": "rectangle",
                "structure_tag": "",
            },
        }
        with self.assertRaisesRegex(ValueError, "面积不一致"):
            recompute_edited_question(
                question,
                stem=(
                    "一块长方形菜地的宽为 x 米，长比宽多 4 米，"
                    "面积为 12 平方米。求这块菜地的宽。"
                ),
                a=1,
                b=4,
                c=-21,
            )

    def test_direct_stem_must_match_equation_coefficients(self):
        question = {
            "id": 1,
            "difficulty": "simple",
            "stem": "旧题干",
            "answer": "旧答案",
            "analysis": "旧解析",
            "params": {
                "a": 1,
                "b": -6,
                "c": 8,
                "design_id": "direct",
                "structure_tag": "",
            },
        }
        edited = recompute_edited_question(
            question,
            stem="解方程 x² - 6x + 8 = 0，求 x 的全部值。",
            a=1,
            b=-6,
            c=8,
        )
        self.assertEqual(edited["params"]["stem_contract"]["equation_c"], 8.0)

        with self.assertRaisesRegex(ValueError, "常数项不一致"):
            recompute_edited_question(
                question,
                stem="解方程 x² - 6x + 8 = 0，求 x 的全部值。",
                a=1,
                b=-6,
                c=9,
            )

    def test_root_relation_accepts_sum_product_form(self):
        question = {
            "id": 1,
            "difficulty": "mid",
            "stem": "旧题干",
            "answer": "旧答案",
            "analysis": "旧解析",
            "params": {
                "a": 2,
                "b": -12,
                "c": 16,
                "design_id": "root_relation",
                "structure_tag": "",
            },
        }
        edited = recompute_edited_question(
            question,
            stem=(
                "已知一个一元二次方程的两个根的和为 6，积为 8，"
                "且二次项系数为 2。请写出这个方程并求它的两个根。"
            ),
            a=2,
            b=-12,
            c=16,
        )
        self.assertEqual(
            edited["params"]["stem_contract"]["root_sum"], 6.0
        )

    def test_invalid_edit_is_rejected(self):
        question = {
            "id": 1,
            "difficulty": "simple",
            "stem": "旧题干",
            "answer": "旧答案",
            "analysis": "旧解析",
            "params": {
                "a": 1,
                "b": 4,
                "c": -21,
                "design_id": "rectangle",
                "structure_tag": "",
            },
        }
        with self.assertRaises(ValueError):
            recompute_edited_question(
                question,
                stem="无效题目",
                a=0,
                b=4,
                c=-21,
            )

    def test_integral_coefficients_are_stored_as_integers(self):
        question = {
            "id": 1,
            "difficulty": "simple",
            "stem": "旧题干",
            "answer": "旧答案",
            "analysis": "旧解析",
            "params": {
                "a": 1,
                "b": 4,
                "c": -21,
                "design_id": "rectangle",
                "structure_tag": "",
            },
        }
        edited = recompute_edited_question(
            question,
            stem=(
                "一块长方形菜地的宽为 x 米，长比宽多 4 米，"
                "面积为 12 平方米。求这块菜地的宽。"
            ),
            a="1",
            b="4.0",
            c="-12.0",
        )
        self.assertIsInstance(edited["params"]["a"], int)
        self.assertIsInstance(edited["params"]["b"], int)
        self.assertIsInstance(edited["params"]["c"], int)
        self.assertEqual(edited["params"]["a"], 1)
        self.assertEqual(edited["params"]["b"], 4)
        self.assertEqual(edited["params"]["c"], -12)

    def test_non_numeric_coefficient_is_rejected(self):
        question = {
            "id": 1,
            "difficulty": "simple",
            "stem": "旧题干",
            "answer": "旧答案",
            "analysis": "旧解析",
            "params": {
                "a": 1,
                "b": 4,
                "c": -21,
                "design_id": "rectangle",
                "structure_tag": "",
            },
        }
        with self.assertRaisesRegex(ValueError, "a 必须是数字"):
            recompute_edited_question(
                question,
                stem="一块长方形菜地的宽为 x 米，长比宽多 4 米，面积为 12 平方米。求这块菜地的宽。",
                a="abc",
                b="4",
                c="-12",
            )


if __name__ == "__main__":
    unittest.main()
