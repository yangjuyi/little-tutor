"""端到端冒烟：真实 LLM 跑通 Web 全流程（手动运行，不进自动化测试）.

运行: .venv/Scripts/python -X utf8 scripts/e2e_smoke.py
      [题量, 默认 2] [accept|reject, 默认 accept] [correct|wrong, 默认 correct]
链路: 开会话 → 组卷预审定稿 → 逐题作答（correct 全对；wrong 首题错、其余对）
→ 会话汇总 → H3 批量确认 → 落库断言。
"""

import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

def _correct_answers(params: dict) -> dict:
    from app.domain.answer_template import build_template

    template = build_template(params)
    return {
        blank["id"]: (
            str(blank["answer_index"] + 1)
            if blank["kind"] == "choice"
            else f"{blank['expected']:g}"
        )
        for blank in template["blanks"]
    }


def _wrong_answers(params: dict) -> dict:
    """把首题的首个最终答案空位改错，保证程序判分命中错误分支。"""
    from app.domain.answer_template import build_template

    template = build_template(params)
    answers = _correct_answers(params)
    answer_ids = template.get("answer_blank_ids") or [template["blanks"][-1]["id"]]
    target = next(
        blank for blank in template["blanks"] if blank["id"] == answer_ids[0]
    )
    if target["kind"] == "choice":
        options = target.get("options") or []
        correct_index = int(target["answer_index"] or 0)
        wrong_index = (correct_index + 1) % len(options)
        answers[target["id"]] = str(wrong_index + 1)
    else:
        answers[target["id"]] = f"{float(target['expected']) + 1:g}"
    return answers


def main() -> None:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    count = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    decision = sys.argv[2].strip().lower() if len(sys.argv) > 2 else "accept"
    if decision not in ("accept", "reject"):
        raise SystemExit("decision 必须是 accept 或 reject")
    answer_mode = sys.argv[3].strip().lower() if len(sys.argv) > 3 else "correct"
    if answer_mode not in ("correct", "wrong"):
        raise SystemExit("answer_mode 必须是 correct 或 wrong")
    with tempfile.TemporaryDirectory(prefix="little-tutor-smoke-") as temp_dir:
        os.environ["TUTOR_DB_PATH"] = str(Path(temp_dir) / "tutor.db")
        os.environ["TUTOR_CHECKPOINT_PATH"] = str(Path(temp_dir) / "checkpoints.db")

        from fastapi.testclient import TestClient

        from app.adapters.checkpoint import close_default_checkpointer
        from app.adapters.persistence import (
            AnswerRecord,
            Mastery,
            PracticeSessionRecord,
            SessionLocal,
            TeacherDecision,
            engine,
        )
        from app.application.student_practice import get_graph
        from app.web import app

        try:
            _run_smoke(
                client_factory=TestClient, app=app, graph_factory=get_graph,
                count=count, session_factory=SessionLocal,
                record_type=AnswerRecord, mastery_type=Mastery,
                decision_type=TeacherDecision,
                session_type=PracticeSessionRecord,
                decision=decision, answer_mode=answer_mode,
            )
        finally:
            close_default_checkpointer()
            engine.dispose()


