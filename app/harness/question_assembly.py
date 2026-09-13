"""会话组卷、候选物化与题干去重。"""

from __future__ import annotations

import random

from langgraph.types import Command, Send

from app.adapters.persistence import Question as QuestionRow, SessionLocal
from app.adapters.session_store import start_practice_session
from app.domain.adaptation import allocate_difficulty_counts
from app.domain.grading import (
    DIFFICULTY_RATIOS,
    completion_cleanliness_error,
    pick_difficulty,
)
from app.domain.question_design import build_designed_question
from app.domain.question_materialization import materialize_question
from app.harness.state import SessionState


INTENT_BIAS = (
    (("简单", "容易", "基础"), {"simple": 0.8, "mid": 0.2, "hard": 0.0}),
    (("难", "拔高", "挑战"), {"simple": 0.1, "mid": 0.4, "hard": 0.5}),
)


def parse_intent_bias(intent: str | None) -> dict | None:
    """老师重组意图 → 难度配比；未命中关键词返回 None。"""
    text = (intent or "").strip()
    if not text:
        return None
    if any(k in text for k in ("全出", "全部", "都出", "只要", "全用")):
        if "难" in text:
            return {"hard": 1.0}
        if "简单" in text or "容易" in text:
            return {"simple": 1.0}
        if "中" in text:
            return {"mid": 1.0}
    for keywords, ratios in INTENT_BIAS:
        if any(k in text for k in keywords):
            return ratios
    return None


def parse_ratio_instruction(arg: str | None) -> dict | None:
    """显式比例指令（70/20/10）→ 难度配比。"""
    parts = (arg or "").strip().split("/")
    if len(parts) != 3:
        return None
    try:
        nums = [int(part) for part in parts]
    except ValueError:
        return None
    if any(num < 0 or num > 100 for num in nums) or sum(nums) != 100:
        return None
    return {
        "simple": nums[0] / 100,
        "mid": nums[1] / 100,
        "hard": nums[2] / 100,
    }


def _pick_with_bias(level: str, bias: dict | None) -> str:
    if bias:
        return random.choices(list(bias), weights=list(bias.values()), k=1)[0]
    return pick_difficulty(level)


def seed_candidate(row: QuestionRow, kp_id: str) -> dict:
    """把题库记录物化为当前题干契约下的候选题目。"""
    materialized = materialize_question(
        {
            "stem": row.stem,
            "answer": row.answer,
            "analysis": row.analysis,
            "params": dict(row.params or {}),
        },
        regenerate_analysis=True,
    )
    if (
        row.answer != materialized["answer"]
        or row.analysis != materialized["analysis"]
        or dict(row.params or {}) != materialized["params"]
    ):
        with SessionLocal() as s:
            persisted = s.get(QuestionRow, row.id)
            if persisted is not None:
                persisted.answer = materialized["answer"]
                persisted.analysis = materialized["analysis"]
                persisted.params = materialized["params"]
                s.commit()
    return {
        "id": row.id,
        "kp_id": kp_id,
        "dep_kp_ids": [],
        "difficulty": row.difficulty,
        "stem": row.stem,
        "answer": materialized["answer"],
        "analysis": materialized["analysis"],
        "images": [],
        "source": row.source,
        "params": materialized["params"],
    }


def is_selectable_seed(row: QuestionRow) -> bool:
    """题库质量闸门：拒绝旧题、脏参数和无法物化的题。"""
    params = dict(row.params or {})
    try:
        a, b, c = float(params["a"]), float(params["b"]), float(params["c"])
    except (KeyError, TypeError, ValueError):
        return False
    if completion_cleanliness_error(a, b, c):
        return False
    if row.source == "ai_generated" and not params.get("design_id"):
        return False
    try:
        materialize_question({
            "stem": row.stem,
            "answer": row.answer,
            "analysis": row.analysis,
            "params": params,
        })
    except ValueError:
        return False
    return True


