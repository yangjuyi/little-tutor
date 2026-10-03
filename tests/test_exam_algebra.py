"""Tests for structured real-exam algebra solvers."""

from __future__ import annotations

import unittest

from app.domain.exam.registry import solve_exam_spec
from app.domain.exam.main_chain import (
    check_structured_exam_answer,
    materialize_structured_exam,
)
from app.domain.exam.specs import (
    DiscriminantChoiceSpec,
    ExpressionFromRootSpec,
    QuadraticRootsSpec,
    RootParameterSpec,
    RootReconstructionSpec,
)


class TestExamAlgebraSolvers(unittest.TestCase):
    def test_discriminant_choice_finds_double_root(self):
        result = solve_exam_spec(DiscriminantChoiceSpec(
            choices={
                "A": "(x-2)^2=-1",
                "B": "(x-2)^2=0",
                "C": "(x-2)^2=1",
                "D": "(x-2)^2=2",
            },
            select="one_distinct",
        ))
        self.assertEqual(result["answer"], ["B"])

    def test_root_reconstruction_builds_original_equation(self):
        result = solve_exam_spec(RootReconstructionSpec(
            root_sum=7,
            root_product=10,
        ))
        self.assertEqual(result["answer"], "1*x**2-7*x+10=0")

    def test_root_parameter_enforces_nonzero_leading_coefficient(self):
        result = solve_exam_spec(RootParameterSpec(
            equation="(a+2)*x^2+2*x+a^2-4=0",
            root_assignment="x=0",
            parameter="a",
            leading_expression="a+2",
        ))
        self.assertEqual(result["answer"], ["a=2"])

    def test_expression_from_root_uses_polynomial_remainder(self):
        result = solve_exam_spec(ExpressionFromRootSpec(
            equation="m^2+4*m-1=0",
            root_symbol="m",
            target_expression="(m+5)*(m-1)",
        ))
        self.assertEqual(result["answer"], "-4")

    def test_quadratic_roots_support_irrational_positive_root(self):
        result = solve_exam_spec(QuadraticRootsSpec(
            equation="a^2-2*a-1=0",
            unknown="a",
            root_filter="positive",
        ))
        self.assertEqual(result["answer"], ["1 + sqrt(2)"])

    def test_generic_main_chain_supports_non_growth_specs(self):
        question = materialize_structured_exam({
            "stem": "下列方程中只有一个不同实数根的是（ ）。",
            "params": {
                "question_type": "discriminant_choice",
                "exam_spec": {
                    "type": "discriminant_choice",
                    "choices": {
                        "A": "(x-2)^2=-1",
                        "B": "(x-2)^2=0",
                        "C": "(x-2)^2=1",
                        "D": "(x-2)^2=2",
                    },
                    "select": "one_distinct",
                },
            },
        })
        self.assertEqual(question["answer"], "B")
        self.assertTrue(check_structured_exam_answer(question, "B"))
        self.assertTrue(check_structured_exam_answer(question, "2"))
        self.assertFalse(check_structured_exam_answer(question, "A"))

    def test_generic_main_chain_checks_root_reconstruction(self):
        question = materialize_structured_exam({
            "stem": "已知方程两根之和为7、积为10，求原方程。",
            "params": {
                "question_type": "root_reconstruction",
                "exam_spec": {
                    "type": "root_reconstruction",
                    "root_sum": 7,
                    "root_product": 10,
                },
            },
        })
        self.assertTrue(
            check_structured_exam_answer(question, "x^2-7x+10=0")
        )
        self.assertFalse(
            check_structured_exam_answer(question, "x^2+7x+10=0")
        )

    def test_generic_main_chain_checks_parameter_and_expression(self):
        parameter_question = materialize_structured_exam({
            "stem": "求参数。",
            "params": {
                "question_type": "root_parameter",
                "exam_spec": {
                    "type": "root_parameter",
                    "equation": "(a+2)*x^2+2*x+a^2-4=0",
                    "root_assignment": "x=0",
                    "parameter": "a",
                    "leading_expression": "a+2",
                },
            },
        })
        self.assertTrue(
            check_structured_exam_answer(parameter_question, "a=2")
        )
        self.assertFalse(
            check_structured_exam_answer(parameter_question, "a=-2")
        )
        expression_question = materialize_structured_exam({
            "stem": "求代数式的值。",
            "params": {
                "question_type": "expression_from_root",
                "exam_spec": {
                    "type": "expression_from_root",
                    "equation": "m^2+4*m-1=0",
                    "root_symbol": "m",
                    "target_expression": "(m+5)*(m-1)",
                },
            },
        })
        self.assertTrue(
            check_structured_exam_answer(expression_question, "-4")
        )

    def test_generic_main_chain_checks_symbolic_roots(self):
        question = materialize_structured_exam({
            "stem": "求正根。",
            "params": {
                "question_type": "quadratic_roots",
                "exam_spec": {
                    "type": "quadratic_roots",
                    "equation": "a^2-2*a-1=0",
                    "unknown": "a",
                    "root_filter": "positive",
                },
            },
        })
        self.assertTrue(
            check_structured_exam_answer(question, "a=1+sqrt(2)")
        )
        self.assertFalse(
            check_structured_exam_answer(question, "a=1")
        )


if __name__ == "__main__":
    unittest.main()
