"""Classify middle-exam probes into implementation capabilities."""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE = ROOT / "data" / "private_questions" / "middle_exam_math.json"
DEFAULT_MARKDOWN = ROOT / "outputs" / "evals" / "middle_exam_capability_matrix.md"
DEFAULT_JSON = ROOT / "outputs" / "evals" / "middle_exam_capability_matrix.json"
DEFAULT_ACCEPTANCE = (
    ROOT / "outputs" / "evals" / "middle_exam_solver_acceptance.json"
)
MIN_SAMPLE_PER_TYPE = 15

CAPABILITIES = {
    "symbolic_answer": {
        "label": "符号答案与等价判定",
        "priority": "P0",
        "why": "根式、分数、表达式和百分数都要做符号等价，不能只比小数。",
    },
    "discriminant": {
        "label": "判别式与实数根个数",
        "priority": "P1",
        "why": "中考选择题和参数题的共同基础。",
    },
    "root_relation": {
        "label": "根与系数关系和方程还原",
        "priority": "P1",
        "why": "需要从根的和积反推参数或方程。",
    },
    "growth_rate": {
        "label": "增长率与降价率",
        "priority": "P1",
        "why": "统一为 a(1+x)^n=b 的增长/衰减模型。",
    },
    "profit_sales": {
        "label": "利润与销售建模",
        "priority": "P2",
        "why": "需要价格变化、销量变化、利润函数和有效解筛选。",
    },
    "geometry_area": {
        "label": "面积、篱笆与几何建模",
        "priority": "P2",
        "why": "需要图形结构和变量表示，当前文本参数不足以表达。",
    },
    "dynamic_geometry": {
        "label": "几何动点与时间方程",
        "priority": "P3",
        "why": "需要图形、速度和范围的联合约束，依赖中间过程诊断。",
    },
    "substitution": {
        "label": "代数式整体代换",
        "priority": "P2",
        "why": "需要符号化简和目标表达式求值，不要求解具体根。",
    },
    "choice": {
        "label": "选择题判分",
        "priority": "P1",
        "why": "支持选项型答案和知识点判分。",
    },
}


def classify(question: dict) -> list[str]:
    stem = question.get("stem", "")
    skills = " ".join(question.get("tested_skills") or [])
    text = f"{stem} {skills}"
    found = {"symbolic_answer"}
    if any(keyword in text for keyword in ("判别式", "实数根", "有两个相等", "两个不相等")):
        found.add("discriminant")
    if any(keyword in text for keyword in ("根与系数", "两个根的和", "两个根的积", "原来的方程")):
        found.add("root_relation")
    if any(
        keyword in text
        for keyword in ("增长率", "平均增长", "百分率", "增长到", "增长为")
    ):
        found.add("growth_rate")
    if any(keyword in text for keyword in ("利润", "销量", "售价", "销售额", "进货")):
        found.add("profit_sales")
    if any(keyword in text for keyword in ("面积", "篱笆", "墙", "纸板", "长方形", "羊圈", "花圃")):
        found.add("geometry_area")
    if any(keyword in text for keyword in ("点P", "点Q", "cm/s", "停止运动")):
        found.add("dynamic_geometry")
    if "一个根" in text and any(keyword in text for keyword in ("代数式", "的值")):
        found.add("substitution")
    if "A." in text and "B." in text:
        found.add("choice")
    return sorted(found)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MARKDOWN)
    parser.add_argument("--json", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--acceptance", type=Path, default=DEFAULT_ACCEPTANCE)
    args = parser.parse_args()

    acceptance: dict[str, str] = {}
    accepted_by_type: dict[str, dict] = {}
    if args.acceptance.exists():
        acceptance_payload = json.loads(
            args.acceptance.read_text(encoding="utf-8")
        )
        acceptance = {
            item["question_id"]: item["status"]
            for item in acceptance_payload.get("results") or []
        }
        accepted_by_type = {
            item["spec_type"]: item
            for item in acceptance_payload.get("type_summaries") or []
        }
    payload = json.loads(args.source.read_text(encoding="utf-8"))
    counts = Counter()
    matrix = []
    for question in payload.get("questions") or []:
        capabilities = classify(question)
        counts.update(capabilities)
        matrix.append({
            "id": question.get("id"),
            "year": question.get("year"),
            "province": question.get("province"),
            "source_type": question.get("source_type"),
            "capabilities": capabilities,
            "current_support": bool(question.get("current_support")),
            "solver_status": acceptance.get(
                question.get("id"),
                "unsupported",
            ),
        })

    capabilities = []
    for capability, count in counts.most_common():
        meta = CAPABILITIES[capability]
        capabilities.append({
            "id": capability,
            "label": meta["label"],
            "priority": meta["priority"],
            "question_count": count,
            "sample_status": (
                "sufficient"
                if count >= MIN_SAMPLE_PER_TYPE
                else "insufficient"
            ),
            "why": meta["why"],
        })
    result = {
        "total_questions": len(matrix),
        "supported_questions": sum(item["current_support"] for item in matrix),
        "solver_verified_questions": sum(
            item["solver_status"] == "solver_verified"
            for item in matrix
        ),
        "min_sample_per_type": MIN_SAMPLE_PER_TYPE,
        "accepted_by_type": accepted_by_type,
        "capabilities": capabilities,
        "matrix": matrix,
    }

    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    lines = [
        "# 中考能力矩阵",
        "",
        f"- 题目总数：{result['total_questions']}",
        f"- 当前可运行：{result['supported_questions']}",
        f"- 离线求解已验证：{result['solver_verified_questions']}",
        f"- 单题型最低样本：{result['min_sample_per_type']}",
        "",
        "## 能力优先级",
        "",
        "| 优先级 | 能力 | 覆盖题数 | 样本状态 | 为什么 |",
        "|---|---|---:|---|---|",
    ]
    for item in capabilities:
        lines.append(
            f"| {item['priority']} | {item['label']} | "
            f"{item['question_count']} | {item['sample_status']} | "
            f"{item['why']} |"
        )
    lines.extend([
        "",
        "## 逐题能力",
        "",
        "| 题号 | 年份/地区 | 能力 | 求解状态 |",
        "|---|---|---|---|",
    ])
    for item in matrix:
        labels = [
            CAPABILITIES[capability]["label"]
            for capability in item["capabilities"]
        ]
        lines.append(
            f"| {item['id']} | {item['year']} {item['province']} | "
            + "、".join(labels)
            + f" | {item['solver_status']} |"
        )
    args.markdown.write_text("\n".join(lines), encoding="utf-8")
    print(f"questions={len(matrix)} capabilities={len(capabilities)}")
    print(f"markdown={args.markdown}")
    print(f"json={args.json}")


if __name__ == "__main__":
    main()
