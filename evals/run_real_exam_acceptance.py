"""Run solver-only acceptance against private real-exam growth questions."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIN_SAMPLE_PER_TYPE = 15
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.adapters.real_exam_bank import (
    build_exam_spec,
    load_algebra_specs,
    load_growth_specs,
    load_question_bank,
)
from app.domain.exam.answer_equiv import (
    equation_equivalent,
    expression_equivalent,
    numeric_equivalent,
)
from app.domain.exam.registry import solve_exam_spec
from app.domain.exam.solvers import verify_growth_rate_result
from app.domain.assessment import get_question_handler

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--bank",
        type=Path,
        default=ROOT / "data" / "private_questions" / "middle_exam_math.json",
    )
    parser.add_argument(
        "--specs",
        type=Path,
        default=ROOT
        / "data"
        / "private_questions"
        / "real_exam_growth_specs.json",
    )
    parser.add_argument(
        "--algebra-specs",
        type=Path,
        default=ROOT
        / "data"
        / "private_questions"
        / "real_exam_algebra_specs.json",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "outputs" / "evals" / "middle_exam_solver_acceptance.json",
    )
    args = parser.parse_args()

    bank = load_question_bank(args.bank)
    questions = {
        question["id"]: question
        for question in bank.get("questions") or []
    }
    items = load_growth_specs(args.specs) + load_algebra_specs(
        args.algebra_specs
    )
    results = []
    for item in items:
        question = questions.get(item["question_id"], {})
        spec = build_exam_spec(item)
        solution = solve_exam_spec(spec)
        target = item.get("target") or item["spec"].get("target", "rate")
        spec_type = item["spec"]["type"]
        if spec_type == "growth_rate":
            passed = verify_growth_rate_result(
                solution,
                expected=item["expected"],
                target=target,
            )
        elif target == "choice":
            passed = item["expected"] in solution["answer"]
        elif target == "equation":
            passed = equation_equivalent(
                solution["answer"],
                item["expected"],
            )
        elif target == "parameter":
            passed = item["expected"] in solution["answer"]
        else:
            answers = solution["answer"]
            if not isinstance(answers, list):
                answers = [answers]
            passed = any(
                numeric_equivalent(answer, item["expected"])
                or expression_equivalent(answer, item["expected"])
                for answer in answers
            )
        handler_params = {
            "question_type": spec_type,
            "exam_spec": item["spec"],
        }
        handler = get_question_handler(handler_params)
        handler_passed = None
        if handler is not None:
            materialized = handler.materialize({
                "stem": question.get("stem", ""),
                "params": handler_params,
            })
            handler_passed = handler.check_answer(
                materialized,
                str(item["expected"]),
            )
            passed = passed and handler_passed
        results.append({
            "question_id": item["question_id"],
            "year": question.get("year"),
            "province": question.get("province"),
            "source_type": question.get("source_type"),
            "spec_type": spec_type,
            "target": target,
            "expected": item["expected"],
            "actual": solution["answer"],
            "equation": solution.get("equation"),
            "all_solutions": solution.get("all_solutions", []),
            "valid_solutions": solution.get("valid_solutions", []),
            "handler": handler.kind if handler is not None else None,
            "handler_verified": handler_passed,
            "status": "solver_verified" if passed else "failed",
            "passed": passed,
        })

    passed_count = sum(result["passed"] for result in results)
    type_summaries = []
    for spec_type in sorted({result["spec_type"] for result in results}):
        items_for_type = [
            result for result in results
            if result["spec_type"] == spec_type
        ]
        type_passed = sum(result["passed"] for result in items_for_type)
        type_summaries.append({
            "spec_type": spec_type,
            "total": len(items_for_type),
            "passed": type_passed,
            "failed": len(items_for_type) - type_passed,
            "sample_ready": len(items_for_type) >= MIN_SAMPLE_PER_TYPE,
            "status": (
                "verified"
                if (
                    len(items_for_type) >= MIN_SAMPLE_PER_TYPE
                    and type_passed == len(items_for_type)
                )
                else "insufficient_sample"
            ),
        })
    report = {
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "suite": "real_exam_acceptance",
        "capability": "structured_real_exam",
        "total": len(results),
        "passed": passed_count,
        "failed": len(results) - passed_count,
        "pass_rate": (
            round(passed_count / len(results), 4) if results else None
        ),
        "min_sample_per_type": MIN_SAMPLE_PER_TYPE,
        "type_summaries": type_summaries,
        "results": results,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"report={args.output}")


if __name__ == "__main__":
    main()
