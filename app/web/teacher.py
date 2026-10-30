"""老师决策路由。"""

import os
from urllib.parse import quote

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from app.application import student_practice as practice
from app.domain.types import ERROR_TYPE_OPTIONS
from app.web.auth import (
    TEACHER_COOKIE,
    TEACHER_THREAD_COOKIE,
    LOGIN_LOCK_SECONDS,
    clear_teacher_login_failures,
    record_teacher_login_failure,
    teacher_client_key,
    teacher_cookie_value,
    teacher_login_locked,
    teacher_redirect,
    resume_token,
)
from app.web.dependencies import templates


router = APIRouter()


def _thread(request: Request) -> str | None:
    return (
        request.cookies.get(TEACHER_THREAD_COOKIE)
        or request.cookies.get("thread_id")
    )


@router.get("/teacher/login")
def teacher_login_page(request: Request):
    return templates.TemplateResponse(
        request,
        "teacher_login.html",
        {
            "error": request.query_params.get("error") == "1",
            "locked": request.query_params.get("error") == "locked",
            "lock_seconds": LOGIN_LOCK_SECONDS,
            "required_token": bool(
                os.getenv("TUTOR_TEACHER_TOKEN", "").strip()
            ),
        },
    )


@router.post("/teacher/login")
def teacher_login(request: Request, token: str = Form("")):
    expected = os.getenv("TUTOR_TEACHER_TOKEN", "").strip()
    if not expected:
        response = RedirectResponse("/teacher/review", status_code=303)
        return response
    client_key = teacher_client_key(request)
    if teacher_login_locked(client_key):
        return RedirectResponse("/teacher/login?error=locked", status_code=303)
    if token.strip() != expected:
        locked = record_teacher_login_failure(client_key)
        query = "locked" if locked else "1"
        return RedirectResponse(
            f"/teacher/login?error={query}", status_code=303
        )
    clear_teacher_login_failures(client_key)
    target = "/teacher/sessions"
    response = RedirectResponse(target, status_code=303)
    response.set_cookie(
        TEACHER_COOKIE,
        teacher_cookie_value(expected),
        httponly=True,
        samesite="lax",
    )
    return response


@router.get("/teacher/sessions")
def teacher_sessions_page(request: Request):
    redirect = teacher_redirect(request)
    if redirect:
        return redirect
    sessions = practice.list_teacher_sessions()
    for item in sessions:
        item["resume_token"] = resume_token(item["session_id"])
    return templates.TemplateResponse(
        request,
        "teacher_sessions.html",
        {
            "sessions": sessions,
            "archived_count": request.query_params.get("archived", ""),
            "error_message": request.query_params.get("error", ""),
            "state_labels": {
                "pending_review": "待预审",
                "in_progress": "答题中",
                "pending_confirmation": "待画像确认",
                "done": "已完成",
                "waiting": "处理中",
                "aborted": "已中断",
            },
        },
    )


@router.get("/teacher/session/{session_id}")
def select_teacher_session(request: Request, session_id: str):
    redirect = teacher_redirect(request)
    if redirect:
        return redirect
    try:
        entry = practice.teacher_session_entry(session_id)
    except ValueError:
        return RedirectResponse("/teacher/sessions", status_code=303)
    target = {
        "review": "/teacher/review",
        "summary": "/teacher/summary",
        "done": "/done",
    }[entry]
    response = RedirectResponse(target, status_code=303)
    response.set_cookie(
        TEACHER_THREAD_COOKIE,
        session_id,
        httponly=True,
        samesite="lax",
    )
    return response


@router.post("/teacher/session/{session_id}/archive")
def archive_teacher_session(request: Request, session_id: str):
    redirect = teacher_redirect(request)
    if redirect:
        return redirect
    try:
        practice.archive_session(session_id)
    except ValueError as exc:
        return RedirectResponse(
            f"/teacher/sessions?error={quote(str(exc))}",
            status_code=303,
        )
    return RedirectResponse("/teacher/sessions", status_code=303)


@router.post("/teacher/sessions/archive-finished")
def archive_finished_teacher_sessions(request: Request):
    redirect = teacher_redirect(request)
    if redirect:
        return redirect
    count = practice.archive_finished_sessions()
    return RedirectResponse(
        f"/teacher/sessions?archived={count}",
        status_code=303,
    )


@router.get("/teacher/review")
def review_page(request: Request):
    redirect = teacher_redirect(request)
    if redirect:
        return redirect
    thread = _thread(request)
    if thread is None:
        return RedirectResponse("/", status_code=303)
    view = practice.load_review(thread)
    if view["kind"] == "error":
        return templates.TemplateResponse(
            request,
            "error.html",
            {"message": view["message"], "retry_url": "/teacher/review"},
        )
    if view["kind"] == "waiting":
        return templates.TemplateResponse(
            request,
            "review.html",
            {"waiting": True, "busy": True, "candidates": []},
        )
    if view["kind"] == "review":
        return templates.TemplateResponse(
            request,
            "review.html",
            {
                "candidates": view["candidates"],
                "simple_ratio": view["simple_ratio"],
                "mid_ratio": view["mid_ratio"],
                "hard_ratio": view["hard_ratio"],
                "teaching_plan": view.get("teaching_plan"),
                "busy": request.query_params.get("busy") == "1",
                "error_message": (
                    view.get("error_message")
                    or request.query_params.get("error", "")
                ),
            },
        )
    if view["kind"] == "redirect_answer":
        return RedirectResponse("/teacher/review-done", status_code=303)
    if view["kind"] == "redirect_summary":
        return RedirectResponse("/teacher/summary", status_code=303)
    return RedirectResponse("/", status_code=303)


