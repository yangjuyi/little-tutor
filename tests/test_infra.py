"""Infrastructure tests: prompt wiring, vocabulary separation, and LLM tasks."""

import os
import subprocess
import sys
import tempfile
import typing
import unittest
from pathlib import Path

from app.adapters.llm import (
    _load_prompt,
    _render_prompt,
    get_llm,
)
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
        self.assertIn("{steps}", prompt)

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


if __name__ == "__main__":
    unittest.main()
