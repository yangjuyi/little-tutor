"""学生练习用例。

该层编排一次完整练习，不依赖 FastAPI。HTTP 状态、模板渲染和跳转由 Web 层处理。
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from contextlib import contextmanager

from langgraph.types import Command

import app.adapters.persistence as db
import app.adapters.session_store as session_store
from app.adapters.checkpoint import default_checkpointer
from app.domain.answer_template import build_template
from app.harness.hints import build_hint, build_scaffold
from app.harness.session_graph import build_session_graph


class PracticeBusy(RuntimeError):
    """同一会话已有写操作执行中。"""


_COMPILED = None


def reset_runtime() -> None:
    """重置进程内图实例，供测试或运行时重载使用。"""
    global _COMPILED
    _COMPILED = None


def _get_graph():
    global _COMPILED
    if _COMPILED is None:
        _COMPILED = build_session_graph(default_checkpointer())
    return _COMPILED


def get_graph():
    """返回当前进程使用的编译图。"""
    return _get_graph()


def _config(thread_id: str) -> dict:
    return {"configurable": {"thread_id": thread_id}}


@contextmanager
def _session_guard(thread_id: str):
    """通过数据库租约串行化同一会话的写操作。"""
    if not session_store.acquire_practice_lease(thread_id):
        raise PracticeBusy(thread_id)
    try:
        yield
    finally:
        session_store.release_practice_lease(thread_id)


def _parse_count(raw: str) -> int:
    try:
        return int(raw) if raw.strip() else 10
    except ValueError:
        return 10


def ensure_student_kp(student_id: str | None = None) -> tuple[str, str]:
    """解析长期学生身份和当前主知识点，缺失时按演示口径创建。"""
    db.init_db()
    with db.SessionLocal() as s:
        student = None
        if student_id:
            try:
                student = s.get(db.Student, int(student_id))
            except ValueError:
                student = None
        if student is None:
            student = s.query(db.Student).filter_by(name="杨同学").first()
        if student is None:
            student = db.Student(name="杨同学")
            s.add(student)
            s.flush()
        kp = (
            s.query(db.KnowledgePoint)
            .filter_by(kp_name="配方法解一元二次方程")
            .first()
        )
        if kp is None:
            kp = db.KnowledgePoint(
                subject="数学",
                chapter="一元二次方程",
                kp_name="配方法解一元二次方程",
                concept="通过配方将方程化为 (x+m)²=n 的形式求解",
            )
            s.add(kp)
            s.flush()
        s.commit()
        return str(student.id), str(kp.id)


def start_practice(student_id: str | None, count: str) -> dict:
    """创建并启动一场新练习。"""
    resolved_student_id, kp_id = ensure_student_kp(student_id)
    thread_id = f"web-{uuid.uuid4().hex[:8]}"
    session_store.start_practice_session(
        thread_id,
        int(resolved_student_id),
        int(kp_id),
    )
    with _session_guard(thread_id):
        _get_graph().invoke(
            {
                "student_id": resolved_student_id,
                "kp_id": kp_id,
                "kp_name": "配方法解一元二次方程",
                "session_id": thread_id,
                "question_count": _parse_count(count),
                "phase": "assemble",
            },
            _config(thread_id),
        )
    return {"student_id": resolved_student_id, "thread_id": thread_id}


def load_review(thread_id: str) -> dict:
    """读取组卷预审页面所需状态。"""
    snap = _get_graph().get_state(_config(thread_id))
    if snap.values.get("llm_error"):
        return {"kind": "error", "message": snap.values["llm_error"]}
    if snap.next:
        task = next((task for task in snap.tasks if task.interrupts), None)
        if task is None:
            return {"kind": "waiting"}
        payload = task.interrupts[0].value
        ratios = snap.values.get("difficulty_ratios") or {
            "simple": 40,
            "mid": 40,
            "hard": 20,
        }
        return {
            "kind": "review",
            "candidates": payload["candidates"],
            "simple_ratio": ratios.get("simple", 0),
            "mid_ratio": ratios.get("mid", 0),
            "hard_ratio": ratios.get("hard", 0),
            "error_message": payload.get("validation_error"),
        }
    if snap.values.get("phase") == "answer":
        return {
            "kind": "redirect_answer",
            "answered": len(snap.values.get("round_results") or []),
        }
    return {"kind": "redirect_home"}


def resume_review(thread_id: str, decision: str) -> dict:
    """提交预审决定并返回下一步位置。"""
    with _session_guard(thread_id):
        _get_graph().invoke(Command(resume=decision), _config(thread_id))
        snap = _get_graph().get_state(_config(thread_id))
    if snap.next:
        return {"kind": "review"}
    return {
        "kind": "answer",
        "answered": len(snap.values.get("round_results") or []),
    }


def swap_question(thread_id: str, number: str) -> None:
    """按题号换题。"""
    with _session_guard(thread_id):
        _get_graph().invoke(
            Command(resume=f"swap:{number.strip()}"), _config(thread_id)
        )


def edit_question(
    thread_id: str,
    number: str,
    stem: str,
    a: float,
    b: float,
    c: float,
    structure_tag: str = "",
) -> None:
    """保存老师对预审题干的修改，并返回预审页继续确认。"""
    with _session_guard(thread_id):
        _get_graph().invoke(
            Command(resume={
                "action": "edit",
                "index": int(number),
                "stem": stem,
                "a": a,
                "b": b,
                "c": c,
                "structure_tag": structure_tag,
            }),
            _config(thread_id),
        )


def regroup_ratios(thread_id: str, simple_r: int, mid_r: int) -> None:
    """按三项比例重新组卷，难题比例自动补足剩余。"""
    simple_r = max(0, min(100, simple_r))
    mid_r = max(0, min(100, mid_r))
    if simple_r + mid_r > 100:
        mid_r = 100 - simple_r
    hard_r = 100 - simple_r - mid_r
    with _session_guard(thread_id):
        _get_graph().invoke(
            Command(resume=f"regroup:{simple_r}/{mid_r}/{hard_r}"),
            _config(thread_id),
        )


def load_answer(thread_id: str, idx: int) -> dict:
    """读取作答页面状态；进度错位时返回目标题号。"""
    values = _get_graph().get_state(_config(thread_id)).values
    questions = values.get("approved_questions") or []
    rounds = values.get("round_results") or []
    answered = len(rounds)
    total = int(values.get("question_count") or len(questions))
    if idx < 0:
        return {"kind": "redirect", "idx": 0}
    if not questions:
        return {"kind": "review"}
    if answered >= total:
        if idx != total:
            return {"kind": "redirect", "idx": total}
        return {
            "kind": "completed",
            "idx": total,
            "total": total,
            "round_results": rounds,
            "questions": questions,
        }
    if idx != answered:
        return {"kind": "redirect", "idx": answered}
    if idx >= len(questions):
        return {"kind": "review"}
    question = questions[idx]
    hint_level = int(values.get("hint_level") or 0)
    scaffold_level = int(values.get("scaffold_level") or 0)
    return {
        "kind": "answer",
        "idx": idx,
        "total": total,
        "question": question,
        "hint_level": hint_level,
        "hint": build_hint(question, hint_level),
        "scaffold_level": scaffold_level,
        "scaffold": build_scaffold(question, scaffold_level),
        "blanks": (
            build_template(question["params"])["blanks"]
            if question.get("params") else []
        ),
    }


def request_hint(thread_id: str, idx: int, max_level: int = 3) -> int:
    """为当前未完成题提升一级提示，返回新的提示等级。"""
    graph = _get_graph()
    config = _config(thread_id)
    values = graph.get_state(config).values
    answered = len(values.get("round_results") or [])
    if idx != answered:
        return int(values.get("hint_level") or 0)
    with _session_guard(thread_id):
        level = min(max_level, int(values.get("hint_level") or 0) + 1)
        graph.update_state(config, {"hint_level": level})
    return level


def request_scaffold(thread_id: str, idx: int, max_level: int = 2) -> int:
    """为当前未完成题提升一级脚手架，返回新的脚手架等级。"""
    graph = _get_graph()
    config = _config(thread_id)
    values = graph.get_state(config).values
    answered = len(values.get("round_results") or [])
    if idx != answered:
        return int(values.get("scaffold_level") or 0)
    with _session_guard(thread_id):
        level = min(max_level, int(values.get("scaffold_level") or 0) + 1)
        graph.update_state(config, {"scaffold_level": level})
    return level


def _build_student_steps(question: dict, form_data: Mapping) -> tuple[dict | None, list]:
    template = build_template(question["params"]) if question.get("params") else None
    steps = []
    if template:
        for blank in template["blanks"]:
            steps.append({
                "basis": blank["basis"],
                "result": str(form_data.get(blank["id"]) or "").strip(),
            })
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
    else:
        steps.append({
            "basis": "最终作答",
            "result": str(form_data.get("final_answer") or "").strip(),
        })
    return template, steps


def submit_answer(
    thread_id: str, idx: int, form_data: Mapping
) -> int:
    """提交单题作答，返回下一题序号。"""
    values = _get_graph().get_state(_config(thread_id)).values
    questions = values.get("approved_questions") or []
    total = len(questions)
    answered = len(values.get("round_results") or [])
    if idx != answered or idx >= total:
        return total if answered >= total else answered
    if not questions:
        return idx
    with _session_guard(thread_id):
        question = questions[idx]
        template, steps = _build_student_steps(question, form_data)
        hint_count = int(values.get("hint_level") or 0)
        scaffold_level = int(values.get("scaffold_level") or 0)
        assistance_level = (
            "scaffolded" if scaffold_level > 0
            else "hinted" if hint_count > 0
            else "independent"
        )
        _get_graph().invoke(
            {
                "student_id": values["student_id"],
                "session_id": values.get("session_id"),
                "current_question": question,
                "template": template,
                "student_steps": steps,
                "attempt_no": 1,
                "assistance_level": assistance_level,
                "hint_count": hint_count,
                "scaffold_level": scaffold_level,
                "phase": "grade_round",
            },
            _config(thread_id),
        )
    return idx + 1


def load_feedback(thread_id: str, idx: int) -> dict | None:
    """读取单题提交后的程序事实，不包含 AI 归因和老师结论。"""
    values = _get_graph().get_state(_config(thread_id)).values
    rounds = values.get("round_results") or []
    if idx < 0 or idx >= len(rounds):
        return None
    questions = values.get("approved_questions") or []
    result = rounds[idx]
    error = result.get("error") or {}
    breakpoint = error.get("program_breakpoint")
    if not breakpoint and not result.get("is_correct"):
        wrong_blank = next(
            (
                blank
                for blank in (result.get("blank_results") or [])
                if not blank.get("is_correct")
            ),
            None,
        )
        if wrong_blank:
            breakpoint = (
                f"程序定位断点：{wrong_blank['blank_id']}"
                f"（{wrong_blank['basis']}）"
            )
    total = int(values.get("question_count") or len(questions))
    return {
        "idx": idx,
        "total": total,
        "is_correct": result["is_correct"],
        "stem": questions[idx]["stem"] if idx < total else "",
        "breakpoint": breakpoint,
        "next_idx": idx + 1,
        "finished": idx + 1 >= total,
    }


def trigger_summary(thread_id: str) -> None:
    """完成答题后触发会话汇总。"""
    values = _get_graph().get_state(_config(thread_id)).values
    if values.get("phase") != "answer":
        return
    with _session_guard(thread_id):
        _get_graph().invoke(
            {
                "student_id": values["student_id"],
                "session_id": values.get("session_id"),
                "phase": "summarize",
            },
            _config(thread_id),
        )


def load_result(thread_id: str, idx: int) -> dict | None:
    """读取单题结果。"""
    values = _get_graph().get_state(_config(thread_id)).values
    rounds = values.get("round_results") or []
    if idx < 0 or idx >= len(rounds):
        return None
    total = len(values.get("approved_questions") or [])
    return {
        "idx": idx,
        "total": total,
        "result": rounds[idx],
        "has_next": idx + 1 < total,
    }


def load_summary(thread_id: str) -> dict:
    """读取批量画像确认页面状态。"""
    snap = _get_graph().get_state(_config(thread_id))
    if snap.values.get("llm_error"):
        return {"kind": "error", "message": snap.values["llm_error"]}
    if snap.next:
        task = next((task for task in snap.tasks if task.interrupts), None)
        if task is not None:
            payload = task.interrupts[0].value
            return {
                "kind": "summary",
                "proposals": payload["proposals"],
                "round_results": snap.values.get("round_results") or [],
                "questions": snap.values.get("approved_questions") or [],
            }
    if snap.values.get("phase") == "done":
        return {"kind": "done"}
    return {"kind": "redirect_home"}


def resolve_summary(
    thread_id: str,
    decision: str,
    corrections: dict[str, str] | None = None,
    error_corrections: dict[str, str] | None = None,
    test_mode: bool = False,
) -> None:
    """提交老师对批量画像的最终决定。"""
    payload = {
        "decision": decision,
        "corrections": corrections or {},
        "error_corrections": error_corrections or {},
        "test_mode": test_mode,
    }
    with _session_guard(thread_id):
        _get_graph().invoke(
            Command(resume=payload), _config(thread_id)
        )


def load_done(thread_id: str) -> dict:
    """读取完成页原始状态。"""
    return dict(_get_graph().get_state(_config(thread_id)).values)
