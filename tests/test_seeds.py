"""种子题库入册测试：幂等加载 + 难度带校验 + 程序算答案（离线，临时库）"""

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app.domain.grading import compute_answer, validate_difficulty_params

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.adapters.persistence as db
import app.adapters.seed_catalog as seeds
from app.domain.grading import compute_answer


SEEDS = {
    "kp_name": "配方法解一元二次方程",
    "questions": [
        {
            "stem": "解方程 x² - 6x + 8 = 0，求 x 的全部值。",
            "params": {"a": 1, "b": -6, "c": 8, "design_id": "direct"},
            "difficulty": "simple",
            "structure_tag": "",
            "analysis": "解析一",
        },
        {
            "stem": "解方程 2x² - 8x + 6 = 0，求 x 的全部值。",
            "params": {"a": 2, "b": -8, "c": 6, "design_id": "direct"},
            "difficulty": "mid",
            "structure_tag": "",
            "analysis": "解析二",
        },
        {
            "stem": (
                "解方程 3x² - 12x + 9 = 0。"
                "先观察系数并化简，再求 x 的全部值。"
            ),
            "params": {
                "a": 3,
                "b": -12,
                "c": 9,
                "design_id": "multi_step",
            },
            "difficulty": "hard",
            "structure_tag": "多步化简",
            "analysis": "解析三",
        },
    ],
}


class TestSeedQuestions(unittest.TestCase):
    """load_seed_questions：幂等 + 校验 + 答案程序算"""

    def test_seed_file_audit(self):
        """种子文件全量审计：难度带合法、答案复算一致、题干唯一（用户实测教训）"""
        payload = json.loads(seeds.SEED_PATH.read_text(encoding="utf-8"))
        stems = set()
        for seed in payload["questions"]:
            p = seed["params"]
            error = validate_difficulty_params(
                p["a"], p["b"], p["c"], seed["difficulty"], seed.get("structure_tag", "")
            )
            self.assertIsNone(error, seed["stem"])
            x1, x2 = compute_answer(p["a"], p["b"], p["c"])
            # 两根必须为有限数值（可手解、可判分）
            self.assertTrue(all(abs(root) < 1000 for root in (x1, x2)), seed["stem"])
            self.assertNotIn(seed["stem"], stems)
            stems.add(seed["stem"])
        self.assertGreaterEqual(len(stems), 9)

    def setUp(self):
        tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        tmp.close()
        self.db_path = tmp.name
        engine = create_engine(
            f"sqlite:///{self.db_path}",
            connect_args={"check_same_thread": False},
        )
        self.engine = engine
        db.Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        self.session = Session
        self._patch = patch.object(seeds, "SessionLocal", Session)
        self._patch.start()
        self.seed_file = None
        with Session() as s:
            s.add(db.KnowledgePoint(
                subject="数学", chapter="一元二次方程",
                kp_name="配方法解一元二次方程", concept="c",
            ))
            s.commit()

    def tearDown(self):
        self._patch.stop()
        self.engine.dispose()
        os.unlink(self.db_path)
        if self.seed_file:
            os.unlink(self.seed_file)

    def _write_seeds(self, payload) -> Path:
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        )
        json.dump(payload, tmp, ensure_ascii=False)
        tmp.close()
        self.seed_file = tmp.name
        return Path(tmp.name)

    def test_loads_and_computes_answers(self):
        path = self._write_seeds(SEEDS)
        added = seeds.load_seed_questions(path=path)
        self.assertEqual(added, 3)
        with self.session() as s:
            rows = s.query(db.Question).all()
            by_stem = {r.stem: r for r in rows}
            self.assertEqual(
                by_stem[SEEDS["questions"][0]["stem"]].answer,
                "x₁=4, x₂=2",
            )
            self.assertEqual(
                by_stem[SEEDS["questions"][0]["stem"]].difficulty,
                "simple",
            )
            self.assertEqual(
                by_stem[SEEDS["questions"][2]["stem"]].difficulty,
                "hard",
            )
            self.assertEqual(
                by_stem[SEEDS["questions"][1]["stem"]].source,
                "ai_generated",
            )

    def test_reload_is_idempotent(self):
        path = self._write_seeds(SEEDS)
        seeds.load_seed_questions(path=path)
        self.assertEqual(seeds.load_seed_questions(path=path), 0)

    def test_invalid_seed_rejected(self):
        bad = json.loads(json.dumps(SEEDS))
        bad["questions"][0]["params"] = {"a": 2, "b": -7, "c": 3}
        path = self._write_seeds(bad)
        with self.assertRaises(ValueError) as ctx:
            seeds.load_seed_questions(path=path)
        self.assertIn("难度带校验", str(ctx.exception))

    def test_curated_question_infers_missing_design_id(self):
        payload = json.loads(json.dumps(SEEDS))
        payload["questions"] = [payload["questions"][0]]
        del payload["questions"][0]["params"]["design_id"]
        path = self._write_seeds(payload)
        self.assertEqual(
            seeds.load_seed_questions(path=path, curated=True), 1
        )
        with self.session() as s:
            row = s.query(db.Question).one()
            self.assertEqual(row.params["design_id"], "direct")

    def test_missing_kp_autocreated(self):
        path = self._write_seeds({"kp_name": "新知识点", "questions": []})
        seeds.load_seed_questions(path=path)
        with self.session() as s:
            kp = s.query(db.KnowledgePoint).filter_by(kp_name="新知识点").one()
            self.assertEqual(kp.subject, "数学")


if __name__ == "__main__":
    unittest.main()
