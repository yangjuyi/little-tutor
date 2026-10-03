"""LLM 适配器：出题参数填充与批改归因。"""

from __future__ import annotations

import logging
import os
import json
import time
from functools import lru_cache
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.callbacks.usage import get_usage_metadata_callback
from pydantic import BaseModel, Field

from app.domain.grading import (
    DIFFICULTY_CONSTRAINTS,
    STRUCTURE_TAGS,
    build_question_record,
    hard_downgrade_target,
    pick_difficulty,
    validate_difficulty_params,
)
from app.domain.program_grading import compute_program_grade
from app.domain.types import DifficultyLevel, Level


_PROMPT_DIR = Path(__file__).resolve().parent / "prompts"
_TASK_TEMPERATURES = {"question": 0.7, "grade": 0.0}
_DEFAULT_TIMEOUT_SECONDS = 30.0
_DEFAULT_MAX_RETRIES = 2
logger = logging.getLogger(__name__)


class QuestionParams(BaseModel):
    a: float = Field(description="二次项系数 a，不能为0")
    b: float = Field(description="一次项系数 b")
    c: float = Field(description="常数项 c")
    stem_context: str = Field(description="题目的生活情境描述，一句话即可")
    structure_tag: str = Field(
        default="",
        description="难度结构标记：hard 难度必填，其他难度留空",
    )


class AttributionOutput(BaseModel):
    error_type: Literal[
        "审题", "概念", "计算", "跳步", "粗心", "无错", "未归因"
    ] = Field(
        description="错误类型；模型正常归因时从审题/概念/计算/跳步/粗心/无错中选择"
    )
    confidence: float = Field(description="AI 对归因的把握 0-1")
    evidence: str = Field(description="定位到的断点证据，具体到哪一步")
    steps_analyzed: int = Field(description="你实际分析了几步")
    insufficient_evidence: bool = Field(
        description="学生步骤是否不足以定位断点（true = 步骤不够）"
    )


@lru_cache(maxsize=None)
def _load_prompt(name: str) -> str:
    return (_PROMPT_DIR / name).read_text(encoding="utf-8")


def _render_prompt(template: str, values: dict[str, str]) -> str:
    for key, value in values.items():
        template = template.replace("{" + key + "}", str(value))
    return template


def _positive_float_env(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ValueError(f"{name} 必须是正数") from exc
    if value <= 0:
        raise ValueError(f"{name} 必须大于 0")
    return value


def _usage_summary(usage_metadata: dict) -> dict:
    input_tokens = 0
    output_tokens = 0
    for usage in usage_metadata.values():
        input_tokens += int(usage.get("input_tokens") or 0)
        output_tokens += int(usage.get("output_tokens") or 0)
    summary = {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
    }
    input_rate = os.getenv("TUTOR_LLM_INPUT_COST_PER_1M", "").strip()
    output_rate = os.getenv("TUTOR_LLM_OUTPUT_COST_PER_1M", "").strip()
    if input_rate or output_rate:
        try:
            summary["estimated_cost"] = round(
                input_tokens * float(input_rate or 0) / 1_000_000
                + output_tokens * float(output_rate or 0) / 1_000_000,
                8,
            )
        except ValueError:
            summary["estimated_cost_error"] = "invalid cost configuration"
    return summary


def _non_negative_int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} 必须是非负整数") from exc
    if value < 0:
        raise ValueError(f"{name} 不能小于 0")
    return value


@lru_cache(maxsize=None)
def get_llm(task: Literal["question", "grade"] = "question") -> ChatOpenAI:
    if task not in _TASK_TEMPERATURES:
        raise ValueError(f"unknown llm task: {task}")
    load_dotenv()
    return ChatOpenAI(
        model=os.getenv("OPENAI_MODEL", "deepseek-v4-flash"),
        base_url=os.getenv("OPENAI_API_BASE", "https://api.deepseek.com/v1"),
        api_key=os.getenv("OPENAI_API_KEY"),
        temperature=_TASK_TEMPERATURES[task],
        timeout=_positive_float_env(
            "OPENAI_TIMEOUT_SECONDS",
            _DEFAULT_TIMEOUT_SECONDS,
        ),
        max_retries=_non_negative_int_env(
            "OPENAI_MAX_RETRIES",
            _DEFAULT_MAX_RETRIES,
        ),
        extra_body={"thinking": {"type": "disabled"}},
    )


