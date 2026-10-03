"""little-tutor Web 应用装配。"""

import logging
import json
import time
import uuid

from fastapi import FastAPI, Request

from app.web.dependencies import templates

from app.web.student import router as student_router
from app.web.teacher import router as teacher_router


logger = logging.getLogger(__name__)

app = FastAPI(title="little-tutor 演示版")


@app.middleware("http")
async def attach_request_id(request: Request, call_next):
    request_id = uuid.uuid4().hex[:12]
    request.state.request_id = request_id
    started = time.perf_counter()
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    logger.info(
        "web_request %s",
        json.dumps(
            {
                "request_id": request_id,
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": round(
                    (time.perf_counter() - started) * 1000,
                    2,
                ),
            },
            ensure_ascii=False,
        ),
    )
    return response


@app.exception_handler(Exception)
async def unhandled_exception_page(request: Request, exc: Exception):
    request_id = getattr(request.state, "request_id", "unknown")
    logger.exception(
        "unhandled web error request_id=%s path=%s",
        request_id,
        request.url.path,
        exc_info=exc,
    )
    response = templates.TemplateResponse(
        request,
        "error.html",
        {
            "message": (
                "系统内部错误，已记录本次请求。"
                f"请求编号：{request_id}"
            ),
            "retry_url": request.headers.get("referer") or "/",
        },
        status_code=500,
    )
    response.headers["X-Request-ID"] = request_id
    return response


app.include_router(student_router)
app.include_router(teacher_router)
