"""数学判分、参数约束与题目真值计算。"""

from __future__ import annotations

import math
import random
import re
from fractions import Fraction

from app.domain.types import DifficultyLevel, Level


DIFFICULTY_RATIOS = {
    "weak": [("simple", 0.6), ("mid", 0.4), ("hard", 0.0)],
    "mid": [("simple", 0.2), ("mid", 0.5), ("hard", 0.3)],
    "strong": [("simple", 0.1), ("mid", 0.5), ("hard", 0.4)],
}

DIFFICULTY_CONSTRAINTS: dict[str, dict] = {
    "simple": {"a_min": 1, "a_max": 1, "b_max": 12, "c_max": 30, "roots": "integer"},
    "mid": {"a_min": 2, "a_max": 5, "b_max": 20, "c_max": 30, "roots": "rational"},
    "hard": {
        "a_min": 2,
        "a_max": 7,
        "b_max": 30,
        "c_max": 40,
        "roots": "rational",
        "structure_required": True,
    },
}

STRUCTURE_TAGS = ("建模", "根与系数", "多步化简")
_STEM_SUFFIX = {
    "": "请用配方法求解 x 的值。",
    "建模": "请根据情境列出方程并求解 x 的值。",
    "根与系数": "请利用根与系数的关系求解 x 的值。",
    "多步化简": "请先化简方程，再求解 x 的值。",
}

_NUM_TOKEN = re.compile(r"-?\d+(?:\.\d+)?(?:/-?\d+(?:\.\d+)?)?")
_VAR_LABEL = re.compile(r"[xX]\s*_?\s*(?:[0-9₁₂])+(?=\s*=)")


def pick_difficulty(mastery_level: Level) -> DifficultyLevel:
    options = DIFFICULTY_RATIOS[mastery_level]
    difficulties = [difficulty for difficulty, _ in options]
    weights = [weight for _, weight in options]
    return random.choices(difficulties, weights=weights, k=1)[0]


def _is_integer(value: float) -> bool:
    return abs(value - round(value)) < 1e-9


def _exact_roots(a: float, b: float, c: float) -> tuple[Fraction, Fraction]:
    ai, bi, ci = int(round(a)), int(round(b)), int(round(c))
    disc = bi * bi - 4 * ai * ci
    k = math.isqrt(disc)
    return Fraction(-bi + k, 2 * ai), Fraction(-bi - k, 2 * ai)


def completion_cleanliness_error(a: float, b: float, c: float) -> str | None:
    if a == 0:
        return "a 不能为 0"
    normalized_b = b / a
    normalized_c = c / a
    if not _is_integer(normalized_b) or not _is_integer(normalized_c):
        return "除以 a 后的一次项与常数项必须为整数，保证配方中间值整洁"
    if int(round(normalized_b)) % 2 != 0:
        return "配方法要求 b/a 为偶数，避免出现 1/4 类不常见中间值"
    return None


def _numeric_constraint_error(
    a: float,
    b: float,
    c: float,
    difficulty: DifficultyLevel,
    curated: bool = False,
) -> str | None:
    bounds = DIFFICULTY_CONSTRAINTS[difficulty]
    if not (_is_integer(a) and _is_integer(b) and _is_integer(c)):
        return "系数必须为整数，保证题目可手解"
    if a == 0:
        return "a 不能为 0"
    disc = b * b - 4 * a * c
    if disc < 0:
        return f"无实数解（判别式 {disc:g} < 0）"
    if not curated and not bounds["a_min"] <= a <= bounds["a_max"]:
        return f"a={a:g} 不在 {difficulty} 难度范围 [{bounds['a_min']}, {bounds['a_max']}]"
    if not curated and abs(b) > bounds["b_max"]:
        return f"|b|={abs(b):g} 超出 {difficulty} 难度上限 {bounds['b_max']}"
    if not curated and abs(c) > bounds["c_max"]:
        return f"|c|={abs(c):g} 超出 {difficulty} 难度上限 {bounds['c_max']}"
    disc_i = int(round(disc))
    k = math.isqrt(disc_i)
    if k * k != disc_i:
        return f"判别式 {disc_i} 不是完全平方数，根为无理数，不适合手解"
    if bounds["roots"] == "integer":
        for root in _exact_roots(a, b, c):
            if root.denominator != 1:
                return f"{difficulty} 难度要求整数根，实际出现分数根 {root}"
    if not curated:
        clean_error = completion_cleanliness_error(a, b, c)
        if clean_error:
            return clean_error
    return None


