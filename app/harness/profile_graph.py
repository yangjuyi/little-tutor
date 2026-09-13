"""旧版单题画像更新图。"""

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from app.adapters.checkpoint import default_checkpointer
from app.application.teacher_review import persist_review, propose_profile_change
from app.harness.state import TutorState


def profile_update_node(state: TutorState) -> dict:
    """先计算建议，再等待老师决定，最后分别落库。"""
    question = state.get("question") or {}
    if not question.get("id"):
        raise ValueError("profile_update 需要 state['question'] 且携带 id")
    proposal = propose_profile_change(
        state["result"],
        student_id=state["student_id"],
        session_id=state.get("session_id"),
    )
    decision = interrupt({
        "proposal": proposal,
        "question": "请审批画像更新：accept / reject",
    })
    persist_review(
        state["student_id"],
        question,
        state["result"],
        proposal,
        decision,
        state.get("session_id"),
    )
    teacher_decision = "accept" if decision == "accept" else "reject"
    return {
        "batch_profile": proposal,
        "teacher_decision": teacher_decision,
        "phase": "profile",
    }


def build_profile_graph(checkpointer=None):
    graph = StateGraph(TutorState)
    graph.add_node("profile_update", profile_update_node)
    graph.add_edge(START, "profile_update")
    graph.add_edge("profile_update", END)
    return graph.compile(
        checkpointer=checkpointer or default_checkpointer()
    )
