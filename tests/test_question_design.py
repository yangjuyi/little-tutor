"""程序化题目设计器测试：配方整洁性 + 情境化题型覆盖（离线）"""

import unittest

from app.domain.answer_template import build_template
from app.domain.grading import completion_cleanliness_error, validate_difficulty_params
from app.domain.question_design import build_designed_question


class TestQuestionDesign(unittest.TestCase):
    def test_all_designs_pass_quality_gate(self):
        for difficulty in ("simple", "mid", "hard"):
            for sequence in range(30):
                with self.subTest(difficulty=difficulty, sequence=sequence):
                    question = build_designed_question(difficulty, sequence)
                    params = question["params"]
                    self.assertIsNone(completion_cleanliness_error(
                        params["a"], params["b"], params["c"]
                    ))
                    self.assertIsNone(validate_difficulty_params(
                        params["a"], params["b"], params["c"],
                        difficulty, params.get("structure_tag", ""),
                    ))
                    self.assertTrue(params.get("design_id"))

    def test_context_designs_do_not_expose_random_raw_equation(self):
        stems = [
            build_designed_question("mid", sequence)["stem"]
            for sequence in range(12)
        ]
        self.assertTrue(any("菜地" in stem for stem in stems))
        self.assertTrue(any("根与系数关系" in stem for stem in stems))

    def test_hard_has_structural_tag(self):
        for sequence in range(12):
            question = build_designed_question("hard", sequence)
            self.assertIn(
                question["params"]["structure_tag"],
                ("建模", "根与系数", "多步化简"),
            )

    def test_first_step_and_choice_position_vary(self):
        prompts = set()
        positions = set()
        for difficulty in ("mid", "hard"):
            for sequence in range(12):
                question = build_designed_question(difficulty, sequence)
                template = build_template(question["params"])
                prompts.add(template["blanks"][0]["basis"])
                positions.add(template["blanks"][0]["answer_index"])
        self.assertGreaterEqual(len(prompts), 3)
        self.assertGreaterEqual(len(positions), 2)

    def test_rectangle_only_answers_positive_width(self):
        question = build_designed_question("mid", 0)
        self.assertEqual(question["params"]["design_id"], "rectangle")
        self.assertEqual(len(question["params"]["valid_roots"]), 1)
        self.assertGreater(question["params"]["valid_roots"][0], 0)
        self.assertTrue(question["answer"].startswith("x="))

    def test_consecutive_even_equation_matches_stem(self):
        question = next(
            build_designed_question("simple", sequence)
            for sequence in range(10)
            if build_designed_question("simple", sequence)["params"]["design_id"]
            == "consecutive_even"
        )
        params = question["params"]
        self.assertEqual(params["a"], 1)
        self.assertEqual(params["b"], 2)
        self.assertGreater(-params["c"], 0)

    def test_mid_and_hard_coefficients_are_balanced(self):
        for difficulty, expected_a in (
            ("mid", {2, 3, 4, 5}),
            ("hard", {2, 3, 4, 5, 6, 7}),
        ):
            questions = [
                build_designed_question(difficulty, sequence)
                for sequence in range(10)
            ]
            counts = {}
            for question in questions:
                a = question["params"]["a"]
                counts[a] = counts.get(a, 0) + 1
            self.assertEqual(set(counts), expected_a)
            self.assertLessEqual(max(counts.values()) - min(counts.values()), 1)

    def test_pool_offers_twenty_unique_questions(self):
        for difficulty in ("simple", "mid", "hard"):
            stems = {
                build_designed_question(difficulty, sequence)["stem"]
                for sequence in range(20)
            }
            self.assertEqual(len(stems), 20)


if __name__ == "__main__":
    unittest.main()
