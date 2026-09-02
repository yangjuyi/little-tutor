"""app/run_mvp.py — P1-L6: MVP 多轮 CLI

流程：出题 → 学生作答 → 批改 → 老师审批画像 → 下一题（同一 thread_id 续会话）
运行: python -m app.run_mvp
"""

import sys

from langgraph.types import Command

from app.graph import build_tutor_graph
from app.db import init_db, SessionLocal, Student, KnowledgePoint


def _seed() -> tuple[str, str]:
    """确保学生和知识点存在，返回 (student_id, kp_id) 字符串"""
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
        return str(stu.id), str(kp.id)


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    student_id, kp_id = _seed()
    graph = build_tutor_graph()
    thread = input("会话 ID（回车默认 mvp-1）: ").strip() or "mvp-1"
    config = {"configurable": {"thread_id": thread}}

    round_no = 0
    while True:
        round_no += 1
        print(f"\n===== 第 {round_no} 轮 · 出题 =====")
        graph.invoke(
            {
                "student_id": student_id,
                "kp_name": "配方法解一元二次方程",
                "profile_snapshot": {"kp_id": kp_id, "level": "weak", "confidence": 0.5, "evidence": "MVP 初始画像"},
                "phase": "generate",
            },
            config,
        )
        question = graph.get_state(config).values["question"]
        print(question["stem"])

        answer = input("学生作答（最终答案，如 x1=1, x2=-3）: ").strip()
        print("\n===== 批改 + 画像更新 =====")
        graph.invoke(
            {
                "student_steps": [{"basis": "最终作答", "result": answer}],
                "phase": "grade",
            },
            config,
        )

        snapshot = graph.get_state(config)
        payload = snapshot.tasks[0].interrupts[0].value
        print("AI 画像建议:", payload["proposal"])
        decision = input("老师审批（accept/reject，回车默认 accept）: ").strip() or "accept"
        final = graph.invoke(Command(resume=decision), config)
        print("老师决定:", final.get("teacher_decision"), "| 画像建议已生效" if decision == "accept" else "| 画像未改动")

        if input("\n继续下一题？（y 回车继续，其他退出）: ").strip().lower() not in ("y", ""):
            print(f"本次会话共 {round_no} 轮，thread_id = {thread}，再见！")
            break


if __name__ == "__main__":
    main()
