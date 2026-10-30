"""学生练习用例。

该层编排一次完整练习，不依赖 FastAPI。HTTP 状态、模板渲染和跳转由 Web 层处理。
"""

from __future__ import annotations

import os
import uuid
import logging
import threading
from collections.abc import Mapping
from contextlib import contextmanager

from langgraph.types import Command

import app.adapters.persistence as db
import app.adapters.session_store as session_store
from app.adapters.checkpoint import default_checkpointer
from app.domain.answer_template import build_template, supports_question_template
from app.harness.hints import build_hint, build_scaffold
from app.harness.session_graph import build_session_graph


class PracticeBusy(RuntimeError):
    """同一会话已有写操作执行中。"""


logger = logging.getLogger(__name__)
_COMPILED = None
MIN_QUESTION_COUNT = 1
MAX_QUESTION_COUNT = 30
BASE_KP = "配方法解一元二次方程"
GROWTH_KP = "一元二次方程增长率"
SUPPORTED_KNOWLEDGE_POINTS = (BASE_KP, GROWTH_KP)
MAX_GROWTH_QUESTION_COUNT = 7


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


def _recover_pending_grade(thread_id: str, snap):
    """完成上次已在批改结果落库后中断的 collect_round。"""
    if (
        snap.next
        and "collect_round" in snap.next
        and snap.values.get("phase") == "grade_round"
    ):
        with _session_guard(thread_id):
            _get_graph().invoke(None, _config(thread_id))
        return _get_graph().get_state(_config(thread_id))
    return snap


@contextmanager
def _session_guard(thread_id: str):
    """通过数据库租约串行化同一会话的写操作。"""
    ttl_seconds = session_store.lease_ttl_seconds()
    if not session_store.acquire_practice_lease(
        thread_id,
        ttl_seconds=ttl_seconds,
    ):
        raise PracticeBusy(thread_id)
    stop_renewal = threading.Event()

    def renew_loop() -> None:
        interval = max(1.0, ttl_seconds / 3)
        while not stop_renewal.wait(interval):
            try:
                if not session_store.renew_practice_lease(
                    thread_id,
                    ttl_seconds=ttl_seconds,
                ):
                    logger.warning(
                        "session lease renewal lost ownership: %s",
                        thread_id,
                    )
                    return
            except Exception:
                logger.exception(
                    "session lease renewal failed: %s",
                    thread_id,
                )

    renewal_thread = threading.Thread(
        target=renew_loop,
        name=f"little-tutor-lease-{thread_id}",
        daemon=True,
    )
    renewal_thread.start()
    try:
        yield
    finally:
        stop_renewal.set()
        renewal_thread.join(timeout=1.0)
        session_store.release_practice_lease(thread_id)


def _parse_count(raw: str) -> int:
    value = str(raw or "").strip()
    if not value:
        return 10
    try:
        count = int(value)
    except ValueError as exc:
        raise ValueError(
            f"题量必须是 {MIN_QUESTION_COUNT}-{MAX_QUESTION_COUNT} 的整数"
        ) from exc
    if not (MIN_QUESTION_COUNT <= count <= MAX_QUESTION_COUNT):
        raise ValueError(
            f"题量必须是 {MIN_QUESTION_COUNT}-{MAX_QUESTION_COUNT} 的整数"
        )
    return count


def ensure_student_kp(
    student_id: str | None = None,
    kp_name: str | None = None,
) -> tuple[str, str]:
    """解析长期学生身份和当前主知识点，缺失时按演示口径创建。"""
    selected_kp = (
        kp_name
        if kp_name in SUPPORTED_KNOWLEDGE_POINTS
        else BASE_KP
    )
    db.init_db()
    if os.getenv("TUTOR_LOAD_SEED_CATALOG", "1") != "0":
        from app.adapters.seed_catalog import (
            load_growth_real_exam_questions,
            load_private_questions,
            load_seed_questions,
        )

        load_seed_questions()
        load_private_questions()
        load_growth_real_exam_questions()
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
            .filter_by(kp_name=selected_kp)
            .first()
        )
        if kp is None:
            concept = (
                "用 a(1+x)^n=b 模型解决平均增长率与降价率问题"
                if selected_kp == GROWTH_KP
                else "通过配方将方程化为 (x+m)²=n 的形式求解"
            )
            kp = db.KnowledgePoint(
                subject="数学",
                chapter="一元二次方程",
                kp_name=selected_kp,
                concept=concept,
            )
            s.add(kp)
            s.flush()
        s.commit()
        return str(student.id), str(kp.id)


