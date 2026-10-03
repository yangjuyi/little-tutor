"""Web 角色访问控制。"""

from __future__ import annotations

import os
import hashlib
import hmac
import threading
import time
from collections import defaultdict

from fastapi import Request
from fastapi.responses import RedirectResponse


TEACHER_COOKIE = "teacher_token"
TEACHER_THREAD_COOKIE = "teacher_thread_id"
MAX_LOGIN_FAILURES = 5
LOGIN_WINDOW_SECONDS = 300
LOGIN_LOCK_SECONDS = 30

_login_failures: dict[str, list[float]] = defaultdict(list)
_login_locked_until: dict[str, float] = {}
_login_lock = threading.Lock()


def reset_teacher_login_attempts() -> None:
    """清空令牌失败计数，供测试与进程级重载使用。"""
    with _login_lock:
        _login_failures.clear()
        _login_locked_until.clear()


def teacher_login_locked(client_key: str) -> bool:
    """同一来源在窗口期内失败过多时暂时锁定。"""
    now = time.monotonic()
    with _login_lock:
        locked_until = _login_locked_until.get(client_key, 0.0)
        if locked_until > now:
            return True
        if locked_until:
            _login_locked_until.pop(client_key, None)
            _login_failures.pop(client_key, None)
        attempts = [
            value
            for value in _login_failures.get(client_key, [])
            if now - value < LOGIN_WINDOW_SECONDS
        ]
        _login_failures[client_key] = attempts
        return False


def record_teacher_login_failure(client_key: str) -> bool:
    """记录一次失败，并返回记录后是否已触发锁定。"""
    now = time.monotonic()
    with _login_lock:
        attempts = [
            value
            for value in _login_failures.get(client_key, [])
            if now - value < LOGIN_WINDOW_SECONDS
        ]
        attempts.append(now)
        if len(attempts) >= MAX_LOGIN_FAILURES:
            _login_locked_until[client_key] = now + LOGIN_LOCK_SECONDS
            _login_failures[client_key] = []
            return True
        _login_failures[client_key] = attempts
        return False


def clear_teacher_login_failures(client_key: str) -> None:
    with _login_lock:
        _login_failures.pop(client_key, None)
        _login_locked_until.pop(client_key, None)


def teacher_client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def teacher_cookie_value(token: str) -> str:
    return hashlib.sha256(f"little-tutor:{token}".encode("utf-8")).hexdigest()


def _resume_secret() -> str:
    return (
        os.getenv("TUTOR_RESUME_SECRET", "").strip()
        or os.getenv("TUTOR_TEACHER_TOKEN", "").strip()
    )


def resume_token(session_id: str) -> str | None:
    """为跨设备学生恢复链接生成签名；未配置密钥时返回 None。"""
    secret = _resume_secret()
    if not secret:
        return None
    return hmac.new(
        secret.encode("utf-8"),
        f"resume:{session_id}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def valid_resume_token(session_id: str, token: str) -> bool:
    expected = resume_token(session_id)
    if expected is None:
        return True
    return bool(token) and hmac.compare_digest(token, expected)


def teacher_redirect(request: Request) -> RedirectResponse | None:
    """返回老师登录跳转；未配置令牌时按本地演示模式放行。"""
    expected = os.getenv("TUTOR_TEACHER_TOKEN", "").strip()
    if not expected:
        return None
    cookie = request.cookies.get(TEACHER_COOKIE, "")
    if hmac.compare_digest(cookie, teacher_cookie_value(expected)):
        return None
    return RedirectResponse("/teacher/login", status_code=303)
