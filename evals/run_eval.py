"""Run little-tutor grading evaluations and write machine-readable reports."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals.harness import (  # noqa: E402
    load_cases,
    program_only_grader,
    run_cases,
    summarize,
)


def _real_grader():
    from app.adapters.llm import get_llm, grade_question

    llm = get_llm("grade")

    def grader(question: dict, steps: list[dict]) -> dict:
        return grade_question(question, steps, llm)

    return grader


def _default_output() -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return ROOT / "outputs" / "evals" / f"eval-{stamp}.json"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--cases",
        type=Path,
        default=ROOT / "evals" / "cases" / "public_v1.jsonl",
    )
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument(
        "--tag",
        help="Only run cases carrying this exact tag, e.g. no_steps.",
    )
    parser.add_argument(
        "--mode",
        choices=("program", "real"),
        default="program",
        help="program is offline; real invokes the configured grading LLM.",
    )
    parser.add_argument("--output", type=Path, default=_default_output())
    args = parser.parse_args()

    cases = load_cases(args.cases)
    if args.tag:
        cases = [
            case for case in cases
            if args.tag in (case.get("tags") or [])
        ]
    if args.limit:
        cases = cases[: args.limit]
    if not cases:
        raise SystemExit("no evaluation cases found")

    grader = program_only_grader if args.mode == "program" else _real_grader()
    started_at = datetime.now().isoformat(timespec="seconds")
    results = run_cases(cases, grader)
    finished_at = datetime.now().isoformat(timespec="seconds")
    summary = summarize(results)
    report = {
        "started_at": started_at,
        "finished_at": finished_at,
        "mode": args.mode,
        "cases_file": str(args.cases),
        "limit": args.limit,
        "summary": summary,
        "results": results,
    }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    jsonl_path = args.output.with_suffix(".jsonl")
    with jsonl_path.open("w", encoding="utf-8", newline="\n") as handle:
        for result in results:
            handle.write(json.dumps(result, ensure_ascii=False) + "\n")

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"report={args.output}")
    print(f"results={jsonl_path}")


if __name__ == "__main__":
    main()