def _difficulty_retry_prompt(error: str, difficulty: DifficultyLevel) -> str:
    bounds = DIFFICULTY_CONSTRAINTS[difficulty]
    structure_note = ""
    if bounds.get("structure_required"):
        structure_note = f"，structure_tag 从 {'/'.join(STRUCTURE_TAGS)} 中选一个"
    return (
        f"刚才的参数不合法（{error}）。请重新生成一道 {difficulty} 难度的题目："
        f"a 为 [{bounds['a_min']}, {bounds['a_max']}] 内的非零整数，"
        f"|b| ≤ {bounds['b_max']}，|c| ≤ {bounds['c_max']}，"
        f"b²-4ac 必须为完全平方数{structure_note}。\n"
        '请严格按以下JSON格式输出：{"a": <数字>, "b": <数字>, "c": <数字>, '
        '"stem_context": "<情境>", "structure_tag": "<结构标记，非hard难度填空字符串>"}'
    )


def generate_question(
    mastery_level: Level,
    kp_name: str,
    llm: ChatOpenAI,
    difficulty: DifficultyLevel | None = None,
    kp_id: str = "math-9-01",
) -> dict:
    difficulty = difficulty or pick_difficulty(mastery_level)
    structured_llm = llm.with_structured_output(QuestionParams, method="json_mode")
    prompt = _render_prompt(
        _load_prompt("question_gen_v1.md"),
        {"kp_name": kp_name, "difficulty": difficulty},
    )
    params = structured_llm.invoke(prompt)

    error = validate_difficulty_params(
        params.a, params.b, params.c, difficulty, params.structure_tag
    )
    if error and difficulty == "hard":
        downgrade = hard_downgrade_target(params.a, params.b, params.c)
        if downgrade:
            difficulty = downgrade
            error = validate_difficulty_params(
                params.a, params.b, params.c, difficulty, params.structure_tag
            )
    if error:
        params = structured_llm.invoke(
            _difficulty_retry_prompt(error, difficulty)
        )
        error = validate_difficulty_params(
            params.a, params.b, params.c, difficulty, params.structure_tag
        )
        if error:
            raise ValueError(f"两次生成参数均不合法：{error}")

    return build_question_record(
        a=params.a,
        b=params.b,
        c=params.c,
        difficulty=difficulty,
        stem_context=params.stem_context,
        structure_tag=params.structure_tag,
        kp_id=kp_id,
    )


def should_skip_attribution(
    program_result: dict,
    student_steps: list,
    *,
    skip: bool = False,
) -> bool:
    """Skip LLM attribution when program facts already leave no error to explain."""
    if skip or not student_steps:
        return True
    return bool(
        program_result.get("final_answer_correct")
        and program_result.get("process_correct")
    )


def _program_facts_payload(program_result: dict) -> str:
    return json.dumps(
        {
            "final_answer_correct": bool(
                program_result.get("final_answer_correct")
            ),
            "process_correct": bool(program_result.get("process_correct")),
            "program_breakpoint": program_result.get("program_breakpoint"),
        },
        ensure_ascii=False,
    )


def build_program_attribution(
    question: dict,
    program_result: dict,
    reason: str,
) -> dict:
    """Build the deterministic fallback used when LLM attribution is unavailable."""
    final_answer_correct = bool(program_result.get("final_answer_correct"))
    process_correct = bool(program_result.get("process_correct"))
    program_breakpoint = program_result.get("program_breakpoint")
    if final_answer_correct and process_correct:
        error_type = "无错"
        confidence = 1.0
        evidence = "程序判定最终答案与过程均正确"
        insufficient_evidence = False
    else:
        error_type = "未归因"
        confidence = 0.0
        evidence = program_breakpoint or reason
        insufficient_evidence = (
            not bool(program_breakpoint)
            and not final_answer_correct
        )
    return {
        "error_type": error_type,
        "error_kp_id": question["kp_id"],
        "confidence": confidence,
        "evidence": evidence,
        "evidence_source": "program",
        "ai_certain": False,
        "teacher_reviewed": False,
        "steps_analyzed": len(program_result.get("steps") or []),
        "insufficient_evidence": insufficient_evidence,
        "program_breakpoint": program_breakpoint,
    }


