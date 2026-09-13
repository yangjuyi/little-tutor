"""Web 角色访问控制。"""

from __future__ import annotations

import os
import hashlib
import hmac

from fastapi import Request
from fastapi.responses import RedirectResponse


TEACHER_COOKIE = "teacher_token"


def teacher_cookie_value(token: str) -> str:
    return hashlib.sha256(f"little-tutor:{token}".encode("utf-8")).hexdigest()


def teacher_redirect(request: Request) -> RedirectResponse | None:
    """返回老师登录跳转；未配置令牌时按本地演示模式放行。"""
    expected = os.getenv("TUTOR_TEACHER_TOKEN", "").strip()
    if not expected:
        return None
    cookie = request.cookies.get(TEACHER_COOKIE, "")
    if hmac.compare_digest(cookie, teacher_cookie_value(expected)):
        return None
    return RedirectResponse("/teacher/login", status_code=303)
