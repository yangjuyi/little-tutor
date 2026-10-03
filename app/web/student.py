"""学生练习路由。"""

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from urllib.parse import quote

from app.application import student_practice as practice
from app.web.auth import valid_resume_token
from app.web.dependencies import templates
from app.web.view_models import build_done_context


router = APIRouter()
STUDENT_COOKIE_MAX_AGE = 60 * 60 * 24 * 30


def _thread(request: Request) -> str | None:
    return request.cookies.get("thread_id")


@router.get("/")
def index(request: Request):
    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "error_message": request.query_params.get("error", ""),
        },
    )


@router.get("/resume")
def resume_session(
    request: Request,
    session_id: str = "",
    token: str = "",
):
    session_id = session_id.strip()
    if not session_id:
        return RedirectResponse("/my-sessions", status_code=303)
    owner = practice.student_session_owner(session_id)
    cookie_owner = request.cookies.get("student_id")
    if owner is None:
        return RedirectResponse("/", status_code=303)
    if (
        cookie_owner != owner
        and not valid_resume_token(session_id, token)
    ):
        return RedirectResponse("/?error=resume_denied", status_code=303)
    view = practice.resume_student_session(session_id)
    if view["kind"] == "error":
        return templates.TemplateResponse(
            request,
            "error.html",
            {"message": view["message"], "retry_url": "/resume"},
        )
    response = RedirectResponse(view["location"], status_code=303)
    response.set_cookie(
        "thread_id",
        session_id,
        httponly=True,
        samesite="lax",
    )
    if view.get("student_id"):
        response.set_cookie(
            "student_id",
            view["student_id"],
            httponly=True,
            samesite="lax",
            max_age=STUDENT_COOKIE_MAX_AGE,
        )
    return response


@router.get("/my-sessions")
def my_sessions(request: Request):
    sessions = practice.list_student_sessions(
        request.cookies.get("student_id")
    )
    labels = {
        "pending_review": "等待老师定稿",
        "in_progress": "答题中",
        "pending_confirmation": "等待老师确认",
        "done": "已完成",
        "waiting": "处理中",
        "aborted": "已中断，可继续",
    }
    return templates.TemplateResponse(
        request,
        "student_sessions.html",
        {
            "sessions": sessions,
            "state_labels": labels,
        },
    )


@router.post("/start")
def start(
    request: Request,
    count: str = Form(""),
    kp_name: str = Form(""),
):
    try:
        result = practice.start_practice(
            request.cookies.get("student_id"), count, kp_name
        )
    except practice.PracticeBusy:
        return RedirectResponse("/", status_code=303)
    except ValueError as exc:
        return RedirectResponse(
            f"/?error={quote(str(exc))}", status_code=303
        )
    response = RedirectResponse("/waiting", status_code=303)
    response.set_cookie(
        "student_id",
        result["student_id"],
        httponly=True,
        samesite="lax",
        max_age=STUDENT_COOKIE_MAX_AGE,
    )
    response.set_cookie(
        "thread_id", result["thread_id"], httponly=True, samesite="lax"
    )
    return response


@router.get("/waiting")
def waiting_page(request: Request):
    thread = _thread(request)
    if thread is None:
        return RedirectResponse("/", status_code=303)
    view = practice.load_review(thread)
    if view["kind"] == "redirect_answer":
        return RedirectResponse(
            f"/answer/{view['answered']}", status_code=303
        )
    if view["kind"] == "error":
        return templates.TemplateResponse(
            request,
            "error.html",
            {"message": view["message"], "retry_url": "/waiting"},
        )
    if view["kind"] in ("review", "waiting"):
        return templates.TemplateResponse(request, "waiting.html", {})
    return RedirectResponse("/", status_code=303)


@router.get("/answer/{idx}")
def answer_page(request: Request, idx: int):
    thread = _thread(request)
    if thread is None:
        return RedirectResponse("/", status_code=303)
    view = practice.load_answer(thread, idx)
    if view["kind"] == "redirect":
        return RedirectResponse(f"/answer/{view['idx']}", status_code=303)
    if view["kind"] == "review":
        return RedirectResponse("/teacher/review", status_code=303)
    if view["kind"] == "completed":
        return templates.TemplateResponse(
            request,
            "answer.html",
            {
                "idx": view["idx"],
                "total": view["total"],
                "question": None,
                "blanks": [],
                "busy": False,
                "completed": True,
                "round_results": view["round_results"],
                "questions": view["questions"],
            },
        )
    return templates.TemplateResponse(
        request,
        "answer.html",
        {
            "idx": view["idx"],
            "total": view["total"],
            "question": view["question"],
            "hint_level": view["hint_level"],
            "hint": view["hint"],
            "scaffold_level": view["scaffold_level"],
            "scaffold": view["scaffold"],
            "blanks": view["blanks"],
            "subquestion_sections": view["subquestion_sections"],
            "busy": request.query_params.get("busy") == "1",
            "completed": False,
        },
    )


