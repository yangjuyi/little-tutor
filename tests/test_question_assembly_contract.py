"""Contract tests for plan/generated assembly."""

import unittest

from app.harness.question_assembly import check_assemble_node


def _question(index: int) -> dict:
    return {
        "id": index,
        "kp_id": "1",
        "difficulty": "simple",
        "stem": f"question-{index}",
        "answer": "x=1",
        "analysis": "",
        "images": [],
        "source": "ai_generated",
        "params": {"a": 1, "b": -2, "c": 1},
    }


class TestQuestionAssemblyContract(unittest.TestCase):
    def test_generated_updates_are_ordered_by_plan_index(self):
        state = {
            "plan_id": 7,
            "plan": [
                {"index": 0, "seed": _question(0)},
                {"index": 1, "seed": None},
                {"index": 2, "seed": None},
            ],
            "generated": [
                {
                    "plan_id": 7,
                    "index": 2,
                    "question": _question(2),
                },
                {
                    "plan_id": 7,
                    "index": 1,
                    "question": _question(1),
                },
            ],
        }
        result = check_assemble_node(state)
        self.assertNotIn("llm_error", result)
        self.assertEqual(
            [question["stem"] for question in result["candidates"]],
            ["question-0", "question-1", "question-2"],
        )

    def test_missing_generated_index_returns_llm_error(self):
        state = {
            "plan_id": 1,
            "plan": [
                {"index": 0, "seed": None},
                {"index": 1, "seed": None},
            ],
            "generated": [
                {
                    "plan_id": 1,
                    "index": 0,
                    "question": _question(0),
                },
            ],
        }
        result = check_assemble_node(state)
        self.assertIn("缺少计划索引", result["llm_error"])

    def test_duplicate_generated_index_returns_llm_error(self):
        state = {
            "plan_id": 1,
            "plan": [
                {"index": 0, "seed": None},
            ],
            "generated": [
                {
                    "plan_id": 1,
                    "index": 0,
                    "question": _question(0),
                },
                {
                    "plan_id": 1,
                    "index": 0,
                    "question": _question(1),
                },
            ],
        }
        result = check_assemble_node(state)
        self.assertIn("重复索引", result["llm_error"])


if __name__ == "__main__":
    unittest.main()
