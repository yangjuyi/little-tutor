"""Import a downloaded middle-exam question compilation into private JSON."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRIVATE_PATH = ROOT / "data" / "private_questions" / "middle_exam_math.json"
SECTION_RE = re.compile(r"实际应用问题（([一二三四五六七八])）")
QUESTION_RE = re.compile(r"^(\d+)[．.，,]")
YEAR_REGION_RE = re.compile(r"（(20\d{2})\s+([^）]+)）")
MANUAL_ANSWERS = {
    ("四", 1): "（1）20-2x；13-2x；（2）x=2",
    ("四", 2): "（1）S=20t-4t²；（2）PQ=10cm；（3）t=2 或 t=3",
    ("四", 3): "（1）AD=24-3x；（2）宽 5 米，长 9 米",
    ("五", 1): "（1）8cm²；（2）Q 再出发 2 秒；（3）见参考解答",
    ("五", 2): "（1）1 秒；（2）3 秒；（3）不能",
    ("五", 3): "（1）680-10x；（2）42 元或 56 元",
}


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _parse_sections(lines: list[str], *, answers: bool) -> dict[tuple[str, int], str]:
    sections: dict[tuple[str, int], str] = {}
    current_section = ""
    current_number: int | None = None
    current_lines: list[str] = []

    def flush() -> None:
        nonlocal current_number, current_lines
        if current_section and current_number is not None:
            sections[(current_section, current_number)] = _normalize(
                " ".join(current_lines)
            )
        current_number = None
        current_lines = []

    for line in lines:
        match = SECTION_RE.search(line)
        if match:
            flush()
            current_section = match.group(1)
            continue
        if current_section:
            question_match = QUESTION_RE.match(line.strip())
            if question_match:
                flush()
                current_number = int(question_match.group(1))
                current_lines = [line]
            elif current_number is not None:
                current_lines.append(line)
    flush()
    return sections


def _answer_only(solution: str) -> str:
    match = re.search(r"【答案】(.*?)(?:【分析】|【解答】|【考点】|$)", solution)
    return _normalize(match.group(1)) if match else ""


def _skills(stem: str) -> list[str]:
    mapping = (
        ("利润", "利润问题"),
        ("销售", "销售问题"),
        ("面积", "面积建模"),
        ("篱笆", "几何建模"),
        ("纸盒", "立体几何建模"),
        ("函数", "一次函数综合"),
        ("判别式", "根的判别式"),
    )
    skills = [label for keyword, label in mapping if keyword in stem]
    if any(
        keyword in stem
        for keyword in ("增长率", "平均增长", "百分率", "增长到", "增长为")
    ):
        skills.append("平均增长率")
    if "根与系数" in stem or (
        "两个根" in stem and ("和" in stem or "积" in stem)
    ):
        skills.append("根与系数关系")
    return skills or ["一元二次方程实际应用"]


def _gap(stem: str) -> str:
    if "如图" in stem:
        return "需要图形理解和动态/几何建模，当前 V2 不能自动解析。"
    if any(keyword in stem for keyword in ("增长", "利润", "销售")):
        return "需要从实际情境建立方程、筛选有效解并解释实际意义。"
    return "超出当前固定参数模板，需要题型扩展和结构化建模。"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--source",
        type=Path,
        default=ROOT / "outputs" / "private_sources" / "21cnjy_22960957.md",
    )
    parser.add_argument("--output", type=Path, default=PRIVATE_PATH)
    args = parser.parse_args()

    lines = args.source.read_text(encoding="utf-8").splitlines()
    student_start = next(
        index for index, line in enumerate(lines)
        if "知识点 4 实际应用问题（一）" in line
    )
    answer_start = next(
        index for index, line in enumerate(lines)
        if "实际应用问题（一）参考答案" in line
    )
    student = _parse_sections(lines[student_start:answer_start], answers=False)
    answers = _parse_sections(lines[answer_start:], answers=True)

    existing = json.loads(args.output.read_text(encoding="utf-8"))
    questions = list(existing.get("questions") or [])
    by_key = {
        (
            str(question.get("year", "")),
            str(question.get("province", "")),
            str(question.get("stem", ""))[:40],
        ): question
        for question in questions
    }

    source_url = "https://zy.21cnjy.com/22960957"
    source_title = (
        "2025年中考数学计算专题（全国通用版）专题17 "
        "一元二次方程实际应用题"
    )
    imported = 0
    for (section, number), stem in student.items():
        year_match = YEAR_REGION_RE.search(stem[:120])
        year = int(year_match.group(1)) if year_match else 0
        region = year_match.group(2).strip() if year_match else "未标注"
        key = (str(year), region, stem[:40])
        solution = answers.get((section, number), "")
        answer = _answer_only(solution) or MANUAL_ANSWERS.get(
            (section, number), ""
        )
        if key in by_key:
            by_key[key].update({
                "answer": answer,
                "reference_solution": solution,
                "tested_skills": _skills(stem),
                "gap": _gap(stem),
            })
            continue
        by_key[key] = {}
        imported += 1
        question = {
            "id": f"zk-import-{section}-{number:02d}",
            "year": year,
            "province": region,
            "source_type": (
                "exam_style" if "模拟" in region else "real_exam"
            ),
            "source_url": source_url,
            "source_title": source_title,
            "source_section": f"实际应用问题（{section}）",
            "stem": stem,
            "answer": answer,
            "reference_solution": solution,
            "tested_skills": _skills(stem),
            "current_support": False,
            "gap": _gap(stem),
        }
        by_key[key] = question
        questions.append(question)

    payload = {
        "kp_name": "一元二次方程中考综合",
        "questions": questions,
    }
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"imported={imported} total={len(questions)} output={args.output}")


if __name__ == "__main__":
    main()
