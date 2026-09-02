"""app/profile_update.py — P1-L5: HITL 画像更新（老师确认后才落库）

设计原则（本课核心）：
1. 纯计算在前 —— AI 建议必须先算好放进 interrupt payload，重跑无害
2. interrupt 居中 —— 暂停等老师，resume 时从这里拿到决定
3. 副作用在后 —— 落库只在 interrupt 之后，且按老师决定分流

运行: python -m app.profile_update
"""

import sys

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import interrupt, Command

from app.state import TutorState
from app.db import (
    init_db,
    SessionLocal,
    Mastery,
    Student,
    KnowledgePoint,
)


def propose_profile_change(result: dict) -> dict:
    """纯函数：根据批改结果给出画像变更建议（重跑无害，所以敢放在 interrupt 前）"""
    wrong = not result["is_correct"]
    return {
        "kp_id": result["error"]["error_kp_id"],
        "wrong_count_delta": 0 if result["is_correct"] else 1,
        "suggest_level": "weak" if wrong else "mid",
        "reason": result["error"]["error_type"],
    }


def apply_to_db(student_id: str, proposal: dict) -> None:
    """副作用：写 mastery 表（wrong_count 累加 + level 更新）"""
    with SessionLocal() as s:
        row = (
            s.query(Mastery)
            .filter_by(student_id=int(student_id), kp_id=int(proposal["kp_id"]))
            .first()
        )
        if row is None:
            row = Mastery(student_id=int(student_id), kp_id=int(proposal["kp_id"]))
            s.add(row)
        row.wrong_count = (row.wrong_count or 0) + proposal["wrong_count_delta"]
        # P1 阶段先直接存 suggest_level，6 级枚举映射留给 P2 持久化课时统一处理
        row.level = proposal["suggest_level"]
        row.last_status = f"批改归因：{proposal['reason']}（老师已确认）"
        s.commit()


def profile_update_node(state: TutorState) -> dict:
    """画像更新节点：先算（纯）→ 再停（interrupt）→ 后写（带分流）"""
    # 1. 纯计算：resume 重跑时这里会再执行一遍，但无副作用
    proposal = propose_profile_change(state["result"])
    # 2. 暂停等老师：第一次执行停在这；resume 时此行直接返回老师的选择
    decision = interrupt({"proposal": proposal, "question": "请审批画像更新：accept / reject"})
    # 3. 副作用：只在 interrupt 之后，且老师 accept 才写库
    if decision == "accept":
        apply_to_db(state["student_id"], proposal)
        return {"batch_profile": proposal, "teacher_decision": "accept", "phase": "profile"}
    return {"batch_profile": proposal, "teacher_decision": "reject", "phase": "profile"}


def build_profile_graph():
    """P1-L5 只组装画像更新单节点；L6 串图时接入 出题→批改→画像更新 全流程"""
    graph = StateGraph(TutorState)
    graph.add_node("profile_update", profile_update_node)
    graph.add_edge(START, "profile_update")
    graph.add_edge("profile_update", END)
    # InMemorySaver 仅用于本课演示；正式版 P2-L1 换 SqliteSaver（进程重启/多实例都能恢复）
    return graph.compile(checkpointer=InMemorySaver())


def _seed() -> tuple[int, int]:
    """初始化并确保演示用的学生和知识点存在，返回 (student_id, kp_id)"""
    init_db()
    with SessionLocal() as s:
        stu = s.query(Student).filter_by(name="杨同学").first()
        if stu is None:
            stu = Student(name="杨同学")
            s.add(stu)
            s.flush()
        kp = s.query(KnowledgePoint).filter_by(kp_name="配方法解一元二次方程").first()
        if kp is None:
            kp = KnowledgePoint(
                subject="数学",
                chapter="一元二次方程",
                kp_name="配方法解一元二次方程",
                concept="通过配方将方程化为 (x+m)²=n 的形式求解",
            )
            s.add(kp)
            s.flush()
        s.commit()
        return stu.id, kp.id


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    student_id, kp_id = _seed()
    graph = build_profile_graph()
    config = {"configurable": {"thread_id": "p1-l5-demo"}}

    # 模拟 L4 批改 Agent 的产出（离线，不调 LLM）：学生答错，AI 归因"计算"
    grade_result = {
        "question_id": "q-1001",
        "is_correct": False,
        "error": {
            "error_type": "计算",
            "error_kp_id": str(kp_id),
            "confidence": 0.9,
            "evidence": "第2步移项符号写反",
            "evidence_source": "llm",
            "ai_certain": True,
            "teacher_reviewed": False,
            "steps_analyzed": 3,
            "insufficient_evidence": False,
        },
        "steps": [],
    }

    print("=== 第1步：invoke，走到画像更新节点会暂停等老师 ===")
    graph.invoke(
        {"student_id": str(student_id), "result": grade_result, "phase": "grade"},
        config,
    )
    snapshot = graph.get_state(config)
    print("待执行节点:", snapshot.next)
    print("暂停点 payload:", snapshot.tasks[0].interrupts[0].value)

    print("\n=== 第2步：老师审批 accept，恢复流程 ===")
    final = graph.invoke(Command(resume="accept"), config)
    print("teacher_decision:", final.get("teacher_decision"))
    print("batch_profile:", final.get("batch_profile"))

    with SessionLocal() as s:
        m = (
            s.query(Mastery)
            .filter_by(student_id=student_id, kp_id=kp_id)
            .first()
        )
        print("\n=== 第3步：验证 DB（老师 accept 后才应有这条记录）===")
        print("mastery: level =", m.level, "| wrong_count =", m.wrong_count, "| last_status =", m.last_status)