def _run_smoke(
    client_factory, app, graph_factory, count: int, session_factory,
    record_type, mastery_type, decision_type, session_type, decision,
    answer_mode: str = "correct",
) -> None:

    client = client_factory(app)
    t0 = time.time()

    r = client.post("/start", data={"count": str(count)}, follow_redirects=False)
    assert r.status_code == 303, f"/start 失败: {r.status_code}"
    print(f"[1/6] 开会话 OK（{time.time() - t0:.1f}s）")

    t = time.time()
    r = client.get("/teacher/review")
    assert r.status_code == 200 and "组卷预审" in r.text, "预审页异常"
    print(f"[2/6] H1 预审页 OK（{time.time() - t:.1f}s）")

    t = time.time()
    r = client.post(
        "/teacher/review",
        data={"decision": "approve"},
        follow_redirects=False,
    )
    assert r.status_code == 303, f"定稿失败: {r.status_code} {r.headers}"
    print(f"[3/6] H1 定稿 OK（{time.time() - t:.1f}s，含 LLM 生成则为秒级以上）")

    thread = client.cookies.get("thread_id")
    config = {"configurable": {"thread_id": thread}}
    for idx in range(count):
        question = graph_factory().get_state(
            config
        ).values["approved_questions"][idx]
        t = time.time()
        page = client.get(f"/answer/{idx}")
        assert page.status_code == 200, f"/answer/{idx} 异常: {page.status_code}"
        answers = (
            _wrong_answers(question["params"])
            if answer_mode == "wrong" and idx == 0
            else _correct_answers(question["params"])
        )
        r = client.post(f"/answer/{idx}", data=answers, follow_redirects=False)
        assert r.status_code == 303, f"作答提交失败: {r.status_code}"
        next_location = (
            f"/answer/{idx + 1}"
            if idx + 1 < count
            else f"/answer/{count}"
        )
        assert r.headers["location"] == next_location, "未连续进入下一题"
        feedback = client.get(f"/feedback/{idx}")
        result = client.get(f"/result/{idx}")
        if answer_mode == "wrong" and idx == 0:
            assert "程序判分：错误" in feedback.text, "错误题即时反馈异常"
            assert "程序初评：错误" in result.text, "错误题判分异常"
            assert "AI 归因" not in feedback.text, "学生即时反馈不应展示 AI 归因"
        else:
            assert "程序判分：正确" in feedback.text, f"第 {idx + 1} 题即时反馈异常"
            assert "程序初评：正确" in result.text, f"第 {idx + 1} 题判分异常"
        print(
            f"[4/6] 第 {idx + 1} 题作答+批改 OK"
            f"（{time.time() - t:.1f}s，LLM 可用则归因，"
            f"不可用则按程序事实兜底）"
        )

    t = time.time()
    r = client.post("/summarize", follow_redirects=False)
    assert r.status_code == 303, f"汇总触发失败: {r.status_code}"
    assert r.headers["location"] == "/waiting-confirmation"
    summary = client.get("/teacher/summary")
    assert "本次练习结果确认" in summary.text, "汇总页异常"
    print(f"[5/6] 会话汇总 OK（{time.time() - t:.1f}s）")

    r = client.post(
        "/teacher/summary",
        data={"decision": decision},
        follow_redirects=False,
    )
    assert r.status_code == 303
    assert r.headers["location"] == "/teacher/completed"
    done = client.get("/done")
    if decision == "accept":
        assert "学生画像已更新" in done.text, "H3 accept 落库异常"
    else:
        assert "本次未更新学生画像" in done.text, "H3 reject 分流异常"

    with session_factory() as s:
        answer_records = s.query(record_type).all()
        records = len(answer_records)
        decisions = s.query(decision_type).count()
        mastery = s.query(mastery_type).all()
        practice_session = s.get(session_type, thread)
    for answer in answer_records:
        assert answer.attempt_no == 1, "首次作答 attempt_no 异常"
        assert answer.first_attempt_correct == answer.is_correct, "首次作答结果未落库"
        assert answer.hint_count == 0, "当前阶段不应有提示计数"
        assert answer.scaffold_level == 0, "当前阶段不应有脚手架计数"
        assert answer.assistance_level == "independent", "独立作答等级异常"
    if answer_mode == "wrong":
        wrong_records = [answer for answer in answer_records if not answer.is_correct]
        assert wrong_records, "错误作答未落库"
        assert wrong_records[0].error_type, "错误作答缺少 error_type 归因结果"
        print(f"错误作答归因：{wrong_records[0].error_type}")
    if decision == "accept":
        assert len(mastery) == 1, "accept 后 mastery 未写入"
        assert practice_session.review_status == "accepted"
    else:
        assert len(mastery) == 0, "reject 后 mastery 不应写入"
        assert practice_session.review_status == "rejected"
    print(f"[6/6] H3 确认+落库 OK：answer_records={records}，"
          f"teacher_decisions={decisions}，mastery={[(m.level, m.confidence) for m in mastery]}，"
          f"review={practice_session.review_status}")
    print(
        f"\n✅ 端到端冒烟通过（{decision}/{answer_mode}），"
        f"总耗时 {time.time() - t0:.1f}s（thread_id={thread}）"
    )


if __name__ == "__main__":
    main()

