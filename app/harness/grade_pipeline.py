"""Program grading and advisory attribution subgraph."""

from __future__ import annotations

from typing import Optional, TypedDict

from langgraph.graph import END, START, StateGraph

from app.adapters.llm import (
    attribute_error,
    build_program_attribution,
    get_llm,
    merge_grade_result,
    should_skip_attribution,
)
from app.adapters.review_store import record_answer
from app.domain.program_grading import compute_program_grade


class GradeState(TypedDict):
    """子图只认这几个键；与主图 SessionState 以共享键衔接"""

    student_id: str
    session_id: Optional[str]
    llm_error: Optional[str]
    current_question: dict
    template: Optional[dict]
    student_steps: list
    attempt_no: int
    assistance_level: Optional[str]
    hint_count: int
    scaffold_level: int
    skip: bool
    program_result: Optional[dict]
    attribution: Optional[dict]
    result: Optional[dict]


def _grade_compute_node(state: GradeState) -> dict:
    """Pure program grading: no LLM call and no attribution text."""
    if state.get("skip"):
        question = state["current_question"]
        result = {
            "question_id": question["id"],
            "is_correct": False,
            "final_answer_correct": False,
            "process_correct": False,
            "steps": [],
            "program_breakpoint": "学生选择跳过本题",
        }
    else:
        result = compute_program_grade(
            state["current_question"],
            state["student_steps"],
            state.get("template"),
        )
    result["difficulty"] = state["current_question"].get("difficulty")
    result["attempt_no"] = int(state.get("attempt_no") or 1)
    result["assistance_level"] = (
        "skipped"
        if state.get("skip")
        else state.get("assistance_level") or "independent"
    )
    result["hint_count"] = int(state.get("hint_count") or 0)
    result["scaffold_level"] = int(state.get("scaffold_level") or 0)
    return {"program_result": result}


def _program_attribution_fallback_node(state: GradeState) -> dict:
    if state.get("skip"):
        reason = "学生选择跳过本题，未形成作答证据"
    elif not state.get("student_steps"):
        reason = "学生未提交任何步骤，无法定位断点"
    else:
        reason = "程序事实无需额外归因"
    return {
        "attribution": build_program_attribution(
            state["current_question"],
            state["program_result"] or {},
            reason,
        )
    }


def _attribute_error_node(state: GradeState) -> dict:
    try:
        attribution = attribute_error(
            state["current_question"],
            state["student_steps"],
            state["program_result"] or {},
            get_llm("grade"),
        )
    except Exception:
        attribution = build_program_attribution(
            state["current_question"],
            state["program_result"] or {},
            "AI 归因不可用，待老师确认",
        )
    return {"attribution": attribution}


def _merge_grade_result_node(state: GradeState) -> dict:
    return {
        "result": merge_grade_result(
            state["program_result"] or {},
            state["attribution"] or {},
        )
    }


def _route_after_grade_compute(state: GradeState) -> str:
    return (
        "attribution_fallback"
        if should_skip_attribution(
            state["program_result"] or {},
            state.get("student_steps") or [],
            skip=bool(state.get("skip")),
        )
        else "attribute_error"
    )


def _validate_grade_input_node(state: GradeState) -> dict:
    """批改子图入口守卫：拒绝脏 checkpoint 进入内部计算。"""
    if not state.get("current_question"):
        return {"llm_error": "批改输入缺少 current_question"}
    steps = state.get("student_steps")
    if steps is None or not isinstance(steps, list):
        return {"llm_error": "批改输入缺少合法 student_steps"}
    return {"llm_error": None}


def _grade_failed_node(state: GradeState) -> dict:
    """批改子图失败汇点：错误通过共享 llm_error 返回主图。"""
    return {}


def _route_after_grade_input(state: GradeState) -> str:
    return "failed" if state.get("llm_error") else "grade_compute"


def _record_fact_node(state: GradeState) -> dict:
    """事实当轮落库（§16.2：单题循环内写 answer_record，带 session_id）"""
    record_answer(
        state["student_id"],
        state["current_question"],
        state["result"],
        state.get("session_id"),
        attempt_no=int(state.get("attempt_no") or 1),
        hint_count=int(state.get("hint_count") or 0),
        scaffold_level=int(state.get("scaffold_level") or 0),
    )
    return {}


grade_pipeline = (
    StateGraph(GradeState)
    .add_node("validate_input", _validate_grade_input_node)
    .add_node("compute_program_grade", _grade_compute_node)
    .add_node("attribute_error", _attribute_error_node)
    .add_node("attribution_fallback", _program_attribution_fallback_node)
    .add_node("merge_grade_result", _merge_grade_result_node)
    .add_node("record_fact", _record_fact_node)
    .add_node("failed", _grade_failed_node)
    .add_edge(START, "validate_input")
    .add_conditional_edges(
        "validate_input",
        _route_after_grade_input,
        {
            "grade_compute": "compute_program_grade",
            "failed": "failed",
        },
    )
    .add_conditional_edges(
        "compute_program_grade",
        _route_after_grade_compute,
        {
            "attribute_error": "attribute_error",
            "attribution_fallback": "attribution_fallback",
        },
    )
    .add_edge("attribute_error", "merge_grade_result")
    .add_edge("attribution_fallback", "merge_grade_result")
    .add_edge("merge_grade_result", "record_fact")
    .add_edge("record_fact", END)
    .add_edge("failed", END)
    .compile()
)