def validate_difficulty_params(
    a: float,
    b: float,
    c: float,
    difficulty: DifficultyLevel,
    structure_tag: str = "",
    curated: bool = False,
) -> str | None:
    error = _numeric_constraint_error(a, b, c, difficulty, curated=curated)
    if error:
        return error
    if (
        DIFFICULTY_CONSTRAINTS[difficulty].get("structure_required")
        and structure_tag not in STRUCTURE_TAGS
    ):
        return (
            f"hard 难度必须携带结构标记（{'/'.join(STRUCTURE_TAGS)}），"
            f"不能只靠系数大撑难度"
        )
    return None


def hard_downgrade_target(
    a: float, b: float, c: float
) -> DifficultyLevel | None:
    if _numeric_constraint_error(a, b, c, "hard") is None:
        mid = DIFFICULTY_CONSTRAINTS["mid"]
        if mid["a_min"] <= a <= mid["a_max"]:
            return "mid"
    return None


def compute_answer(a: float, b: float, c: float) -> tuple:
    if a == 0:
        raise ValueError("a 不能为 0，不是二次方程")
    disc = b * b - 4 * a * c
    if disc < 0:
        raise ValueError(f"无实数解：判别式 {disc} < 0")
    x1 = (-b + math.sqrt(disc)) / (2 * a)
    x2 = (-b - math.sqrt(disc)) / (2 * a)
    return (round(x1, 2), round(x2, 2))


def validate_params(a: float, b: float, c: float) -> str | None:
    if a == 0:
        return "a 不能为 0"
    disc = b * b - 4 * a * c
    if disc < 0:
        return f"无实数解（判别式 {disc} < 0），请调整参数"
    return None


def extract_numbers(text: str) -> set[float]:
    text = _VAR_LABEL.sub("x", text)
    values: set[float] = set()
    for token in _NUM_TOKEN.findall(text):
        if "/" in token:
            num, den = token.split("/")
            if float(den) != 0:
                values.add(round(float(num) / float(den), 2))
        else:
            values.add(round(float(token), 2))
    return values


def check_is_correct(student_final: str, roots: list[float]) -> bool:
    if not student_final.strip():
        return False
    numbers = extract_numbers(student_final)
    return all(
        any(abs(number - root) < 0.01 for number in numbers)
        for root in set(roots)
    )


def question_roots(question: dict) -> list[float]:
    params = question.get("params")
    if params:
        if params.get("valid_roots"):
            return [float(value) for value in params["valid_roots"]]
        x1, x2 = compute_answer(params["a"], params["b"], params["c"])
        if params.get("design_id") == "rectangle":
            return [root for root in (x1, x2) if root > 0]
        return [x1, x2]
    return sorted(extract_numbers(question["answer"]))


def build_question_record(
    *,
    a: float,
    b: float,
    c: float,
    difficulty: DifficultyLevel,
    stem_context: str,
    structure_tag: str,
    kp_id: str,
) -> dict:
    x1, x2 = compute_answer(a, b, c)
    stem = (
        f"{stem_context}："
        f"已知方程 {a:g}x² + {b:g}x + {c:g} = 0，"
        f"{_STEM_SUFFIX.get(structure_tag, _STEM_SUFFIX[''])}"
    )
    return {
        "id": f"q-{random.randint(1000, 9999)}",
        "kp_id": kp_id,
        "dep_kp_ids": [],
        "difficulty": difficulty,
        "stem": stem,
        "answer": f"x₁={x1}, x₂={x2}",
        "analysis": (
            f"用配方法：将方程 {a}x² + {b}x + {c} = 0 "
            f"化为标准形式后配方求解。"
        ),
        "images": [],
        "source": "ai_generated",
        "params": {
            "a": a,
            "b": b,
            "c": c,
            "structure_tag": structure_tag,
        },
    }
