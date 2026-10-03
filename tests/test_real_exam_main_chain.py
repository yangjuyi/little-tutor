"""Main-chain integration tests for structured real-exam questions."""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.adapters.persistence as db
import app.adapters.seed_catalog as seed_catalog
from app.application.student_practice import start_practice
from app.domain.assessment import get_question_handler
from app.domain.assessment.subquestions import (
    build_subquestion_results,
    combine_subquestion_results,
)
from app.adapters.real_exam_bank import (
    DEFAULT_BANK,
    DEFAULT_GROWTH_SPECS,
    load_growth_main_chain_questions,
    load_multipart_specs,
)
from app.domain.exam.main_chain import (
    check_structured_exam_answer,
    materialize_structured_exam,
)
from app.domain.answer_template import (
    breakpoint_label,
    build_template,
    judge_blanks,
)
from app.domain.question_materialization import materialize_question
from app.domain.assessment.elements import judge_block
from app.application.student_practice import _build_student_steps
from app.harness.hints import build_hint, build_scaffold


HAS_PRIVATE_BANK = DEFAULT_BANK.exists() and DEFAULT_GROWTH_SPECS.exists()


class TestRealExamMainChain(unittest.TestCase):
    def test_discriminant_choice_handler_uses_generic_pipeline(self):
        params = {
            "question_type": "discriminant_choice",
            "response_type": "multiple_choice",
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
        }
        handler = get_question_handler(params)
        self.assertIsNotNone(handler)
        self.assertEqual(handler.kind, "discriminant_choice")
        record = materialize_question({
            "stem": "下列方程中只有一个不同实数根的是（ ）。",
            "answer": "",
            "analysis": "",
            "params": params,
        })
        self.assertEqual(record["answer"], "B")
        template = handler.build_template(record["params"])
        self.assertEqual(template["blanks"][0]["option_labels"], ["A", "B", "C", "D"])
        self.assertTrue(judge_block(template["blanks"][0], "B"))
        self.assertTrue(judge_block(template["blanks"][0], "2"))
        self.assertFalse(judge_block(template["blanks"][0], "A"))
        self.assertTrue(handler.check_answer(record, "B"))
        self.assertFalse(handler.check_answer(record, "A"))

    def test_growth_rate_is_resolved_by_registered_handler(self):
        handler = get_question_handler({
            "question_type": "growth_rate",
            "exam_spec": {
                "type": "growth_rate",
                "initial": 100,
                "final": 121,
                "periods": 2,
            },
        })
        self.assertIsNotNone(handler)
        self.assertEqual(handler.kind, "growth_rate")

    @unittest.skipUnless(HAS_PRIVATE_BANK, "private real-exam bank unavailable")
    def test_growth_suite_loads_fifteen_questions(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        engine = create_engine(f"sqlite:///{tmp.name}")
        db.Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        try:
            with patch.object(seed_catalog, "SessionLocal", Session):
                added = seed_catalog.load_growth_real_exam_questions()
                added_again = seed_catalog.load_growth_real_exam_questions()
            self.assertEqual(added, 15)
            self.assertEqual(added_again, 0)
            with Session() as session:
                rows = session.query(db.Question).all()
            self.assertEqual(len(rows), 15)
            self.assertEqual(
                sum(
                    row.params.get("question_type") == "growth_application"
                    for row in rows
                ),
                2,
            )
            self.assertTrue(all(
                row.params.get("question_type")
                in ("growth_rate", "growth_application")
                for row in rows
            ))
        finally:
            engine.dispose()
            os.unlink(tmp.name)

    def test_equation_answer_uses_symbolic_equivalence(self):
        record = materialize_structured_exam({
            "stem": "某校绿化面积从1000平方米增长到1440平方米。",
            "params": {
                "question_type": "growth_rate",
                "target": "equation",
                "exam_spec": {
                    "type": "growth_rate",
                    "initial": 1000,
                    "final": 1440,
                    "periods": 2,
                    "mode": "growth",
                    "target": "equation",
                },
            },
        })
        self.assertEqual(record["answer"], "1000(1+x)^2=1440")
        self.assertTrue(check_structured_exam_answer(
            record, "1000*(1+x)**2 = 1440"
        ))
        self.assertFalse(check_structured_exam_answer(
            record, "1000(1+x)=1440"
        ))

    def test_rate_answer_accepts_percent_and_fraction(self):
        record = materialize_structured_exam({
            "stem": "某商品从40万元增长到48.4万元。",
            "params": {
                "question_type": "growth_rate",
                "target": "rate",
                "presentation": "stepwise",
                "exam_spec": {
                    "type": "growth_rate",
                    "initial": 40,
                    "final": 48.4,
                    "periods": 2,
                    "mode": "growth",
                    "target": "rate",
                },
            },
        })
        self.assertEqual(record["answer"], "10%")
        self.assertTrue(check_structured_exam_answer(record, "10%"))
        self.assertTrue(check_structured_exam_answer(record, "0.1"))
        self.assertTrue(check_structured_exam_answer(record, "1/10"))
        self.assertFalse(check_structured_exam_answer(record, "20%"))

    def test_growth_question_hints_do_not_require_quadratic_params(self):
        question = {
            "stem": "某商品连续两次降价。",
            "params": {
                "question_type": "growth_rate",
                "target": "rate",
                "presentation": "stepwise",
                "exam_spec": {
                    "type": "growth_rate",
                    "initial": 100,
                    "final": 81,
                    "periods": 2,
                    "mode": "decay",
                    "target": "rate",
                },
            },
        }
        self.assertTrue(build_hint(question, 1))
        self.assertTrue(build_hint(question, 3))
        self.assertTrue(build_scaffold(question, 1))
        self.assertTrue(build_scaffold(question, 2))

    def test_growth_practice_rejects_more_than_preapproved_pool_allows(self):
        with self.assertRaisesRegex(ValueError, "最多可选 7 题"):
            start_practice("1", "8", "一元二次方程增长率")

    def test_growth_template_locates_wrong_process_component(self):
        question = materialize_structured_exam({
            "stem": "某校绿化面积从1000平方米增长到1440平方米。",
            "params": {
                "question_type": "growth_rate",
                "target": "rate",
                "presentation": "stepwise",
                "exam_spec": {
                    "type": "growth_rate",
                    "initial": 1000,
                    "final": 1440,
                    "periods": 2,
                    "mode": "growth",
                    "target": "rate",
                },
            },
        })
        template = build_template(question["params"])
        self.assertEqual(template["final_answer_builder"], "growth_rate")
        steps = []
        for blank in template["blanks"]:
            if blank["kind"] == "choice":
                result = str(blank["answer_index"] + 1)
            elif blank["id"] == "b1":
                result = "999"
            else:
                result = f"{blank['expected']:g}"
            steps.append({"basis": blank["basis"], "result": result})
        checks = judge_blanks(template, steps)
        self.assertEqual(breakpoint_label(checks), "第 1 个作答项（题目中的初始量是多少？）")

    def test_multiple_choice_exam_keeps_original_options_and_labels(self):
        record = materialize_structured_exam({
            "stem": "下列关于增长率的方程中，正确的是（ ）。",
            "params": {
                "question_type": "growth_rate",
                "target": "equation",
                "response_type": "multiple_choice",
                "choices": [
                    "1000(1+x)=1440",
                    "1000(1+x)^2=1440",
                    "1000(1+2x)=1440",
                    "1000(1+x^2)=1440",
                ],
                "correct_choice": "B",
                "exam_spec": {
                    "type": "growth_rate",
                    "initial": 1000,
                    "final": 1440,
                    "periods": 2,
                    "mode": "growth",
                    "target": "equation",
                },
            },
        })
        template = build_template(record["params"])
        self.assertEqual(template["blanks"][0]["option_labels"], ["A", "B", "C", "D"])
        self.assertEqual(template["blanks"][0]["answer_index"], 1)
        _, steps = _build_student_steps(record, {"b1": "2"})
        self.assertEqual(steps[-1]["result"], "1000(1+x)^2=1440")
        self.assertTrue(check_structured_exam_answer(record, steps[-1]["result"]))

    def test_multipart_growth_application_runs_through_subquestions(self):
        item = load_multipart_specs()[0]
        params = {
            "question_type": "growth_application",
            "parts": item["parts"],
        }
        handler = get_question_handler(params)
        self.assertIsNotNone(handler)
        record = handler.materialize({
            "stem": "某商场四月份投入20万元，六月份投入24.2万元。",
            "params": params,
        })
        template = handler.build_template(record["params"])
        self.assertEqual(len(template["subquestions"]), 2)
        form = {}
        for blank in template["blanks"]:
            if blank["kind"] == "choice":
                form[blank["id"]] = str(blank["answer_index"] + 1)
            else:
                form[blank["id"]] = f"{blank['expected']:g}"
        template, steps = _build_student_steps(record, form)
        subquestion_results = build_subquestion_results(
            template,
            judge_blanks(template, steps),
        )
        self.assertTrue(combine_subquestion_results(subquestion_results))
        self.assertTrue(handler.check_answer(record, steps[-1]["result"]))


if __name__ == "__main__":
    unittest.main()
