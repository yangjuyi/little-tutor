"""LLM 适配器：出题参数填充与批改归因。"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from app.domain.grading import (
    DIFFICULTY_CONSTRAINTS,
    STRUCTURE_TAGS,
    build_question_record,
    check_is_correct,
    hard_downgrade_target,
    pick_difficulty,
    question_roots,
    validate_difficulty_params,
)
from app.domain.types import DifficultyLevel, Level


NL = "\n"
_PROMPT_DIR = Path(__file__).resolve().parent / "prompts"
_TASK_TEMPERATURES = {"question": 0.7, "grade": 0.0}
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


class GradeOutput(BaseModel):
    is_correct: bool = Field(description="学生最终答案是否正确")
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


def grade_question(question: dict, student_steps: list, llm) -> dict:
    student_final = student_steps[-1]["result"].strip() if student_steps else ""
    is_correct = check_is_correct(student_final, question_roots(question))

    steps_text = NL.join([
        f"第{i + 1}步：依据={step['basis']}，结果={step['result']}"
        for i, step in enumerate(student_steps)
    ])
    prompt = _render_prompt(
        _load_prompt("grader_v1.md"),
        {
            "stem": question["stem"],
            "answer": question["answer"],
            "steps": steps_text,
        },
    )

    structured_llm = llm.with_structured_output(GradeOutput, method="json_mode")
    try:
        grade = structured_llm.invoke(prompt)
    except Exception as exc:
        logger.warning("LLM grading failed: %s", exc.__class__.__name__)
        grade = GradeOutput(
            is_correct=is_correct,
            error_type="无错" if is_correct else "未归因",
            confidence=0.0,
            evidence="AI 归因不可用，待老师确认",
            steps_analyzed=len(student_steps),
            insufficient_evidence=not is_correct,
        )
        evidence_source = "program"
    else:
        evidence_source = "llm"

    if not student_steps and not is_correct:
        grade.error_type = "未归因"
        grade.confidence = 0.0
        grade.evidence = "学生未提交任何步骤，无法定位断点"
        grade.insufficient_evidence = True
    if is_correct and grade.error_type != "无错":
        grade.error_type = "无错"
        grade.confidence = 1.0
    if not is_correct and grade.error_type == "无错":
        grade.error_type = "计算"
        grade.confidence = 0.5
        grade.insufficient_evidence = True

    return {
        "question_id": question["id"],
        "is_correct": is_correct,
        "error": {
            "error_type": grade.error_type,
            "error_kp_id": question["kp_id"],
            "confidence": grade.confidence,
            "evidence": grade.evidence,
            "evidence_source": evidence_source,
            "ai_certain": grade.confidence >= 0.8 and not grade.insufficient_evidence,
            "teacher_reviewed": False,
            "steps_analyzed": grade.steps_analyzed,
            "insufficient_evidence": grade.insufficient_evidence,
        },
        "steps": student_steps,
    }
