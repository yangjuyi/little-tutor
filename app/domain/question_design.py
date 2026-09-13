"""程序化题目设计器.

当前模板固定走配方法，因此题目参数必须保证：
- 除以 a 后的一次项系数为偶数；
- 除以 a 后的常数项为整数；
- 判别式为完全平方数。

在此基础上，设计器从常见题型结构中生成题面，不再把随机参数后拼一句无关情境
当作“应用题”。LLM 生成题仍可保留，但必须通过同一质量闸门。
"""

from __future__ import annotations

from functools import lru_cache

from app.domain.grading import compute_answer, validate_difficulty_params
from app.domain.question_materialization import materialize_question
from app.domain.types import DifficultyLevel


_DESIGN_ORDER: dict[str, tuple[str, ...]] = {
    "simple": ("direct", "consecutive_even", "rectangle", "root_relation"),
    "mid": ("rectangle", "root_relation", "direct"),
    "hard": ("rectangle", "root_relation", "multi_step"),
}

_A_CHOICES: dict[str, tuple[int, ...]] = {
    "simple": (1,),
    "mid": (2, 3, 4, 5),
    "hard": (2, 3, 4, 5, 6, 7),
}

_FALLBACKS = {
    "simple": (
        (1, -6, 8, "", "direct"),
        (1, -4, 3, "", "direct"),
        (1, -8, 15, "", "direct"),
        (1, -10, 21, "", "direct"),
        (1, -2, -15, "", "direct"),
        (1, 2, -8, "", "direct"),
        (1, 4, -12, "", "direct"),
        (1, 6, 5, "", "direct"),
        (1, -6, -7, "", "direct"),
        (1, 8, 7, "", "direct"),
        (1, 10, 24, "", "direct"),
        (1, -10, 24, "", "direct"),
    ),
    "mid": (
        (2, -8, 6, "", "direct"),
        (2, -4, -6, "", "direct"),
        (3, -12, 9, "", "direct"),
        (3, -18, 24, "", "direct"),
        (4, -16, 12, "", "direct"),
        (4, -16, 0, "", "direct"),
        (5, -20, 15, "", "direct"),
        (5, -10, 0, "", "direct"),
        (2, -12, 16, "", "direct"),
        (2, -8, 8, "", "direct"),
        (3, -12, 0, "", "direct"),
        (3, -6, 3, "", "direct"),
    ),
    "hard": (
        (3, -12, 9, "多步化简", "multi_step"),
        (2, 4, -30, "建模", "rectangle"),
        (3, -18, 24, "根与系数", "root_relation"),
        (4, -24, 32, "多步化简", "multi_step"),
        (5, -30, 40, "建模", "rectangle"),
        (6, -24, 18, "根与系数", "root_relation"),
        (7, -28, 21, "多步化简", "multi_step"),
        (6, -24, 0, "建模", "rectangle"),
        (5, -20, 15, "根与系数", "root_relation"),
        (4, -16, 12, "多步化简", "multi_step"),
        (3, -6, 3, "建模", "rectangle"),
        (2, -4, -6, "根与系数", "root_relation"),
    ),
}


def _format_equation(a: int, b: int, c: int) -> str:
    first = "x²" if a == 1 else f"{a}x²"
    parts = [first]
    for coefficient, variable in ((b, "x"), (c, "")):
        if coefficient == 0:
            continue
        sign = "+" if coefficient > 0 else "-"
        magnitude = abs(coefficient)
        if variable:
            term = "x" if magnitude == 1 else f"{magnitude}x"
        else:
            term = str(magnitude)
        parts.append(f"{sign} {term}")
    return " ".join(parts) + " = 0"


def _factor_analysis(a: int, r1: int, r2: int) -> str:
    left = "" if a == 1 else f"{a}"
    return (
        f"原方程可化为 {left}(x-({r1}))(x-({r2}))=0，"
        f"因此两个根为 {r1} 与 {r2}。"
    )


def _params_from_roots(
    a: int, r1: int, r2: int, structure_tag: str, design_id: str,
) -> dict:
    return {
        "a": a,
        "b": -a * (r1 + r2),
        "c": a * r1 * r2,
        "structure_tag": structure_tag,
        "design_id": design_id,
    }


