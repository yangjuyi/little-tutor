"""Tests for the minimal error-type to training-focus bridge."""

from __future__ import annotations

import unittest

from app.domain.teaching_plan import (
    build_teaching_plan,
    build_training_focus,
    question_training_tags,
    rank_questions_for_focus,
)
from app.domain.question_design import build_designed_question
from app.harness.session_graph import collect_round_node


class TestTeachingPlan(unittest.TestCase):
    def test_error_type_maps_to_focus(self):
        focus = build_training_focus("计算", "direct")
        self.assertEqual(focus["error_type"], "计算")
        self.assertIn("calculation", focus["tags"])
        self.assertTrue(focus["provisional"])

    def test_question_tags_fall_back_to_design_family(self):
        tags = question_training_tags({
            "params": {"design_id": "multi_step"}
        })
        self.assertIn("process", tags)
        self.assertIn("multi_step", tags)

    def test_designed_question_carries_explicit_training_tags(self):
        question = build_designed_question("simple", sequence=0)
        self.assertTrue(question["params"].get("training_tags"))

    def test_teaching_plan_is_minimal_and_pending_review(self):
        plan = build_teaching_plan(
            build_training_focus("计算", "direct")
        )
        self.assertIn("计算稳定性", plan["target_skill"])
        self.assertEqual(plan["recommended_question_count"], 2)
        self.assertEqual(plan["teacher_review_status"], "pending")
        self.assertTrue(plan["needs_verification"])

    def test_focus_ranks_matching_questions_first(self):
        questions = [
            {"id": 1, "params": {"design_id": "direct"}},
            {"id": 2, "params": {"design_id": "multi_step"}},
        ]
        ranked = rank_questions_for_focus(
            questions,
            build_training_focus("跳步", "multi_step"),
        )
        self.assertEqual([q["id"] for q in ranked], [2, 1])

    def test_missing_focus_preserves_original_order(self):
        questions = [
            {"id": 1, "params": {"design_id": "direct"}},
            {"id": 2, "params": {"design_id": "multi_step"}},
        ]
        self.assertEqual(
            rank_questions_for_focus(questions, None),
            questions,
        )

    def test_empty_source_design_does_not_break_ranking(self):
        questions = [
            {"id": 1, "params": {"design_id": "direct"}},
            {"id": 2, "params": {"design_id": "multi_step"}},
        ]
        ranked = rank_questions_for_focus(
            questions,
            {
                "tags": ["calculation"],
                "source_design_id": "",
            },
        )
        self.assertEqual([q["id"] for q in ranked], [1, 2])

    def test_collect_round_uses_error_focus_for_next_question(self):
        current = {
            "id": 1,
            "difficulty": "mid",
            "params": {"design_id": "direct"},
        }
        preferred = {
            "id": 2,
            "difficulty": "mid",
            "params": {"design_id": "multi_step"},
        }
        other = {
            "id": 3,
            "difficulty": "mid",
            "params": {"design_id": "direct"},
        }
        result = {
            "is_correct": False,
            "difficulty": "mid",
            "assistance_level": "independent",
            "error": {"error_type": "跳步"},
        }
        update = collect_round_node({
            "round_results": [],
            "result": result,
            "approved_questions": [current],
            "approved_pool": [current, preferred, other],
            "question_count": 2,
            "adaptive_target": "mid",
            "current_question": current,
            "training_focus": None,
            "focus_remaining": 0,
        })
        self.assertEqual(update["training_focus"]["error_type"], "跳步")
        self.assertEqual(update["focus_remaining"], 2)
        self.assertEqual(update["approved_questions"][-1]["id"], 2)


if __name__ == "__main__":
    unittest.main()
