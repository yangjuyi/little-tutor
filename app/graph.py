"""app/graph.py — P1-L6: 串图 MVP（出题 → 批改 → 画像更新）

结构：
    START --(phase 路由)--> generate（L3 出题）--> END
    START --(phase 路由)--> grade（L4 批改）--> profile_update（L5 HITL）--> END

两段式流程靠 checkpointer + thread_id 衔接：
第一次 invoke 出题（黑板存题），学生作答后第二次 invoke 批改并触发老师审批。
"""

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import InMemorySaver

from app.state import TutorState
from app.agents import get_llm, generate_question, grade_question
from app.profile_update import profile_update_node


def route_by_phase(state: TutorState) -> str:
    """按 phase 路由：出题轮 vs 批改轮"""
    return "grade" if state.get("phase") == "grade" else "generate"


def generate_node(state: TutorState) -> dict:
    """出题节点（L3 产出直接接入）：画像难度 → 出题 → 写回黑板"""
    llm = get_llm()
    level = state["profile_snapshot"]["level"]
    q = generate_question(level, state["kp_name"], llm)
    # kp_id 统一为 DB 主键字符串（画像落库要用）
    q["kp_id"] = state["profile_snapshot"]["kp_id"]
    return {"question": q, "phase": "answer"}


def grade_node(state: TutorState) -> dict:
    """批改节点（L4 产出直接接入）：程序判对错 + AI 归因"""
    result = grade_question(state["question"], state["student_steps"], get_llm())
    return {"result": result, "phase": "profile"}


def build_tutor_graph():
    graph = StateGraph(TutorState)
    graph.add_node("generate", generate_node)
    graph.add_node("grade", grade_node)
    graph.add_node("profile_update", profile_update_node)
    graph.add_conditional_edges(START, route_by_phase, {"generate": "generate", "grade": "grade"})
    graph.add_edge("generate", END)
    graph.add_edge("grade", "profile_update")
    graph.add_edge("profile_update", END)
    # InMemorySaver：P1 MVP 用；P2-L1 换 SqliteSaver
    return graph.compile(checkpointer=InMemorySaver())
