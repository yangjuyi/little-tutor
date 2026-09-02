"""Agents: QuestionGenerator (P1-L3) + Grader (P1-L4, future).

Core principle (spec §7): LLM fills parameters, program computes answers.
"""

import random
import math
import os
from pydantic import BaseModel, Field
from typing import Literal, Optional

from langchain_openai import ChatOpenAI

NL = "\n"  # newline shorthand for prompt building

# ========== Pydantic 输出模型 ==========

class QuestionParams(BaseModel):
    """LLM 只负责填参数，不负责算答案（spec §7 红线）"""
    a: float = Field(description="二次项系数 a，不能为0")
    b: float = Field(description="一次项系数 b")
    c: float = Field(description="常数项 c")
    stem_context: str = Field(description="题目的生活情境描述，一句话即可")


class GradeOutput(BaseModel):
    """Grader 的输出结构（P1-L4 用，先定义好）"""
    is_correct: bool = Field(description="学生最终答案是否正确")
    error_type: Literal["审题", "概念", "计算", "跳步", "粗心", "无错"] = Field(
        description="错误类型，从这6个选项中选择"
    )
    confidence: float = Field(description="AI 对归因的把握 0-1")
    evidence: str = Field(description="定位到的断点证据，具体到哪一步")
    steps_analyzed: int = Field(description="你实际分析了几步")
    insufficient_evidence: bool = Field(
        description="学生步骤是否不足以定位断点（true = 步骤不够）"
    )


# ========== 难度混合矩阵（spec §16.5）==========

DIFFICULTY_RATIOS = {
    "weak":   [("simple", 0.6), ("mid", 0.4), ("hard", 0.0)],
    "mid":    [("simple", 0.2), ("mid", 0.5), ("hard", 0.3)],
    "strong": [("simple", 0.1), ("mid", 0.5), ("hard", 0.4)],
}


def pick_difficulty(mastery_level: str) -> str:
    """根据掌握度按混合比例随机选难度（spec §16.5）"""
    options = DIFFICULTY_RATIOS[mastery_level]
    difficulties = [d for d, _ in options]
    weights = [w for _, w in options]
    return random.choices(difficulties, weights=weights, k=1)[0]


# ========== 程序算答案（spec §7 红线）==========

def compute_answer(a: float, b: float, c: float) -> tuple:
    """程序精确计算一元二次方程的解，不让 LLM 算。

    Raises:
        ValueError: a=0 或判别式 < 0
    """
    if a == 0:
        raise ValueError("a 不能为 0，不是二次方程")
    disc = b * b - 4 * a * c
    if disc < 0:
        raise ValueError(f"无实数解：判别式 {disc} < 0")
    x1 = (-b + math.sqrt(disc)) / (2 * a)
    x2 = (-b - math.sqrt(disc)) / (2 * a)
    return (round(x1, 2), round(x2, 2))


def validate_params(a: float, b: float, c: float) -> Optional[str]:
    """先校验参数合法性，再算答案。返回错误消息或 None。"""
    if a == 0:
        return "a 不能为 0"
    disc = b * b - 4 * a * c
    if disc < 0:
        return f"无实数解（判别式 {disc} < 0），请调整参数"
    return None


# ========== LLM 初始化 ==========

def get_llm() -> ChatOpenAI:
    """从 .env 加载配置，初始化 LLM。"""
    from dotenv import load_dotenv
    load_dotenv()

    return ChatOpenAI(
        model=os.getenv("OPENAI_MODEL", "deepseek-v4-flash"),
        base_url=os.getenv("OPENAI_API_BASE", "https://api.deepseek.com/v1"),
        api_key=os.getenv("OPENAI_API_KEY"),
        temperature=0.7,
    )


# ========== 出题 Agent ==========

