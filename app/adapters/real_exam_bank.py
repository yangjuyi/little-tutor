"""Load local real-exam data and structured specs."""

from __future__ import annotations

import json
import re
from pathlib import Path

from app.domain.exam.specs import build_exam_spec_from_dict
from app.domain.exam.registry import solve_exam_spec
from app.domain.question_materialization import materialize_question


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BANK = ROOT / "data" / "private_questions" / "middle_exam_math.json"
DEFAULT_GROWTH_SPECS = (
    ROOT / "data" / "private_questions" / "real_exam_growth_specs.json"
)
DEFAULT_ALGEBRA_SPECS = (
    ROOT / "data" / "private_questions" / "real_exam_algebra_specs.json"
)
DEFAULT_MULTIPART_SPECS = (
    ROOT / "data" / "private_questions" / "real_exam_multipart_specs.json"
)


def _extract_choices(stem: str) -> list[str]:
    matches = re.findall(
        r"([ABCD])\.\s*(.*?)(?=\s+[ABCD]\.\s*|$)",
        str(stem or ""),
    )
    return [text.strip() for _, text in matches]


def load_question_bank(path: Path = DEFAULT_BANK) -> dict:
    if not path.exists():
        return {"questions": []}
    return json.loads(path.read_text(encoding="utf-8"))


def load_growth_specs(path: Path = DEFAULT_GROWTH_SPECS) -> list[dict]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload.get("items") or []


def load_algebra_specs(path: Path = DEFAULT_ALGEBRA_SPECS) -> list[dict]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload.get("items") or []


def load_multipart_specs(path: Path = DEFAULT_MULTIPART_SPECS) -> list[dict]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload.get("items") or []


def build_exam_spec(item: dict):
    return build_exam_spec_from_dict(item["spec"])


def load_growth_main_chain_questions(kp_id: int) -> list[dict]:
    """Build main-chain question records from the private growth-rate suite."""
    bank = load_question_bank()
    questions = {
        question["id"]: question
        for question in bank.get("questions") or []
    }
    records: list[dict] = []
    for item in load_growth_specs():
        source = questions.get(item["question_id"])
        if source is None:
            continue
        spec_payload = dict(item["spec"])
        target = item.get("target") or spec_payload.get("target", "rate")
        solution = solve_exam_spec(build_exam_spec(item))
        choices = _extract_choices(source["stem"])
        source_answer = str(source.get("answer") or "").strip().upper()
        response_type = (
            "rate_value"
            if target == "rate"
            else "equation_value"
        )
        if (
            len(choices) == 4
            and source_answer in {"A", "B", "C", "D"}
        ):
            response_type = "multiple_choice"
        params = {
            "question_type": spec_payload["type"],
            "exam_spec": spec_payload,
            "target": target,
            "response_type": response_type,
            "choices": choices if response_type == "multiple_choice" else [],
            "correct_choice": (
                source_answer
                if response_type == "multiple_choice"
                else ""
            ),
            "presentation": "exam",
            "source_question_id": item["question_id"],
            "source_type": source.get("source_type"),
            "year": source.get("year"),
            "province": source.get("province"),
            "source_url": source.get("source_url"),
        }
        record = {
            "kp_id": str(kp_id),
            "stem": source["stem"],
            "answer": str(solution["answer"]),
            "analysis": (
                f"按平均变化率模型列出 {solution.get('equation', '')}，"
                f"程序求得符合实际意义的答案。"
            ),
            "difficulty": item.get("difficulty", "simple"),
            "source": "private",
            "params": params,
        }
        records.append(
            materialize_question(record, regenerate_analysis=True)
        )
    for item in load_multipart_specs():
        source = questions.get(item["question_id"])
        if source is None:
            continue
        params = {
            "question_type": "growth_application",
            "parts": item["parts"],
            "presentation": "exam",
            "source_question_id": item["question_id"],
            "source_type": source.get("source_type"),
            "year": source.get("year"),
            "province": source.get("province"),
            "source_url": source.get("source_url"),
        }
        record = {
            "kp_id": str(kp_id),
            "stem": source["stem"],
            "answer": "",
            "analysis": "",
            "difficulty": item.get("difficulty", "hard"),
            "source": "private",
            "params": params,
        }
        records.append(
            materialize_question(record, regenerate_analysis=True)
        )
    return records
