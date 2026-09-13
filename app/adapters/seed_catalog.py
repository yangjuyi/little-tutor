"""种子题库入册（§16.1 决策③）。

种子题为 AI 原创题（JSON），答案一律由程序按 params 计算（spec §7 红线），
入库前按 B2 难度带校验，防止题库混入不受控难度。
"出题优先挑库"的选库逻辑由会话级图（C 阶段）的 H1 组卷预审实现。
"""

import json
from pathlib import Path

from app.adapters.persistence import KnowledgePoint, Question, SessionLocal, init_db
from app.domain.grading import validate_difficulty_params
from app.domain.question_materialization import materialize_question

DEFAULT_KP = "配方法解一元二次方程"
SEED_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "seed_questions.json"
PRIVATE_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "private_questions"
DEFAULT_KP_META = {
    "subject": "数学",
    "chapter": "一元二次方程",
    "concept": "通过配方将方程化为 (x+m)²=n 的形式求解",
}


def load_seed_questions(
    path: Path | None = None, kp_name: str | None = None,
    source: str = "ai_generated",
    curated: bool = False,
) -> int:
    """把种子题幂等入册（按题干去重），返回本次新增条数。

    Raises:
        ValueError: 种子题未通过难度带校验
    """
    if source not in ("ai_generated", "private"):
        raise ValueError(f"非法题目来源：{source}")
    seed_path = path or SEED_PATH
    payload = json.loads(seed_path.read_text(encoding="utf-8"))
    kp_name = payload.get("kp_name") or kp_name or DEFAULT_KP
    init_db()

    added = 0
    with SessionLocal() as s:
        kp = s.query(KnowledgePoint).filter_by(kp_name=kp_name).first()
        if kp is None:
            kp = KnowledgePoint(kp_name=kp_name, **DEFAULT_KP_META)
            s.add(kp)
            s.flush()
        existing = {stem for (stem,) in s.query(Question.stem).all()}
        for seed in payload["questions"]:
            a, b, c = (seed["params"][k] for k in ("a", "b", "c"))
            difficulty = seed["difficulty"]
            error = validate_difficulty_params(
                a, b, c, difficulty, seed.get("structure_tag", ""), curated=curated
            )
            if error:
                raise ValueError(f"种子题未通过难度带校验（{error}）：{seed['stem'][:30]}")
            materialized = materialize_question(
                seed,
                regenerate_analysis=True,
            )
            if seed["stem"] in existing:
                continue
            s.add(Question(
                kp_id=kp.id,
                stem=seed["stem"],
                answer=materialized["answer"],
                analysis=materialized["analysis"],
                difficulty=difficulty,
                source=source,
                params=materialized["params"],
            ))
            added += 1
        s.commit()
    return added


def load_private_questions() -> int:
    """加载私有题库目录全部 JSON（网摘/真题摘录，source=private）。

    私有目录被 .gitignore 隔离，绝不入仓库（版权红线：公开仓库只放 AI 原创题）。
    人工审核过：走 curated 校验（可解性红线），跳过 AI 尺寸护栏。
    """
    added = 0
    if PRIVATE_DIR.exists():
        for path in sorted(PRIVATE_DIR.glob("*.json")):
            added += load_seed_questions(path=path, source="private", curated=True)
    return added