def start_practice(
    student_id: str | None,
    count: str,
    kp_name: str | None = None,
) -> dict:
    """创建并启动一场新练习。"""
    question_count = (
        MAX_GROWTH_QUESTION_COUNT
        if kp_name == GROWTH_KP and not str(count or "").strip()
        else _parse_count(count)
    )
    if (
        kp_name == GROWTH_KP
        and question_count > MAX_GROWTH_QUESTION_COUNT
    ):
        raise ValueError(
            "真实中考增长率题当前有 15 道，预审需要 2 倍题量，"
            f"最多可选 {MAX_GROWTH_QUESTION_COUNT} 题"
        )
    resolved_student_id, kp_id = ensure_student_kp(student_id, kp_name)
    selected_kp = kp_name if kp_name in SUPPORTED_KNOWLEDGE_POINTS else BASE_KP
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
                "kp_name": selected_kp,
                "session_id": thread_id,
                "question_count": question_count,
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
        if "candidates" not in payload:
            if "proposals" in payload:
                return {"kind": "redirect_summary"}
            return {"kind": "waiting"}
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
            "teaching_plan": payload.get("teaching_plan"),
        }
    if snap.values.get("phase") == "answer":
        return {
            "kind": "redirect_answer",
            "answered": len(snap.values.get("round_results") or []),
        }
    return {"kind": "redirect_home"}


def resume_student_session(session_id: str) -> dict:
    """按业务 session_id 恢复学生端，并在需要时同步学生身份。"""
    db.init_db()
    with db.SessionLocal() as s:
        session = s.get(db.PracticeSessionRecord, session_id)
        if session is None:
            return {
                "kind": "redirect",
                "location": "/",
                "student_id": None,
            }
        student_id = str(session.student_id)
        if session.archived_at is not None:
            return {
                "kind": "error",
                "message": "这场练习已归档，不再继续作答。",
            }
        if session.status == "aborted":
            session.status = "started"
            session.review_status = "pending"
            session.completed_at = None
            s.commit()

    snap = _recover_pending_grade(
        session_id,
        _get_graph().get_state(_config(session_id)),
    )
    if snap.values.get("llm_error"):
        return {"kind": "error", "message": snap.values["llm_error"]}
    if snap.next:
        task = next((task for task in snap.tasks if task.interrupts), None)
        if task is not None:
            payload = task.interrupts[0].value or {}
            if "candidates" in payload:
                location = "/waiting"
            elif "proposals" in payload:
                location = "/waiting-confirmation"
            else:
                location = "/waiting"
        else:
            location = "/waiting"
        return {
            "kind": "redirect",
            "location": location,
            "student_id": student_id,
        }

    phase = snap.values.get("phase")
    answered = len(snap.values.get("round_results") or [])
    total = len(snap.values.get("approved_questions") or [])
    if phase == "answer":
        location = f"/answer/{min(answered, total)}"
    elif phase == "done":
        location = "/done"
    else:
        location = "/"
    return {
        "kind": "redirect",
        "location": location,
        "student_id": student_id,
    }


def student_session_owner(session_id: str) -> str | None:
    """返回会话所属学生 ID；不存在时返回 None。"""
    db.init_db()
    with db.SessionLocal() as s:
        row = s.get(db.PracticeSessionRecord, session_id)
        return str(row.student_id) if row is not None else None


