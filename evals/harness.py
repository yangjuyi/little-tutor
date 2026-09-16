"""Build, run, and summarize little-tutor evaluation cases."""

from __future__ import annotations

import hashlib
import json
import statistics
import time
from collections import Counter
from pathlib import Path
from typing import Callable

from app.domain.grading import check_is_correct, question_roots
from app.domain.question_materialization import materialize_question


ROOT = Path(__file__).resolve().parents[1]
PUBLIC_SEED_PATH = ROOT / "data" / "seed_questions.json"
PRIVATE_DRILLS_PATH = ROOT / "data" / "private_questions" / "drills.json"
GRADER_PROMPT_PATH = ROOT / "app" / "adapters" / "prompts" / "grader_v1.md"

Grader = Callable[[dict, list[dict]], dict]


def _infer_design_id(question: dict) -> str:
    stem = str(question.get("stem") or "")
    if "根与系数" in stem:
        return "root_relation"
    if "长方形" in stem or "菜地" in stem:
        return "rectangle"
    if "连续偶数" in stem:
        return "consecutive_even"
    if "先化简" in stem or "多步化简" in stem:
        return "multi_step"
    return "direct"


def _load_questions(path: Path, source: str) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    questions = []
    for index, raw in enumerate(payload.get("questions") or [], start=1):
        params = dict(raw.get("params") or {})
        params.setdefault("design_id", _infer_design_id(raw))
        question = {
            "id": f"{source}-{index:03d}",
            "kp_id": "math-9-01",
            "dep_kp_ids": [],
            "difficulty": raw.get("difficulty", "mid"),
            "stem": raw["stem"],
            "answer": raw.get("answer", ""),
            "analysis": raw.get("analysis", ""),
            "images": [],
            "source": source,
            "params": params,
        }
        questions.append(materialize_question(question))
    return questions


def load_public_questions() -> list[dict]:
    return _load_questions(PUBLIC_SEED_PATH, "public_seed")


def load_private_questions() -> list[dict]:
    if not PRIVATE_DRILLS_PATH.exists():
        return []
    return _load_questions(PRIVATE_DRILLS_PATH, "private_drill")


def _answer_text(values: list[float]) -> str:
    if len(values) == 1:
        return f"x={values[0]:g}"
    return f"x₁={values[0]:g}, x₂={values[1]:g}"


def _build_variants(question: dict, prefix: str) -> list[dict]:
    roots = list(question_roots(question))
    correct = _answer_text(roots)
    wrong = _answer_text([root + 1 for root in roots])
    partial = _answer_text(roots[:1]) if len(roots) > 1 else ""
    common_tags = [
        f"difficulty:{question.get('difficulty', 'unknown')}",
        f"design:{question['params'].get('design_id', 'unknown')}",
    ]
    correct_steps = [
        {"basis": "根据题意建立方程", "result": "由题意得到一元二次方程"},
        {"basis": "配方并求出全部根", "result": correct},
    ]
    variants = [
        {
            "case_id": f"{prefix}-correct-process",
            "tags": common_tags + ["correct", "with_process"],
            "student_steps": correct_steps,
            "expected_program_correct": True,
            "expected_insufficient_evidence": False,
        },
        {
            "case_id": f"{prefix}-correct-final-only",
            "tags": common_tags + ["correct", "final_only"],
            "student_steps": [
                {"basis": "直接给出最终答案", "result": correct},
            ],
            "expected_program_correct": True,
            "expected_insufficient_evidence": None,
        },
        {
            "case_id": f"{prefix}-partial-answer",
            "tags": common_tags + ["wrong", "missing_root"],
            "student_steps": [
                {"basis": "只完成部分求解", "result": partial},
            ],
            "expected_program_correct": False,
            "expected_insufficient_evidence": None,
        },
        {
            "case_id": f"{prefix}-wrong-answer",
            "tags": common_tags + ["wrong", "wrong_root"],
            "student_steps": [
                {"basis": "配方后得到错误结果", "result": wrong},
            ],
            "expected_program_correct": False,
            "expected_insufficient_evidence": None,
        },
        {
            "case_id": f"{prefix}-no-evidence",
            "tags": common_tags + ["wrong", "no_steps"],
            "student_steps": [],
            "expected_program_correct": False,
            "expected_insufficient_evidence": True,
        },
    ]
    for variant in variants:
        variant["question"] = question
    return variants


def build_cases(
    *,
    source: str = "public",
    limit_questions: int | None = None,
) -> list[dict]:
    if source == "public":
        questions = load_public_questions()
    elif source == "private":
        questions = load_private_questions()
    elif source == "all":
        questions = load_public_questions() + load_private_questions()
    else:
        raise ValueError(f"unknown case source: {source}")
    if limit_questions is not None:
        questions = questions[:limit_questions]
    cases = []
    for question in questions:
        cases.extend(_build_variants(question, question["id"]))
    return cases


