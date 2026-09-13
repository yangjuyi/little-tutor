"""分级提示策略测试。"""

import unittest

from app.harness.hints import build_hint


class TestHintPolicy(unittest.TestCase):
    def test_hint_levels_do_not_reveal_final_answer(self):
        question = {
            "params": {
                "a": 1,
                "b": -6,
                "c": 8,
                "design_id": "direct",
            }
        }
        first = build_hint(question, 1)
        second = build_hint(question, 2)
        third = build_hint(question, 3)
        self.assertIn("整理", first)
        self.assertIn("先完成这一步", second)
        self.assertIn("检查符号", third)
        self.assertNotIn("x=2", " ".join((first, second, third)))
        self.assertNotIn("x=4", " ".join((first, second, third)))


if __name__ == "__main__":
    unittest.main()