def list_student_sessions(
    student_id: str | None,
    limit: int = 50,
) -> list[dict]:
    """列出学生自己的练习记录，供学生选择任意一场恢复或查看。"""
    if not student_id:
        return []
    db.init_db()
    with db.SessionLocal() as s:
        rows = (
            s.query(db.PracticeSessionRecord)
            .filter(
                db.PracticeSessionRecord.student_id == int(student_id),
                db.PracticeSessionRecord.archived_at.is_(None),
            )
            .order_by(db.PracticeSessionRecord.started_at.desc())
            .limit(limit)
            .all()
        )
        sessions = [
            {
                "session_id": row.session_id,
                "status": row.status,
                "review_status": row.review_status,
                "started_at": row.started_at.strftime("%Y-%m-%d %H:%M"),
                "kp_id": row.kp_id,
            }
            for row in rows
        ]

    entries = []
    for session in sessions:
        state, values = _teacher_session_state(session["session_id"])
        if session["status"] == "aborted":
            state = "aborted"
        entries.append({
            **session,
            "state": state,
            "answered": len(values.get("round_results") or []),
            "total": len(values.get("approved_questions") or []),
            "kp_name": values.get("kp_name") or "练习",
            "resume_url": f"/resume?session_id={session['session_id']}",
        })
    return entries


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


def load_review_done(thread_id: str) -> dict:
    """读取老师预审完成页状态；已完成会话不依赖 H1 候选负载。"""
    snap = _get_graph().get_state(_config(thread_id))
    if snap.next:
        task = next((task for task in snap.tasks if task.interrupts), None)
        if task is not None:
            payload = task.interrupts[0].value or {}
            if "candidates" in payload:
                return {"kind": "review"}
    return {"kind": "done"}


def _teacher_session_state(session_id: str) -> tuple[str, dict]:
    """返回老师视角的会话状态和 LangGraph 快照。"""
    snap = _get_graph().get_state(_config(session_id))
    if snap.next:
        task = next((task for task in snap.tasks if task.interrupts), None)
        if task is not None:
            payload = task.interrupts[0].value or {}
            if "candidates" in payload:
                return "pending_review", snap.values
            if "proposals" in payload:
                return "pending_confirmation", snap.values
    if snap.values.get("phase") == "done":
        return "done", snap.values
    if snap.values.get("phase") == "answer":
        return "in_progress", snap.values
    return "waiting", snap.values


def list_teacher_sessions(limit: int = 50) -> list[dict]:
    """老师待办列表，不依赖学生浏览器 Cookie。"""
    db.init_db()
    with db.SessionLocal() as s:
        rows = (
            s.query(db.PracticeSessionRecord)
            .filter(db.PracticeSessionRecord.archived_at.is_(None))
            .order_by(db.PracticeSessionRecord.started_at.desc())
            .limit(limit)
            .all()
        )
        students = {
            row.id: row.name for row in s.query(db.Student).all()
        }
        knowledge_points = {
            row.id: row.kp_name for row in s.query(db.KnowledgePoint).all()
        }
    sessions = []
    for row in rows:
        state, values = _teacher_session_state(row.session_id)
        if row.status == "aborted":
            state = "aborted"
        stale = (
            row.status == "started"
            and session_store.session_is_stale(row.started_at)
        )
        can_archive = state in ("done", "aborted") or stale
        rounds = list(values.get("round_results") or [])
        total = int(values.get("question_count") or 0)
        sessions.append({
            "session_id": row.session_id,
            "student_name": students.get(row.student_id, f"学生 {row.student_id}"),
            "kp_name": knowledge_points.get(row.kp_id, f"知识点 {row.kp_id}"),
            "state": state,
            "status": row.status,
            "review_status": row.review_status,
            "data_source": row.data_source,
            "answered": len(rounds),
            "total": total,
            "started_at": row.started_at.strftime("%Y-%m-%d %H:%M"),
            "stale": stale,
            "can_archive": can_archive,
        })
    return sessions


def archive_session(session_id: str) -> None:
    """归档单场会话；具体状态校验由持久化层负责。"""
    session_store.archive_practice_session(session_id)


def archive_finished_sessions() -> int:
    """归档所有已完成和已中断会话。"""
    return session_store.archive_finished_practice_sessions()