@router.post("/teacher/review")
def review_post(request: Request, decision: str = Form("")):
    redirect = teacher_redirect(request)
    if redirect:
        return redirect
    thread = _thread(request)
    if thread is None:
        return RedirectResponse("/", status_code=303)
    try:
        view = practice.resume_review(thread, decision)
    except practice.PracticeBusy:
        return RedirectResponse("/teacher/review?busy=1", status_code=303)
    if view["kind"] == "review":
        return RedirectResponse("/teacher/review", status_code=303)
    return RedirectResponse("/teacher/review-done", status_code=303)


@router.get("/teacher/review-done")
def review_done_page(request: Request):
    redirect = teacher_redirect(request)
    if redirect:
        return redirect
    thread = _thread(request)
    if thread is None:
        return RedirectResponse("/", status_code=303)
    view = practice.load_review_done(thread)
    if view["kind"] == "review":
        return RedirectResponse("/teacher/review", status_code=303)
    return templates.TemplateResponse(request, "review_done.html", {})


@router.post("/teacher/review/swap")
def review_swap(request: Request, no: str = Form("")):
    redirect = teacher_redirect(request)
    if redirect:
        return redirect
    thread = _thread(request)
    if thread is None:
        return RedirectResponse("/", status_code=303)
    try:
        practice.swap_question(thread, no)
    except practice.PracticeBusy:
        return RedirectResponse("/teacher/review?busy=1", status_code=303)
    return RedirectResponse("/teacher/review", status_code=303)


@router.post("/teacher/review/edit")
def review_edit(
    request: Request,
    no: str = Form(""),
    stem: str = Form(""),
    a: str = Form(...),
    b: str = Form(...),
    c: str = Form(...),
    structure_tag: str = Form(""),
):
    redirect = teacher_redirect(request)
    if redirect:
        return redirect
    thread = _thread(request)
    if thread is None:
        return RedirectResponse("/", status_code=303)
    try:
        practice.edit_question(
            thread, no, stem, a, b, c, structure_tag
        )
    except practice.PracticeBusy:
        return RedirectResponse("/teacher/review?busy=1", status_code=303)
    except ValueError as exc:
        return RedirectResponse(
            f"/teacher/review?error={quote(str(exc))}", status_code=303
        )
    return RedirectResponse("/teacher/review", status_code=303)


@router.post("/teacher/review/regroup-ratios")
def review_regroup_ratios(
    request: Request,
    simple_r: int = Form(0),
    mid_r: int = Form(0),
):
    redirect = teacher_redirect(request)
    if redirect:
        return redirect
    thread = _thread(request)
    if thread is None:
        return RedirectResponse("/", status_code=303)
    try:
        practice.regroup_ratios(thread, simple_r, mid_r)
    except practice.PracticeBusy:
        return RedirectResponse("/teacher/review?busy=1", status_code=303)
    return RedirectResponse("/teacher/review", status_code=303)


@router.get("/teacher/summary")
def summary_page(request: Request):
    redirect = teacher_redirect(request)
    if redirect:
        return redirect
    thread = _thread(request)
    if thread is None:
        return RedirectResponse("/", status_code=303)
    view = practice.load_summary(thread)
    if view["kind"] == "error":
        return templates.TemplateResponse(
            request,
            "error.html",
            {"message": view["message"], "retry_url": "/teacher/summary"},
        )
    if view["kind"] == "summary":
        return templates.TemplateResponse(
            request,
            "summary.html",
            {
                "proposals": view["proposals"],
                "round_results": view["round_results"],
                "questions": view["questions"],
                "error_types": ERROR_TYPE_OPTIONS,
                "error_message": view.get("error_message"),
            },
        )
    if view["kind"] == "done":
        return RedirectResponse("/teacher/completed", status_code=303)
    return templates.TemplateResponse(request, "summary_wait.html", {})


@router.post("/teacher/summary")
async def summary_post(request: Request):
    redirect = teacher_redirect(request)
    if redirect:
        return redirect
    thread = _thread(request)
    if thread is None:
        return RedirectResponse("/", status_code=303)
    form = await request.form()
    decision = str(form.get("decision") or "")
    corrections = {
        key.removeprefix("level_"): str(value)
        for key, value in form.items()
        if key.startswith("level_") and value
    }
    error_corrections = {
        key.removeprefix("error_"): str(value)
        for key, value in form.items()
        if key.startswith("error_") and value
    }
    result_corrections = {
        key.removeprefix("result_"): str(value)
        for key, value in form.items()
        if key.startswith("result_") and value
    }
    subquestion_corrections = {
        key.removeprefix("subresult_"): str(value)
        for key, value in form.items()
        if key.startswith("subresult_") and value
    }
    test_mode = str(form.get("test_session") or "").lower() in (
        "1", "true", "on", "yes",
    )
    try:
        result = practice.resolve_summary(
            thread,
            decision,
            corrections,
            error_corrections,
            result_corrections,
            subquestion_corrections,
            test_mode,
        )
    except practice.PracticeBusy:
        return RedirectResponse("/teacher/summary?busy=1", status_code=303)
    if result.get("kind") == "summary":
        return RedirectResponse("/teacher/summary", status_code=303)
    return RedirectResponse("/teacher/completed", status_code=303)


@router.get("/teacher/completed")
def teacher_completed_page(request: Request):
    redirect = teacher_redirect(request)
    if redirect:
        return redirect
    return templates.TemplateResponse(request, "teacher_completed.html", {})
