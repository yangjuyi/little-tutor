"""Infrastructure tests: prompt wiring, vocabulary separation, and LLM tasks."""

import os
import subprocess
import sys
import tempfile
import typing
import unittest
from pathlib import Path
from unittest.mock import patch

from app.adapters.llm import (
    _load_prompt,
    _render_prompt,
    _usage_summary,
    get_llm,
)
from app.application.student_practice import _parse_count
from app.domain.grading import (
    DIFFICULTY_RATIOS,
    pick_difficulty,
)
from app.domain.types import DifficultyLevel, Level


class TestPromptWiring(unittest.TestCase):
    """Versioned prompt files must stay loadable and parameterized."""

    def test_question_prompt_is_loadable(self):
        prompt = _load_prompt("question_gen_v1.md")
        self.assertIn("{kp_name}", prompt)
        self.assertIn("{difficulty}", prompt)
        self.assertIn("## Output Format", prompt)

    def test_grader_prompt_is_loadable(self):
        prompt = _load_prompt("grader_v1.md")
        self.assertIn("{stem}", prompt)
        self.assertIn("{answer}", prompt)
        self.assertIn("{program_facts_json}", prompt)
        self.assertIn("{steps_json}", prompt)
        self.assertIn("DATA", prompt)
        self.assertIn("INSTRUCTION", prompt)
        self.assertNotIn('"is_correct"', prompt)

    def test_render_prompt_preserves_json_braces(self):
        rendered = _render_prompt(
            "hello {name}, output {\"a\": 1}",
            {"name": "world"},
        )
        self.assertEqual(rendered, "hello world, output {\"a\": 1}")


class TestVocabularySeparation(unittest.TestCase):
    """Question difficulty and mastery level are different domains."""

    def test_difficulty_and_mastery_literals_are_independent(self):
        self.assertEqual(
            typing.get_args(DifficultyLevel),
            ("simple", "mid", "hard"),
        )
        self.assertEqual(
            typing.get_args(Level),
            ("weak", "mid", "strong"),
        )

    def test_difficulty_ratios_use_difficulty_vocabulary(self):
        for ratios in DIFFICULTY_RATIOS.values():
            self.assertLessEqual(
                set(ratio for ratio, _ in ratios),
                set(typing.get_args(DifficultyLevel)),
            )

    def test_pick_difficulty_stays_in_difficulty_domain(self):
        for mastery in typing.get_args(Level):
            self.assertIn(pick_difficulty(mastery), typing.get_args(DifficultyLevel))


class TestLlmTaskSelection(unittest.TestCase):
    """Task-specific LLM settings must reject unknown tasks."""

    def test_unknown_task_is_rejected(self):
        with self.assertRaises(ValueError):
            get_llm("unknown")

    def test_usage_summary_tracks_tokens_and_optional_cost(self):
        usage = {
            "model-a": {
                "input_tokens": 1000,
                "output_tokens": 500,
            }
        }
        with patch.dict(
            os.environ,
            {
                "TUTOR_LLM_INPUT_COST_PER_1M": "2",
                "TUTOR_LLM_OUTPUT_COST_PER_1M": "8",
            },
            clear=False,
        ):
            summary = _usage_summary(usage)
        self.assertEqual(summary["input_tokens"], 1000)
        self.assertEqual(summary["output_tokens"], 500)
        self.assertEqual(summary["total_tokens"], 1500)
        self.assertEqual(summary["estimated_cost"], 0.006)


class TestRuntimeIsolation(unittest.TestCase):
    """Manual smoke runs must be able to redirect DB and checkpoint paths."""

    def test_db_and_checkpoint_env_overrides(self):
        project_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as temp_dir:
            db_path = Path(temp_dir) / "test.db"
            checkpoint_path = Path(temp_dir) / "checkpoints.db"
            env = os.environ.copy()
            env["TUTOR_DB_PATH"] = str(db_path)
            env["TUTOR_CHECKPOINT_PATH"] = str(checkpoint_path)
            code = (
                "import app.adapters.persistence as db; "
                "import app.adapters.checkpoint as cp; "
                "print(db.DATABASE_PATH); print(cp.CHECKPOINT_DB)"
            )
            result = subprocess.run(
                [sys.executable, "-c", code],
                cwd=project_root,
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )
            self.assertEqual(
                result.stdout.strip().splitlines(),
                [str(db_path), str(checkpoint_path)],
            )


class TestQuestionCountParsing(unittest.TestCase):
    """题量必须是 1-30 的整数，空值按默认 10 处理。"""

    def test_default_and_boundary_counts(self):
        self.assertEqual(_parse_count(""), 10)
        self.assertEqual(_parse_count(" 4 "), 4)
        self.assertEqual(_parse_count("1"), 1)
        self.assertEqual(_parse_count("30"), 30)

    def test_invalid_counts_are_rejected(self):
        for raw in ("-1", "0", "abc", "1.5", "31"):
            with self.subTest(raw=raw):
                with self.assertRaises(ValueError):
                    _parse_count(raw)


if __name__ == "__main__":
    unittest.main()
