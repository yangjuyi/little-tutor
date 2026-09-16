"""学生练习路由。"""

from fastapi import APIRouter, Form, Request
from fastapi.responses import RedirectResponse
from urllib.parse import quote

from app.application import student_practice as practice
from app.web.dependencies import templates
from app.web.view_models import build_done_context


router = APIRouter()


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


@router.post("/start")
def start(request: Request, count: str = Form("")):
    try:
        result = practice.start_practice(
            request.cookies.get("student_id"), count
        )
    except practice.PracticeBusy:
        return RedirectResponse("/", status_code=303)
    except ValueError as exc:
        return RedirectResponse(
            f"/?error={quote(str(exc))}", status_code=303
        )
    response = RedirectResponse("/waiting", status_code=303)
    response.set_cookie(
        "student_id", result["student_id"], httponly=True, samesite="lax"
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
        practice.trigger_summary(thread)
    except practice.PracticeBusy:
        return RedirectResponse("/waiting-confirmation", status_code=303)
    return RedirectResponse("/waiting-confirmation", status_code=303)


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