def generate_question(mastery_level: str, kp_name: str, llm: ChatOpenAI) -> dict:
    """出题：LLM 填参数 → 程序算答案 → 组装 Question。

    Args:
        mastery_level: 学生掌握度（weak/mid/strong）
        kp_name: 知识点名称（如"配方法解一元二次方程"）
        llm: 已初始化的 ChatOpenAI 实例

    Returns:
        dict: 符合 Question TypedDict 的题目数据
    """
    # 1. 随机选难度
    difficulty = pick_difficulty(mastery_level)

    # 2. LLM 填参数（不填答案）
    structured_llm = llm.with_structured_output(QuestionParams, method="json_mode")
    prompt = (
        f"请为初中数学知识点「{kp_name}」出一道{difficulty}难度的一元二次方程题。\n"
        f"要求：给一个简单的生活情境，a不能为0，确保b²-4ac≥0。不要算答案。\n\n"
        f"请严格按以下JSON格式输出（不要输出其他内容）：\n"
        f'{{"a": <二次项系数，数字>, "b": <一次项系数，数字>, "c": <常数项，数字>, '
        f'"stem_context": "<一句话生活情境描述>"}}'
    )

    params = structured_llm.invoke(prompt)

    # 3. 先校验参数合法性
    error = validate_params(params.a, params.b, params.c)
    if error:
        # 重试一次
        params = structured_llm.invoke(
            f"刚才的参数不合法（{error}）。请重新生成，确保 b²-4ac ≥ 0 且 a≠0。\n"
            f'请严格按以下JSON格式输出：{{"a": <数字>, "b": <数字>, "c": <数字>, "stem_context": "<情境>"}}'
        )
        error = validate_params(params.a, params.b, params.c)
        if error:
            raise ValueError(f"两次生成参数均不合法：{error}")

    # 4. 程序算答案
    x1, x2 = compute_answer(params.a, params.b, params.c)

    # 5. 组装题目
    stem = (
        f"{params.stem_context}："
        f"已知方程 {params.a}x² + {params.b}x + {params.c} = 0，"
        f"请用配方法求解 x 的值。"
    )

    return {
        "id": f"q-{random.randint(1000, 9999)}",
        "kp_id": "math-9-01",
        "dep_kp_ids": [],
        "difficulty": difficulty,
        "stem": stem,
        "answer": f"x₁={x1}, x₂={x2}",
        "analysis": (
            f"用配方法：将方程 {params.a}x² + {params.b}x + {params.c} = 0 "
            f"化为标准形式后配方求解。"
        ),
        "images": [],
        "source": "ai_generated",
        "params": {"a": params.a, "b": params.b, "c": params.c},
    }



# ========== 批改 Agent（P1-L4） ==========

def grade_question(question: dict, student_steps: list, llm) -> dict:
    """批改：程序判对错 + AI 复演归因。"""
    # 程序判对错（空答案直接 False，防止空串 in 任何串 = True 的 bug）
    student_final = student_steps[-1]["result"].strip() if student_steps else ""
    is_correct = bool(student_final) and student_final in question["answer"]

    # AI 复演归因
    steps_text = NL.join([
        f"第{i+1}步：依据={s['basis']}，结果={s['result']}"
        for i, s in enumerate(student_steps)
    ])

    prompt = (
        f"你是一个初中数学批改助手。请按以下三把尺子逐步复演学生过程：{NL}"
        f"1. 审题尺：学生是否漏用/误读了题目条件？{NL}"
        f"2. 概念尺：学生是否选错了公式或方法？{NL}"
        f"3. 计算尺：学生是否算错了数值？{NL}{NL}"
        f"题目：{question['stem']}{NL}"
        f"标准答案：{question['answer']}{NL}{NL}"
        f"学生作答步骤：{NL}{steps_text}{NL}{NL}"
        f"规则（严格遵守）：{NL}"
        f"- 只分析学生实际提交的步骤，绝不推断学生未提交的步骤{NL}"
        f"- 如果步骤不足以定位断点，设 insufficient_evidence=true 并降低 confidence{NL}"
        f"- error_type 必须从：审题/概念/计算/跳步/粗心/无错 中选择{NL}"
        f"- 请严格按以下JSON格式输出（不要输出其他内容）：{NL}"
        f'{{"is_correct": <true/false>, "error_type": "<审题/概念/计算/跳步/粗心/无错>", "confidence": <0到1的数字>, "evidence": "<断点定位证据，具体到哪一步>", "steps_analyzed": <你分析了几步，数字>, "insufficient_evidence": <true/false>}}'
    )

    structured_llm = llm.with_structured_output(GradeOutput, method="json_mode")
    grade = structured_llm.invoke(prompt)

    # 程序修正 AI 矛盾
    if is_correct and grade.error_type != "无错":
        grade.error_type = "无错"
        grade.confidence = 1.0

    if not is_correct and grade.error_type == "无错":
        grade.error_type = "计算"
        grade.confidence = 0.5
        grade.insufficient_evidence = True

    # 置信度分流
    ai_certain = grade.confidence >= 0.8 and not grade.insufficient_evidence

    # 组装输出
    return {
        "question_id": question["id"],
        "is_correct": is_correct,
        "error": {
            "error_type": grade.error_type,
            "error_kp_id": question["kp_id"],
            "confidence": grade.confidence,
            "evidence": grade.evidence,
            "evidence_source": "llm",
            "ai_certain": ai_certain,
            "teacher_reviewed": False,
            "steps_analyzed": grade.steps_analyzed,
            "insufficient_evidence": grade.insufficient_evidence,
        },
        "steps": student_steps,
    }