def _normalize_attribution(
    question: dict,
    student_steps: list,
    program_result: dict,
    attribution: dict,
) -> dict:
    error = dict(attribution)
    error["error_kp_id"] = question["kp_id"]
    error["program_breakpoint"] = program_result.get("program_breakpoint")
    final_answer_correct = bool(program_result.get("final_answer_correct"))
    process_correct = bool(program_result.get("process_correct"))
    program_breakpoint = program_result.get("program_breakpoint")

    if not student_steps and not final_answer_correct:
        error.update({
            "error_type": "未归因",
            "confidence": 0.0,
            "evidence": "学生未提交任何步骤，无法定位断点",
            "evidence_source": "program",
            "ai_certain": False,
            "insufficient_evidence": True,
        })
    elif final_answer_correct and process_correct:
        error.update({
            "error_type": "无错",
            "confidence": 1.0,
            "evidence": "程序判定最终答案与过程均正确",
            "evidence_source": "program",
            "ai_certain": True,
            "insufficient_evidence": False,
        })
    elif program_breakpoint and error.get("error_type") == "无错":
        error.update({
            "error_type": "未归因",
            "confidence": 0.0,
            "evidence": "程序发现中间步骤断点，但 AI 未给出可确认错因",
            "evidence_source": "program",
            "ai_certain": False,
            "insufficient_evidence": False,
        })
    elif not final_answer_correct and error.get("error_type") == "无错":
        error.update({
            "error_type": "计算",
            "confidence": 0.5,
            "evidence": "程序判定最终答案错误，AI 未给出更具体错因",
            "evidence_source": "program",
            "ai_certain": False,
            "insufficient_evidence": True,
        })
    return error


def attribute_error(
    question: dict,
    student_steps: list,
    program_result: dict,
    llm,
) -> dict:
    """Call the LLM for advisory attribution only; never return a verdict field."""
    if should_skip_attribution(program_result, student_steps):
        return build_program_attribution(
            question,
            program_result,
            "程序事实无需额外归因",
        )
    steps_payload = []
    for i, step in enumerate(student_steps):
        payload = {
            "step_no": i + 1,
            "basis": str(step.get("basis") or "")[:200],
            "result": str(step.get("result") or "")[:200],
        }
        if step.get("options"):
            payload["options"] = [
                str(option)[:200] for option in step["options"]
            ]
        if step.get("selected_option_text"):
            payload["selected_option_text"] = str(
                step["selected_option_text"]
            )[:200]
        steps_payload.append(payload)
    steps_json = json.dumps(steps_payload, ensure_ascii=False)
    prompt = _render_prompt(
        _load_prompt("grader_v1.md"),
        {
            "stem": question["stem"],
            "answer": question["answer"],
            "program_facts_json": _program_facts_payload(program_result),
            "steps_json": steps_json,
        },
    )

    structured_llm = llm.with_structured_output(
        AttributionOutput,
        method="json_mode",
    )
    started = time.perf_counter()
    usage_metadata: dict = {}
    try:
        with get_usage_metadata_callback() as usage_callback:
            grade = structured_llm.invoke(prompt)
        usage_metadata = dict(usage_callback.usage_metadata)
    except Exception as exc:
        logger.warning(
            "llm_attribution_failed error=%s duration_ms=%.2f steps=%d "
            "usage=%s",
            exc.__class__.__name__,
            (time.perf_counter() - started) * 1000,
            len(student_steps),
            json.dumps(_usage_summary(usage_metadata), ensure_ascii=False),
        )
        return build_program_attribution(
            question,
            program_result,
            "AI 归因不可用，待老师确认",
        )
    logger.info(
        "llm_attribution_ok duration_ms=%.2f steps=%d evidence_chars=%d "
        "usage=%s",
        (time.perf_counter() - started) * 1000,
        len(student_steps),
        len(grade.evidence or ""),
        json.dumps(_usage_summary(usage_metadata), ensure_ascii=False),
    )

    attribution = {
        "error_type": grade.error_type,
        "error_kp_id": question["kp_id"],
        "confidence": grade.confidence,
        "evidence": grade.evidence,
        "evidence_source": "llm",
        "ai_certain": (
            grade.confidence >= 0.8
            and not grade.insufficient_evidence
        ),
        "teacher_reviewed": False,
        "steps_analyzed": grade.steps_analyzed,
        "insufficient_evidence": grade.insufficient_evidence,
    }
    return _normalize_attribution(
        question,
        student_steps,
        program_result,
        attribution,
    )


def merge_grade_result(program_result: dict, attribution: dict) -> dict:
    """Merge authoritative program facts with advisory attribution."""
    result = dict(program_result)
    kp_id = result.pop("kp_id", None)
    result.pop("program_breakpoint", None)
    error = dict(attribution)
    error.setdefault("error_kp_id", kp_id)
    error.setdefault("program_breakpoint", None)
    error.setdefault("evidence_source", "program")
    error.setdefault("ai_certain", False)
    error.setdefault("teacher_reviewed", False)
    error.setdefault("insufficient_evidence", not result.get("is_correct"))
    result["error"] = error
    return result


def grade_question(question: dict, student_steps: list, llm) -> dict:
    """Compatibility helper for legacy/eval callers; main graph uses split nodes."""
    program_result = compute_program_grade(question, student_steps)
    attribution = attribute_error(
        question,
        student_steps,
        program_result,
        llm,
    )
    return merge_grade_result(program_result, attribution)