def write_cases(cases: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for case in cases:
            handle.write(json.dumps(case, ensure_ascii=False) + "\n")


def load_cases(path: Path) -> list[dict]:
    cases = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                cases.append(json.loads(line))
    return cases


def program_only_grader(question: dict, steps: list[dict]) -> dict:
    final = steps[-1]["result"].strip() if steps else ""
    is_correct = check_is_correct(final, question_roots(question))
    return {
        "is_correct": is_correct,
        "error": {
            "error_type": "无错" if is_correct else "未归因",
            "confidence": 1.0 if is_correct else 0.0,
            "evidence": "offline program-only evaluation",
            "evidence_source": "program",
            "insufficient_evidence": not is_correct,
            "steps_analyzed": len(steps),
        },
    }


def run_cases(cases: list[dict], grader: Grader) -> list[dict]:
    results = []
    for case in cases:
        started = time.perf_counter()
        actual = grader(case["question"], case["student_steps"])
        latency_ms = (time.perf_counter() - started) * 1000
        error = actual.get("error") or {}
        result = {
            "case_id": case["case_id"],
            "tags": case.get("tags") or [],
            "expected_program_correct": case["expected_program_correct"],
            "expected_insufficient_evidence": case.get(
                "expected_insufficient_evidence"
            ),
            "actual": {
                "is_correct": bool(actual.get("is_correct")),
                "error_type": error.get("error_type"),
                "confidence": error.get("confidence"),
                "evidence": error.get("evidence"),
                "evidence_source": error.get("evidence_source"),
                "insufficient_evidence": bool(
                    error.get("insufficient_evidence")
                ),
                "steps_analyzed": error.get("steps_analyzed"),
            },
            "latency_ms": round(latency_ms, 2),
        }
        result["program_match"] = (
            result["actual"]["is_correct"]
            == result["expected_program_correct"]
        )
        results.append(result)
    return results


def _rate(numerator: int, denominator: int) -> float | None:
    if not denominator:
        return None
    return round(numerator / denominator, 4)


def _prompt_hash() -> str:
    if not GRADER_PROMPT_PATH.exists():
        return ""
    return hashlib.sha256(
        GRADER_PROMPT_PATH.read_bytes()
    ).hexdigest()[:12]


def summarize(results: list[dict]) -> dict:
    total = len(results)
    program_matches = sum(result["program_match"] for result in results)
    correct_cases = [
        result for result in results
        if result["expected_program_correct"]
    ]
    wrong_cases = [
        result for result in results
        if not result["expected_program_correct"]
    ]
    correct_guard_passes = sum(
        result["actual"]["is_correct"]
        and result["actual"]["error_type"] == "无错"
        for result in correct_cases
    )
    wrong_guard_passes = sum(
        not result["actual"]["is_correct"]
        and result["actual"]["error_type"] not in (None, "", "无错")
        for result in wrong_cases
    )
    fallback_count = sum(
        result["actual"]["evidence_source"] == "program"
        for result in results
    )
    attributed_count = sum(
        bool(result["actual"]["error_type"])
        for result in results
    )
    insufficient_expected = [
        result for result in results
        if result["expected_insufficient_evidence"] is True
    ]
    insufficient_passes = sum(
        result["actual"]["insufficient_evidence"]
        for result in insufficient_expected
    )
    no_evidence_safe = sum(
        result["actual"]["insufficient_evidence"]
        and result["actual"]["error_type"] in ("未归因", "")
        for result in insufficient_expected
    )
    latencies = [result["latency_ms"] for result in results]
    distribution = Counter(
        result["actual"]["error_type"] or "EMPTY"
        for result in results
    )
    failures = [
        {
            "case_id": result["case_id"],
            "expected_program_correct": result["expected_program_correct"],
            "actual": result["actual"],
        }
        for result in results
        if not result["program_match"]
    ]
    return {
        "total_cases": total,
        "program_accuracy": _rate(program_matches, total),
        "attribution_nonempty_rate": _rate(attributed_count, total),
        "fallback_rate": _rate(fallback_count, total),
        "correct_guard_pass_rate": _rate(
            correct_guard_passes, len(correct_cases)
        ),
        "wrong_guard_pass_rate": _rate(
            wrong_guard_passes, len(wrong_cases)
        ),
        "insufficient_evidence_rate": _rate(
            insufficient_passes, len(insufficient_expected)
        ),
        "no_evidence_over_attribution_rate": _rate(
            len(insufficient_expected) - no_evidence_safe,
            len(insufficient_expected),
        ),
        "error_type_distribution": dict(sorted(distribution.items())),
        "latency_ms_avg": round(
            statistics.mean(latencies), 2
        ) if latencies else 0.0,
        "latency_ms_p50": round(
            statistics.median(latencies), 2
        ) if latencies else 0.0,
        "latency_ms_p95": round(
            sorted(latencies)[max(0, int(len(latencies) * 0.95) - 1)],
            2,
        ) if latencies else 0.0,
        "grader_prompt_sha256_12": _prompt_hash(),
        "program_failures": failures,
    }
