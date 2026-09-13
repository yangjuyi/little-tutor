"""会话制 CLI（C 会话级图）。

流程：组卷(H1 预审，interrupt①) → 连续作答×N（程序批改，零打断，对错当场可见）
→ 会话汇总 → 批量画像确认(H3，interrupt②)。
运行: python -m app.run_mvp
"""

import sys

from langgraph.types import Command

from app.adapters.persistence import (
    init_db,
    SessionLocal,
    Student,
    KnowledgePoint,
    Question as QuestionRow,
)
from app.domain.answer_template import build_template
from app.harness.session_graph import build_session_graph


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


def _persist_question(kp_id: str, question: dict) -> None:
    """AI 变式题落库换真实主键：answer_records 外键需要它"""
    with SessionLocal() as s:
        row = QuestionRow(
            kp_id=int(kp_id),
            stem=question["stem"],
            answer=question["answer"],
            analysis=question.get("analysis"),
            difficulty=question.get("difficulty", "simple"),
            source="ai_generated",
            params=question.get("params"),
        )
        s.add(row)
        s.commit()
        question["id"] = row.id


def _collect_steps(template: dict | None) -> list[dict]:
    """按模板逐空作答；无模板（旧数据）退化为最终作答。根空位拼装最终作答。"""
    if not template:
        answer = input("学生作答（最终答案，如 x1=1, x2=-3）: ").strip()
        return [{"basis": "最终作答", "result": answer}]
    print("\n请按步骤作答（选择填序号，填空填数值）：")
    steps = []
    for i, blank in enumerate(template["blanks"]):
        if blank["kind"] == "choice":
            options = "\n".join(
                f"   {j + 1}. {option}"
                for j, option in enumerate(blank["options"])
            )
            print(f"第{i + 1}步 {blank['basis']}\n{options}")
        else:
            print(f"第{i + 1}步 {blank['basis']}")
        steps.append(
            {"basis": blank["basis"], "result": input("   你的作答: ").strip()}
        )
    # 按模板声明的答案空位拼装最终作答，兼容题面只有一个有效根的应用题
    by_id = {
        blank["id"]: step["result"]
        for blank, step in zip(template["blanks"], steps)
    }
    answer_ids = template.get("answer_blank_ids") or [
        blank["id"] for blank in template["blanks"][-2:]
    ]
    roots = [by_id[blank_id] for blank_id in answer_ids]
    final_answer = (
        f"x={roots[0]}" if len(roots) == 1
        else f"x1={roots[0]}, x2={roots[1]}"
    )
    steps.append({"basis": "最终作答", "result": final_answer})
    return steps


def _show_candidates(payload: dict) -> None:
    print("\n===== H1 组卷预审 =====")
    if payload.get("validation_error"):
        print(f"上次修改未通过：{payload['validation_error']}")
    for c in payload["candidates"]:
        print(f"  {c['index']}. [{c['difficulty']}] {c['stem']}")
        print(f"      （程序答案：{c['answer']}）")
    print("动作：approve（定稿）/ swap:序号（换题）/ regroup:意图（重新组）")


def _llm_error(graph, config) -> str | None:
    """LLM 异常兜底标记（P2）：有则提示重试，图已正常收束不炸进程"""
    return graph.get_state(config).values.get("llm_error")


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    student_id, kp_id = _seed()
    graph = build_session_graph()
    thread = input("会话 ID（回车默认 mvp-1）: ").strip() or "mvp-1"
    count_raw = input("本次题量（回车默认 10）: ").strip()
    question_count = int(count_raw) if count_raw else 10
    config = {"configurable": {"thread_id": thread}}

    # H1：组卷 + 预审循环（interrupt①；swap/regroup 回审直到定稿）
    graph.invoke(
        {
            "student_id": student_id,
            "kp_id": kp_id,
            "kp_name": "配方法解一元二次方程",
            "session_id": thread,
            "question_count": question_count,
            "phase": "assemble",
        },
        config,
    )
    error = _llm_error(graph, config)
    if error:
        print(f"\n组卷失败：{error}\n请检查 LLM 配置/网络后重开会话。")
        return
    while graph.get_state(config).next:
        payload = graph.get_state(config).tasks[0].interrupts[0].value
        _show_candidates(payload)
        decision = input("老师预审: ").strip()
        graph.invoke(Command(resume=decision), config)
        error = _llm_error(graph, config)
        if error:
            print(f"\n组卷失败：{error}\n请检查 LLM 配置/网络后重开会话。")
            return

    questions = graph.get_state(config).values["approved_questions"]
    # 定稿题目换真实主键：AI 变式题不在库中；种子题自带库主键
    for q in questions:
        if not isinstance(q["id"], int):
            _persist_question(kp_id, q)

    # 单题循环：作答 + 程序批改（零打断），对错当场可见（B4）
    round_no = 0
    for question in questions:
        round_no += 1
        print(f"\n===== 第 {round_no}/{len(questions)} 题 =====")
        print(question["stem"])
        template = (
            build_template(question["params"]) if question.get("params") else None
        )
        steps = _collect_steps(template)
        graph.invoke(
            {
                "student_id": student_id,
                "session_id": thread,
                "current_question": question,
                "template": template,
                "student_steps": steps,
                "phase": "grade_round",
            },
            config,
        )
        error = _llm_error(graph, config)
        if error:
            print(f"\n批改失败：{error}")
            return
        result = graph.get_state(config).values["round_results"][-1]
        print(f"程序初评：{'正确' if result['is_correct'] else '错误'}")
        breakpoint = result["error"].get("program_breakpoint")
        if breakpoint:
            print(breakpoint)

    # H3：会话汇总 + 批量画像确认（interrupt②）
    graph.invoke(
        {"student_id": student_id, "session_id": thread, "phase": "summarize"},
        config,
    )
    payload = graph.get_state(config).tasks[0].interrupts[0].value
    level_labels = {"weak": "需要加强", "mid": "基本掌握", "strong": "掌握较好"}
    print("\n===== 本次练习结果确认 =====")
    for p in payload["proposals"]:
        print(f"  知识点：{p['kp_name']}")
        print(
            f"  本次练习：{p['round_count']} 题，答对 {p['correct_count']} 题"
            f"（正确率 {p['session_rate']:.0%}）"
        )
        print(f"  系统建议：{level_labels[p['suggest_level']]}")
        print(f"  判断依据：{p['evidence']}")
    while True:
        decision = input("确认更新画像请输入 accept，暂不更新输入 reject: ").strip().lower()
        if decision in ("accept", "reject"):
            break
        print("请输入 accept 或 reject（不设默认值，防止误操作）")
    final = graph.invoke(Command(resume=decision), config)
    print(
        "老师决定:", final.get("h3_decision"),
        "| 批量画像已生效" if decision == "accept" else "| 画像未改动（事实已留痕）",
    )
    print(f"本次会话共 {round_no} 题，thread_id = {thread}，再见！")


if __name__ == "__main__":
    main()