@router.post("/answer/{idx}")
async def answer_post(request: Request, idx: int):
    thread = _thread(request)
    if thread is None:
        return RedirectResponse("/", status_code=303)
    try:
        next_idx = practice.submit_answer(
            thread, idx, await request.form()
        )
    except practice.PracticeBusy:
        return RedirectResponse(f"/answer/{idx}?busy=1", status_code=303)
    return RedirectResponse(f"/answer/{next_idx}", status_code=303)


@router.post("/skip/{idx}")
def skip_question(request: Request, idx: int):
    thread = _thread(request)
    if thread is None:
        return RedirectResponse("/", status_code=303)
    try:
        next_idx = practice.skip_answer(thread, idx)
    except practice.PracticeBusy:
        return RedirectResponse(f"/answer/{idx}?busy=1", status_code=303)
    return RedirectResponse(f"/answer/{next_idx}", status_code=303)


@router.get("/feedback/{idx}")
def feedback_page(request: Request, idx: int):
    thread = _thread(request)
    if thread is None:
        return RedirectResponse("/", status_code=303)
    view = practice.load_feedback(thread, idx)
    if view is None:
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(
        request,
        "feedback.html",
        view,
    )


@router.post("/hint/{idx}")
def hint_request(request: Request, idx: int):
    thread = _thread(request)
    if thread is None:
        return RedirectResponse("/", status_code=303)
    try:
        practice.request_hint(thread, idx)
    except practice.PracticeBusy:
        return RedirectResponse(f"/answer/{idx}?busy=1", status_code=303)
    return RedirectResponse(f"/answer/{idx}", status_code=303)


@router.post("/scaffold/{idx}")
def scaffold_request(request: Request, idx: int):
    thread = _thread(request)
    if thread is None:
        return RedirectResponse("/", status_code=303)
    try:
        practice.request_scaffold(thread, idx)
    except practice.PracticeBusy:
        return RedirectResponse(f"/answer/{idx}?busy=1", status_code=303)
    return RedirectResponse(f"/answer/{idx}", status_code=303)


@router.post("/summarize")
def summarize_trigger(request: Request):
    thread = _thread(request)
    if thread is None:
        return RedirectResponse("/", status_code=303)
    try:
        result = practice.trigger_summary(thread)
    except practice.PracticeBusy:
        return RedirectResponse("/waiting-confirmation", status_code=303)
    return RedirectResponse(result["location"], status_code=303)


@router.get("/waiting-confirmation")
def waiting_confirmation(request: Request):
    thread = _thread(request)
    if thread is None:
        return RedirectResponse("/", status_code=303)
    view = practice.load_summary(thread)
    if view["kind"] == "error":
        return templates.TemplateResponse(
            request,
            "error.html",
            {"message": view["message"], "retry_url": "/waiting-confirmation"},
        )
    if view["kind"] == "done":
        return RedirectResponse("/done", status_code=303)
    if view["kind"] == "redirect":
        return RedirectResponse(view["location"], status_code=303)
    return templates.TemplateResponse(request, "confirmation_wait.html", {})


@router.get("/result/{idx}")
def result_page(request: Request, idx: int):
    thread = _thread(request)
    if thread is None:
        return RedirectResponse("/", status_code=303)
    view = practice.load_result(thread, idx)
    if view is None:
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(
        request,
        "result.html",
        {
            "idx": view["idx"],
            "total": view["total"],
            "result": view["result"],
            "next_url": f"/answer/{view['idx'] + 1}",
            "has_next": view["has_next"],
        },
    )


@router.get("/done")
def done_page(request: Request):
    thread = _thread(request)
    if thread is None:
        return RedirectResponse("/", status_code=303)
    values = practice.load_done(thread)
    context = build_done_context(values)
    context.update({
        "h3_decision": values.get("h3_decision"),
        "test_session": bool(values.get("test_session")),
        "detail_url": f"/answer/{context['total']}" if context["total"] else "/",
    })
    return templates.TemplateResponse(request, "done.html", context)
