"""老师决策路由。"""

import os
from urllib.parse import quote

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse

from app.application import student_practice as practice
from app.web.auth import TEACHER_COOKIE, teacher_cookie_value, teacher_redirect
from app.web.dependencies import templates


router = APIRouter()


def _thread(request: Request) -> str | None:
    return request.cookies.get("thread_id")


@router.get("/teacher/login")
def teacher_login_page(request: Request):
    return templates.TemplateResponse(
        request,
        "teacher_login.html",
        {
            "error": request.query_params.get("error") == "1",
            "required_token": bool(
                os.getenv("TUTOR_TEACHER_TOKEN", "").strip()
            ),
        },
    )


@router.post("/teacher/login")
def teacher_login(token: str = Form("")):
    expected = os.getenv("TUTOR_TEACHER_TOKEN", "").strip()
    if not expected:
        response = RedirectResponse("/teacher/review", status_code=303)
        return response
    if token.strip() != expected:
        return RedirectResponse("/teacher/login?error=1", status_code=303)
    response = RedirectResponse("/teacher/review", status_code=303)
    response.set_cookie(
        TEACHER_COOKIE,
        teacher_cookie_value(expected),
        httponly=True,
        samesite="lax",
    )
    return response


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
            request, "error.html", {"message": view["message"]}
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
                "busy": request.query_params.get("busy") == "1",
                "error_message": (
                    view.get("error_message")
                    or request.query_params.get("error", "")
                ),
            },
        )
    if view["kind"] == "redirect_answer":
        return RedirectResponse(
            f"/answer/{view['answered']}", status_code=303
        )
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
    return RedirectResponse(f"/answer/{view['answered']}", status_code=303)


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
    a: float = Form(...),
    b: float = Form(...),
    c: float = Form(...),
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
            request, "error.html", {"message": view["message"]}
        )
    if view["kind"] == "summary":
        return templates.TemplateResponse(
            request,
            "summary.html",
            {
                "proposals": view["proposals"],
                "round_results": view["round_results"],
                "questions": view["questions"],
            },
        )
    if view["kind"] == "done":
        return RedirectResponse("/done", status_code=303)
    return RedirectResponse("/", status_code=303)


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
    try:
        practice.resolve_summary(thread, decision, corrections)
    except practice.PracticeBusy:
        return RedirectResponse("/teacher/summary?busy=1", status_code=303)
    return RedirectResponse("/done", status_code=303)