def _root_pair(slot: int, max_gap_steps: int = 4) -> tuple[int, int]:
    r1 = 1 + slot % 5
    r2 = r1 + 2 * (1 + (slot // 5) % max_gap_steps)
    if slot % 3 == 0:
        r1, r2 = -r2, -r1
    return r1, r2


def _direct(slot: int, difficulty: DifficultyLevel) -> dict:
    a = _A_CHOICES[difficulty][slot % len(_A_CHOICES[difficulty])]
    r1, r2 = _root_pair(slot)
    if difficulty == "hard":
        structure_tag, design_id = "多步化简", "multi_step"
    else:
        structure_tag, design_id = "", "direct"
    params = _params_from_roots(a, r1, r2, structure_tag, design_id)
    stem = f"解方程 {_format_equation(a, params['b'], params['c'])}，求 x 的全部值。"
    return {
        "stem": stem,
        "params": params,
        "analysis": _factor_analysis(a, r1, r2),
        "design_id": design_id,
    }


def _consecutive_even(slot: int) -> dict:
    smaller = 2 + 2 * (slot % 10)
    other = smaller + 2
    product = smaller * other
    params = {
        "a": 1,
        "b": 2,
        "c": -product,
        "structure_tag": "",
        "design_id": "consecutive_even",
    }
    return {
        "stem": (
            f"两个连续偶数的积是 {product}。设较小的偶数为 x，"
            "列出方程并求这两个偶数。"
        ),
        "params": params,
        "analysis": (
            f"x(x+2)={product}，化为 x²+2x-{product}=0，"
            f"解得 x={smaller} 或 x={-other}。"
        ),
        "design_id": "consecutive_even",
    }


def _rectangle(slot: int, difficulty: DifficultyLevel) -> dict:
    a = _A_CHOICES[difficulty][slot % len(_A_CHOICES[difficulty])]
    width = 1 + (slot % (2 if a >= 4 else 3))
    offset = 2 * a * (1 + (slot // 3) % 2)
    length = a * width + offset
    area = width * length
    params = {
        "a": a,
        "b": offset,
        "c": -area,
        "structure_tag": "建模" if difficulty == "hard" else "",
        "design_id": "rectangle",
        "valid_roots": [width],
    }
    if a == 1:
        relation = f"长比宽多 {offset} 米"
    else:
        relation = f"长比宽的 {a} 倍多 {offset} 米"
    return {
        "stem": (
            f"一块长方形菜地的宽为 x 米，{relation}，面积为 {area} 平方米。"
            "求这块菜地的宽。"
        ),
        "params": params,
        "analysis": (
            f"x({a}x+{offset})={area}，即 {_format_equation(a, offset, -area)}，"
            f"有效解为 x={width}。"
        ),
        "design_id": "rectangle",
    }


def _root_relation(slot: int, difficulty: DifficultyLevel) -> dict:
    a = _A_CHOICES[difficulty][slot % len(_A_CHOICES[difficulty])]
    if difficulty == "hard":
        a = min(a, 3)
    r1, r2 = 1 + slot % 3, 3 + slot % 6
    if (r1 + r2) % 2:
        r2 += 1
    params = _params_from_roots(
        a, r1, r2, "根与系数" if difficulty == "hard" else "", "root_relation",
    )
    return {
        "stem": (
            f"已知方程 {_format_equation(a, params['b'], params['c'])} 的两个根为 "
            "x₁、x₂。先用根与系数关系求 x₁+x₂ 与 x₁x₂，再求这两个根。"
        ),
        "params": params,
        "analysis": _factor_analysis(a, r1, r2),
        "design_id": "root_relation",
    }


def _multi_step(slot: int) -> dict:
    a = _A_CHOICES["hard"][slot % len(_A_CHOICES["hard"])]
    r1, r2 = _root_pair(slot)
    params = _params_from_roots(a, r1, r2, "多步化简", "multi_step")
    return {
        "stem": (
            f"解方程 {_format_equation(a, params['b'], params['c'])}。"
            "先观察系数并化简，再求 x 的全部值。"
        ),
        "params": params,
        "analysis": _factor_analysis(a, r1, r2),
        "design_id": "multi_step",
    }


def _fallback(difficulty: DifficultyLevel, slot: int) -> dict:
    choices = _FALLBACKS[difficulty]
    a, b, c, _, _ = choices[slot % len(choices)]
    roots = compute_answer(a, b, c)
    structure_tag = "多步化简" if difficulty == "hard" else ""
    design_id = "multi_step" if difficulty == "hard" else "direct"
    params = {
        "a": a, "b": b, "c": c,
        "structure_tag": structure_tag, "design_id": design_id,
    }
    if difficulty == "hard":
        stem = (
            f"解方程 {_format_equation(a, b, c)}。"
            "先观察系数并化简，再求 x 的全部值。"
        )
    else:
        stem = f"解方程 {_format_equation(a, b, c)}，求 x 的全部值。"
    return {
        "stem": stem,
        "params": params,
        "analysis": f"该方程的两个根为 {roots[0]:g} 与 {roots[1]:g}。",
        "design_id": design_id,
    }


def _build_variant(
    difficulty: DifficultyLevel, sequence: int = 0, kp_id: str = "math-9-01",
) -> dict:
    """构建单个题目变体；公共入口从缓存题池中取唯一项。"""
    order = _DESIGN_ORDER[difficulty]
    kind = order[sequence % len(order)]
    slot = sequence // len(order)
    if kind == "direct":
        designed = _direct(slot, difficulty)
    elif kind == "consecutive_even":
        designed = _consecutive_even(slot)
    elif kind == "rectangle":
        designed = _rectangle(slot, difficulty)
    elif kind == "root_relation":
        designed = _root_relation(slot, difficulty)
    else:
        designed = _multi_step(slot)

    params = designed["params"]
    error = validate_difficulty_params(
        params["a"], params["b"], params["c"],
        difficulty, params.get("structure_tag", ""),
    )
    if error:
        designed = _fallback(difficulty, slot)
        params = designed["params"]

    designed = materialize_question(designed)
    params = designed["params"]
    return {
        "id": f"q-{difficulty}-{designed['design_id']}-{sequence}",
        "kp_id": kp_id,
        "dep_kp_ids": [],
        "difficulty": difficulty,
        "stem": designed["stem"],
        "answer": designed["answer"],
        "analysis": designed["analysis"],
        "images": [],
        "source": "ai_generated",
        "params": params,
    }


@lru_cache(maxsize=None)
def _variant_pool(difficulty: str) -> tuple[dict, ...]:
    """缓存每个难度的唯一题池，避免组卷现场循环碰撞。"""
    candidates: list[dict] = []
    seen: set[str] = set()
    sequence = 0
    stale = 0
    while sequence < 2000 and stale < 200:
        question = _build_variant(difficulty, sequence)
        if question["stem"] not in seen:
            seen.add(question["stem"])
            candidates.append(question)
            stale = 0
        else:
            stale += 1
        sequence += 1

    by_a: dict[float, list[dict]] = {}
    for question in candidates:
        by_a.setdefault(question["params"]["a"], []).append(question)

    pool: list[dict] = []
    while len(pool) < 20:
        progressed = False
        for a in sorted(by_a):
            if len(pool) >= 20:
                break
            group = by_a[a]
            if group:
                pool.append(group.pop(0))
                progressed = True
        if not progressed:
            break
    if len(pool) < 20:
        raise RuntimeError(f"{difficulty} 题目设计池不足：仅生成 {len(pool)} 道唯一题")
    return tuple(pool)


def build_designed_question(
    difficulty: DifficultyLevel, sequence: int = 0, kp_id: str = "math-9-01",
) -> dict:
    """按难度和会话槽位从缓存题池中构建纯净、可复现的题目。"""
    pool = _variant_pool(difficulty)
    source = pool[sequence % len(pool)]
    question = dict(source)
    question["id"] = f"q-{difficulty}-{source['params']['design_id']}-{sequence}"
    question["kp_id"] = kp_id
    question["params"] = dict(source["params"])
    return question