def persist_ai_question(question: dict, kp_id: str) -> None:
    """落库 AI 题并换真实主键。"""
    materialized = materialize_question(question)
    with SessionLocal() as s:
        row = QuestionRow(
            kp_id=int(kp_id),
            stem=materialized["stem"],
            answer=materialized["answer"],
            analysis=materialized.get("analysis"),
            difficulty=materialized.get("difficulty", "simple"),
            source="ai_generated",
            params=materialized.get("params"),
        )
        s.add(row)
        s.commit()
        question.clear()
        question.update(materialized)
        question["id"] = row.id


def plan_assembly(
    state: SessionState,
    plan_id: int,
    bias: dict | None = None,
):
    """构建双倍预审题池，保留每题难度配比。"""
    level = state["profile_snapshot"]["level"]
    kp_id = state["kp_id"]
    kp_name = state.get("kp_name") or ""
    pool_count = int(state.get("question_count") or 10) * 2
    weights = dict(bias) if bias else {
        difficulty: weight for difficulty, weight in DIFFICULTY_RATIOS[level]
    }
    difficulty_counts = allocate_difficulty_counts(pool_count, weights)
    difficulties = [
        difficulty
        for difficulty in ("simple", "mid", "hard")
        for _ in range(difficulty_counts[difficulty])
    ]
    random.shuffle(difficulties)
    plan = []
    sends = []
    used: list = []
    with SessionLocal() as s:
        seed_rows = (
            s.query(QuestionRow)
            .filter(
                QuestionRow.kp_id == int(kp_id),
                QuestionRow.source.in_(["ai_generated", "private"]),
            )
            .all()
        )
    seed_rows = [row for row in seed_rows if is_selectable_seed(row)]
    for index, difficulty in enumerate(difficulties):
        pool = [
            row for row in seed_rows
            if row.difficulty == difficulty and row.id not in used
        ]
        if pool:
            row = random.choice(pool)
            used.append(row.id)
            plan.append({
                "index": index,
                "difficulty": difficulty,
                "seed": seed_candidate(row, kp_id),
            })
        else:
            plan.append({
                "index": index,
                "difficulty": difficulty,
                "seed": None,
            })
            sends.append(Send("gen_candidate", {
                "plan_id": plan_id,
                "index": index,
                "difficulty": difficulty,
                "level": level,
                "kp_id": kp_id,
                "kp_name": kp_name,
            }))
    return plan, sends


def generate_question_set_node(state: SessionState):
    start_practice_session(
        str(state["session_id"]),
        int(state["student_id"]),
        int(state["kp_id"]),
    )
    plan, sends = plan_assembly(state, plan_id=1)
    update = {"plan": plan, "plan_id": 1}
    if sends:
        return Command(update=update, goto=sends)
    return Command(update=update, goto="check_assemble")


def gen_candidate_node(payload: dict) -> dict:
    try:
        question = build_designed_question(
            payload["difficulty"],
            sequence=payload["index"],
            kp_id=payload["kp_id"],
        )
    except Exception as exc:
        return {
            "llm_error": (
                f"AI 变式生成失败（第 {payload['index'] + 1} 题）：{exc}"
            )
        }
    return {"generated": [{
        "plan_id": payload["plan_id"],
        "index": payload["index"],
        "question": question,
    }]}


def check_assemble_node(state: SessionState) -> dict:
    if state.get("llm_error"):
        return {"phase": "done"}
    generated = {
        item["index"]: item["question"]
        for item in state.get("generated") or []
        if item["plan_id"] == state.get("plan_id")
    }
    candidates = []
    for slot in state.get("plan") or []:
        if slot["seed"] is not None:
            candidates.append(slot["seed"])
        else:
            candidates.append(generated[slot["index"]])
    seen = set()
    for index, question in enumerate(candidates):
        if question["stem"] not in seen:
            seen.add(question["stem"])
            continue
        for offset in range(1, 40):
            replacement = build_designed_question(
                question["difficulty"],
                sequence=1000 + index * 200 + offset,
                kp_id=state["kp_id"],
            )
            if replacement["stem"] not in seen:
                candidates[index] = replacement
                seen.add(replacement["stem"])
                break
    return {"candidates": candidates}


def route_after_check(state: SessionState) -> str:
    return "failed" if state.get("llm_error") else "h1_review"
