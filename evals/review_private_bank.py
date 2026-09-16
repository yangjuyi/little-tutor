"""Render a human-readable review of local private question banks."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRIVATE_DIR = ROOT / "data" / "private_questions"
OUTPUT = ROOT / "outputs" / "evals" / "private_bank_review.md"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _drill_lines(payload: dict) -> list[str]:
    lines = [
        "## 常规配方法私有题",
        "",
        f"- 题量：{len(payload.get('questions') or [])}",
        "- 定位：V2 当前可运行的重复训练题，不代表中考综合难度",
        "",
    ]
    for index, question in enumerate(payload.get("questions") or [], start=1):
        params = question.get("params") or {}
        lines.extend([
            f"### {index}. {question['stem']}",
            "",
            f"- 难度标签：`{question.get('difficulty', 'unknown')}`",
            (
                "- 参数："
                f"`a={params.get('a')}, b={params.get('b')}, c={params.get('c')}`"
            ),
            f"- 解析：{question.get('analysis', '')}",
            "",
        ])
    return lines


def _middle_exam_lines(payload: dict) -> list[str]:
    questions = payload.get("questions") or []
    supported = sum(bool(question.get("current_support")) for question in questions)
    lines = [
        "## 中考真题探针",
        "",
        f"- 题量：{len(questions)}",
        f"- 当前系统可运行：{supported}",
        f"- 当前系统不支持：{len(questions) - supported}",
        "- 定位：暴露真实中考题型、判分和建模缺口，不冒充 V2 已支持",
        "",
    ]
    for index, question in enumerate(questions, start=1):
        support = "支持" if question.get("current_support") else "不支持"
        lines.extend([
            (
                f"### {index}. {question.get('year', '')} "
                f"{question.get('province', '')}｜{support}"
            ),
            "",
            question["stem"],
            "",
            f"- 答案：`{question.get('answer', '')}`",
            (
                "- 考查："
                + "、".join(question.get("tested_skills") or [])
            ),
            f"- 当前缺口：{question.get('gap', '')}",
            "",
        ])
    return lines


def main() -> None:
    drill_path = PRIVATE_DIR / "drills.json"
    middle_path = PRIVATE_DIR / "middle_exam_math.json"
    lines = [
        "# 私有题库审查",
        "",
        "> 私有资料，仅在本机查看，不进入公开仓库。",
        "",
    ]
    if drill_path.exists():
        lines.extend(_drill_lines(_load(drill_path)))
    if middle_path.exists():
        lines.extend(_middle_exam_lines(_load(middle_path)))
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text("\n".join(lines), encoding="utf-8")
    print(f"report={OUTPUT}")


if __name__ == "__main__":
    main()
