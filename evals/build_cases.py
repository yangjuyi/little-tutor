"""Build reproducible evaluation case files from local question catalogs."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from evals.harness import build_cases, write_cases  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT / "evals" / "cases" / "public_v1.jsonl",
    )
    parser.add_argument(
        "--source",
        choices=("public", "private", "all"),
        default="public",
        help="Question source. Private outputs must stay untracked.",
    )
    parser.add_argument("--limit-questions", type=int)
    args = parser.parse_args()

    cases = build_cases(
        source=args.source,
        limit_questions=args.limit_questions,
    )
    write_cases(cases, args.output)
    print(f"cases={len(cases)} output={args.output}")


if __name__ == "__main__":
    main()
