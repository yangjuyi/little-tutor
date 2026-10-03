"""会话内自适应策略。"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from app.domain.types import DifficultyLevel


DIFFICULTY_ORDER: tuple[DifficultyLevel, ...] = ("simple", "mid", "hard")
ASSISTANCE_WEIGHTS = {
    "independent": 1.0,
    "hinted": 0.5,
    "scaffolded": 0.25,
    "skipped": 0.0,
}


def _assistance_weight(level: str | None) -> float:
    return ASSISTANCE_WEIGHTS.get(level or "independent", 0.25)


def evidence_weight_for(
    is_correct: bool,
    assistance_level: str | None,
) -> float:
    """单次作答进入掌握度证据链时的权重。"""
    return _assistance_weight(assistance_level) if is_correct else 0.0


def evidence_weighted_rate(results: Sequence[dict]) -> float:
    """按受助程度加权计算会话掌握证据。"""
    if not results:
        return 0.0
    correct_weight = sum(
        evidence_weight_for(
            bool(
                result.get(
                    "effective_is_correct",
                    result.get("is_correct"),
                )
            ),
            result.get("assistance_level"),
        )
        for result in results
    )
    return round(correct_weight / len(results), 4)


def select_next_target(
    current_target: DifficultyLevel,
    results: Sequence[dict],
) -> DifficultyLevel:
    """根据最近作答证据决定下一题目标难度。"""
    if not results:
        return current_target
    latest = results[-1]
    latest_difficulty = latest.get("difficulty", current_target)
    latest_index = DIFFICULTY_ORDER.index(latest_difficulty)

    if not latest.get("is_correct"):
        return DIFFICULTY_ORDER[max(0, latest_index - 1)]

    recent = results[-2:]
    independent_correct = all(
        result.get("is_correct")
        and (result.get("assistance_level") or "independent") == "independent"
        for result in recent
    )
    if len(recent) == 2 and independent_correct:
        target_index = DIFFICULTY_ORDER.index(current_target)
        return DIFFICULTY_ORDER[min(len(DIFFICULTY_ORDER) - 1, target_index + 1)]
    return current_target


def order_questions_for_target(
    questions: Iterable[dict],
    target: DifficultyLevel,
) -> list[dict]:
    """按与目标难度的距离稳定排序，保持同难度题目的原有顺序。"""
    target_index = DIFFICULTY_ORDER.index(target)
    return sorted(
        questions,
        key=lambda question: abs(
            DIFFICULTY_ORDER.index(question["difficulty"]) - target_index
        ),
    )


def allocate_difficulty_counts(
    total: int,
    weights: dict[str, float],
) -> dict[str, int]:
    """按权重把总题量分配到各难度，使用最大余数法保持总和精确。"""
    if total <= 0:
        return {difficulty: 0 for difficulty in DIFFICULTY_ORDER}
    normalized = {
        difficulty: max(0.0, float(weights.get(difficulty, 0.0)))
        for difficulty in DIFFICULTY_ORDER
    }
    weight_sum = sum(normalized.values())
    if weight_sum <= 0:
        normalized = {"simple": 1.0, "mid": 0.0, "hard": 0.0}
        weight_sum = 1.0
    raw = {
        difficulty: total * weight / weight_sum
        for difficulty, weight in normalized.items()
    }
    counts = {
        difficulty: int(value)
        for difficulty, value in raw.items()
    }
    remaining = total - sum(counts.values())
    ranked = sorted(
        DIFFICULTY_ORDER,
        key=lambda difficulty: raw[difficulty] - counts[difficulty],
        reverse=True,
    )
    for difficulty in ranked[:remaining]:
        counts[difficulty] += 1
    return counts
