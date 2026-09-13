"""旧版串图 MVP（出题 → 批改 → 画像更新）。

结构：
    START --(phase 路由)--> generate（出题）--> END
    START --(phase 路由)--> grade（批改）--> profile_update（HITL）--> END

两段式流程靠 checkpointer + thread_id 衔接：
第一次 invoke 出题（题目存入图状态），学生作答后第二次 invoke 批改并触发老师审批。
"""

from langgraph.graph import StateGraph, START, END

from app.adapters.checkpoint import default_checkpointer
from app.adapters.llm import generate_question, get_llm, grade_question
from app.domain.answer_template import build_template, first_wrong_blank, judge_blanks
from app.harness.profile_graph import profile_update_node
from app.harness.state import TutorState


def route_by_phase(state: TutorState) -> str:
    """按 phase 路由：出题轮 vs 批改轮"""
    return "grade" if state.get("phase") == "grade" else "generate"


def generate_node(state: TutorState) -> dict:
    """出题节点：画像难度 → 出题 → 写回状态"""
    llm = get_llm("question")
    level = state["profile_snapshot"]["level"]
    q = generate_question(level, state["kp_name"], llm)
    # kp_id 统一为 DB 主键字符串（画像落库要用）
    q["kp_id"] = state["profile_snapshot"]["kp_id"]
    # 模板由程序按题型套路生成（A 定稿）；无 params 的题（题库直采旧数据）退化为最终作答
    template = build_template(q["params"]) if q.get("params") else None
    return {"question": q, "template": template, "phase": "answer"}


def grade_node(state: TutorState) -> dict:
    """批改节点：程序判对错 + AI 归因"""
    result = grade_question(
        state["question"],
        state["student_steps"],
        get_llm("grade"),
    )
    # 模板逐空判定：程序事实（断点定位）并入证据；对错仍由 grade_question 按最终作答判
    template = state.get("template")
    if template:
        blank_results = judge_blanks(template, state["student_steps"])
        result["blank_results"] = blank_results
        breakpoint = first_wrong_blank(blank_results)
        if breakpoint:
            result["error"]["program_breakpoint"] = (
                f"程序定位断点：{breakpoint['blank_id']}（{breakpoint['basis']}）"
            )
    return {"result": result, "phase": "profile"}


def build_tutor_graph(checkpointer=None):
    graph = StateGraph(TutorState)
    graph.add_node("generate", generate_node)
    graph.add_node("grade", grade_node)
    graph.add_node("profile_update", profile_update_node)
    graph.add_conditional_edges(START, route_by_phase, {"generate": "generate", "grade": "grade"})
    graph.add_edge("generate", END)
    graph.add_edge("grade", "profile_update")
    graph.add_edge("profile_update", END)
    # 默认文件级 SqliteSaver（checkpoints.db）；测试可注入 InMemorySaver 隔离
    return graph.compile(checkpointer=checkpointer or default_checkpointer())