def teacher_session_entry(session_id: str) -> str:
    """老师选中会话后的目标页面类型。"""
    db.init_db()
    with db.SessionLocal() as s:
        row = s.get(db.PracticeSessionRecord, session_id)
        if row is None or row.archived_at is not None:
            raise ValueError("会话不存在或已归档")
    state, _ = _teacher_session_state(session_id)
    return {
        "pending_review": "review",
        "in_progress": "summary",
        "pending_confirmation": "summary",
        "done": "done",
        "waiting": "summary",
    }[state]


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
    a: str | int | float,
    b: str | int | float,
    c: str | int | float,
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
    snap = _recover_pending_grade(
        thread_id,
        _get_graph().get_state(_config(thread_id)),
    )
    values = snap.values
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
    template = (
        build_template(question["params"])
        if supports_question_template(question.get("params"))
        else None
    )
    subquestion_sections = []
    if template and template.get("subquestions"):
        blanks_by_id = {
            blank["id"]: blank for blank in template.get("blanks") or []
        }
        subquestion_sections = [
            {
                "id": item["id"],
                "prompt": item["prompt"],
                "blanks": [
                    blanks_by_id[blank_id]
                    for blank_id in item.get("blank_ids") or []
                    if blank_id in blanks_by_id
                ],
            }
            for item in template["subquestions"]
        ]
    return {
        "kind": "answer",
        "idx": idx,
        "total": total,
        "question": question,
        "hint_level": hint_level,
        "hint": build_hint(question, hint_level),
        "scaffold_level": scaffold_level,
        "scaffold": build_scaffold(question, scaffold_level),
        "blanks": template["blanks"] if template else [],
        "subquestion_sections": subquestion_sections,
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
    params = question.get("params") or {}
    template = (
        build_template(params)
        if supports_question_template(params)
        else None
    )
    steps = []
    if template:
        for blank in template["blanks"]:
            result = str(form_data.get(blank["id"]) or "").strip()
            step = {
                "basis": blank["basis"],
                "result": result,
                "response_mode": "templated",
            }
            if not result:
                step["unfilled"] = True
            if blank["kind"] == "choice":
                options = list(blank.get("options") or [])
                step["options"] = options
                try:
                    selected_index = int(result) - 1
                    if 0 <= selected_index < len(options):
                        step["selected_option_text"] = options[selected_index]
                except (TypeError, ValueError):
                    pass
            steps.append(step)
        by_id = {
            blank["id"]: step["result"]
            for blank, step in zip(template["blanks"], steps)
        }
        builder = template.get("final_answer_builder")
        answer_ids = template.get("answer_blank_ids") or [
            blank["id"] for blank in template["blanks"][-2:]
        ]
        if builder == "growth_rate":
            final_answer = by_id[answer_ids[0]]
        elif builder == "choice_text":
            raw_selected = by_id[answer_ids[0]]
            try:
                selected = int(raw_selected) - 1
                final_answer = template["blanks"][0]["options"][selected]
            except (TypeError, ValueError, IndexError):
                final_answer = ""
        elif builder == "subquestions":
            final_answer = ";".join(
                f"{subquestion['id']}={by_id[subquestion['final_blank_id']]}"
                for subquestion in template["subquestions"]
                if by_id.get(subquestion["final_blank_id"])
            )
        elif builder == "growth_equation":
            final_answer = str(template["computed_final_answer"])
        else:
            roots = [
                by_id[blank_id]
                for blank_id in answer_ids
                if by_id.get(blank_id)
            ]
            final_answer = (
                f"x={roots[0]}" if len(roots) == 1
                else f"x1={roots[0]}, x2={roots[1]}"
                if len(roots) >= 2
                else ""
            )
        steps.append({
            "basis": "最终作答",
            "result": final_answer,
            "response_mode": "templated",
            "unfilled": not bool(final_answer),
        })
    else:
        steps.append({
            "basis": "最终作答",
            "result": str(form_data.get("final_answer") or "").strip(),
            "response_mode": "free_form",
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


def skip_answer(thread_id: str, idx: int) -> int:
    """学生明确选择跳过：记录未作答事实，不做 AI 归因，进入下一题。"""
    values = _get_graph().get_state(_config(thread_id)).values
    questions = values.get("approved_questions") or []
    total = len(questions)
    answered = len(values.get("round_results") or [])
    if idx != answered or idx >= total:
        return total if answered >= total else answered
    with _session_guard(thread_id):
        question = questions[idx]
        _get_graph().invoke(
            {
                "student_id": values["student_id"],
                "session_id": values.get("session_id"),
                "current_question": question,
                "template": None,
                "student_steps": [],
                "attempt_no": 1,
                "assistance_level": "skipped",
                "hint_count": int(values.get("hint_level") or 0),
                "scaffold_level": int(values.get("scaffold_level") or 0),
                "skip": True,
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
        from app.domain.answer_template import breakpoint_label

        label = breakpoint_label(result.get("blank_results") or [])
        if label:
            breakpoint = f"程序定位断点：{label}"
    total = int(values.get("question_count") or len(questions))
    return {
        "idx": idx,
        "total": total,
        "is_correct": result["is_correct"],
        "final_answer_correct": result.get(
            "final_answer_correct", result["is_correct"]
        ),
        "process_correct": result.get("process_correct", True),
        "assistance_level": result.get("assistance_level", "independent"),
        "stem": questions[idx]["stem"] if idx < total else "",
        "breakpoint": breakpoint,
        "next_idx": idx + 1,
        "finished": idx + 1 >= total,
    }


def trigger_summary(thread_id: str) -> dict:
    """完成答题后触发会话汇总；未到汇总阶段时返回受控跳转。"""
    snap = _get_graph().get_state(_config(thread_id))
    if snap.next:
        task = next((task for task in snap.tasks if task.interrupts), None)
        if task is not None:
            payload = task.interrupts[0].value or {}
            if "proposals" in payload:
                return {"kind": "redirect", "location": "/waiting-confirmation"}
            if "candidates" in payload:
                return {"kind": "redirect", "location": "/waiting"}
        return {"kind": "redirect", "location": "/waiting"}

    values = snap.values
    if values.get("phase") == "done":
        return {"kind": "redirect", "location": "/done"}
    if values.get("phase") != "answer":
        return {"kind": "redirect", "location": "/"}

    answered = len(values.get("round_results") or [])
    total = len(values.get("approved_questions") or [])
    if answered < total:
        return {
            "kind": "redirect",
            "location": f"/answer/{answered}",
        }

    with _session_guard(thread_id):
        _get_graph().invoke(
            {
                "student_id": values["student_id"],
                "session_id": values.get("session_id"),
                "phase": "summarize",
            },
            _config(thread_id),
        )
    return {"kind": "redirect", "location": "/waiting-confirmation"}


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
            if "proposals" not in payload:
                if "candidates" in payload:
                    return {"kind": "redirect", "location": "/waiting"}
                return {"kind": "redirect", "location": "/"}
            return {
                "kind": "summary",
                "proposals": payload["proposals"],
                "round_results": snap.values.get("round_results") or [],
                "questions": snap.values.get("approved_questions") or [],
                "error_message": payload.get("validation_error"),
            }
    if snap.values.get("phase") == "done":
        return {"kind": "done"}
    return {"kind": "redirect_home"}


def resolve_summary(
    thread_id: str,
    decision: str,
    corrections: dict[str, str] | None = None,
    error_corrections: dict[str, str] | None = None,
    result_corrections: dict[str, str] | None = None,
    subquestion_corrections: dict[str, str] | None = None,
    test_mode: bool = False,
) -> dict:
    """提交老师对批量画像的最终决定。"""
    payload = {
        "decision": decision,
        "corrections": corrections or {},
        "error_corrections": error_corrections or {},
        "result_corrections": result_corrections or {},
        "subquestion_corrections": subquestion_corrections or {},
        "test_mode": test_mode,
    }
    with _session_guard(thread_id):
        _get_graph().invoke(
            Command(resume=payload), _config(thread_id)
        )
        snap = _get_graph().get_state(_config(thread_id))
    if snap.next:
        task = next((task for task in snap.tasks if task.interrupts), None)
        if task is not None:
            interrupt_payload = task.interrupts[0].value or {}
            return {
                "kind": "summary",
                "error_message": interrupt_payload.get("validation_error"),
            }
    return {"kind": "done"}


def load_done(thread_id: str) -> dict:
    """读取完成页原始状态。"""
    return dict(_get_graph().get_state(_config(thread_id)).values)
