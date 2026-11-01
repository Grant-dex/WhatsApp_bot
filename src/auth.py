"""认证：登录页、登录/注册接口、会话中间件。

中间件负责把 cookie 里的 session 解析成 :class:`tenancy.Tenant` 并写入
contextvar，后续所有 ``get_config()`` / ``get_connection()`` 都会落到该租户
的数据目录。
"""

from __future__ import annotations

import logging
import os
import secrets
import time
from collections import deque
from pathlib import Path
from typing import Deque, Dict, Optional, Tuple
from urllib.parse import quote

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response

import accounts
import cf_access
import tenancy
from tenancy import Tenant

logger = logging.getLogger(__name__)

router = APIRouter()

# 不需要登录就能访问的路径
_PUBLIC_EXACT = {"/login", "/health", "/favicon.ico", "/robots.txt"}
_PUBLIC_PREFIXES = ("/assets/", "/api/auth/")

_ALLOW_SIGNUP = os.getenv("WA_ALLOW_SIGNUP", "1") not in ("0", "false", "no")


# ── 登录限流（内存，单进程足够） ─────────────────────────────────────────

_MAX_FAILS = 5
_WINDOW = 10 * 60
_LOCK = 5 * 60
_fails: Dict[Tuple[str, str], Deque[float]] = {}
_locked_until: Dict[Tuple[str, str], float] = {}


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else ""


def _check_rate_limit(key: Tuple[str, str]) -> Optional[int]:
    now = time.time()
    until = _locked_until.get(key)
    if until and until > now:
        return int(until - now)
    return None


def _record_failure(key: Tuple[str, str]) -> None:
    now = time.time()
    bucket = _fails.setdefault(key, deque())
    bucket.append(now)
    while bucket and now - bucket[0] > _WINDOW:
        bucket.popleft()
    if len(bucket) >= _MAX_FAILS:
        _locked_until[key] = now + _LOCK
        bucket.clear()


def _clear_failures(key: Tuple[str, str]) -> None:
    _fails.pop(key, None)
    _locked_until.pop(key, None)


# ── 工具 ────────────────────────────────────────────────────────────────

def _is_https(request: Request) -> bool:
    proto = request.headers.get("x-forwarded-proto", "")
    if proto:
        return proto.split(",")[0].strip() == "https"
    return request.url.scheme == "https"


def _set_session_cookie(response: Response, token: str, request: Request) -> None:
    response.set_cookie(
        accounts.SESSION_COOKIE,
        token,
        max_age=accounts.SESSION_TTL_DAYS * 24 * 3600,
        httponly=True,
        samesite="lax",
        secure=_is_https(request),
        path="/",
    )


def _origin_ok(request: Request) -> bool:
    """防 CSRF：带 Origin 的写请求必须同源。"""
    origin = request.headers.get("origin")
    if not origin:
        return True
    host = request.headers.get("host", "")
    return origin.split("://")[-1].split("/")[0] == host


def _login_html() -> str:
    path = Path(__file__).resolve().parent / "static" / "login.html"
    return path.read_text(encoding="utf-8")


# ── 页面 ────────────────────────────────────────────────────────────────

@router.get("/login")
async def login_page(request: Request):
    # 已经过了 Cloudflare Access 的人不该再看到登录页
    if cf_access.enabled() and request.cookies.get(cf_access.COOKIE_NAME):
        result = _cf_login(request)
        if result:
            _, token = result
            resp = RedirectResponse("/", status_code=302)
            _set_session_cookie(resp, token, request)
            return resp
    return HTMLResponse(_login_html())


# ── 接口 ────────────────────────────────────────────────────────────────

@router.get("/api/auth/status")
async def auth_status(request: Request):
    token = request.cookies.get(accounts.SESSION_COOKIE)
    session = accounts.resolve_session(token) if token else None
    return {
        "has_users": accounts.count_users() > 0,
        "authed": bool(session),
        "email": session["email"] if session else None,
        "allow_signup": _ALLOW_SIGNUP,
    }


@router.post("/api/auth/bootstrap")
async def bootstrap(request: Request):
    """第一次运行：创建管理员账号，并接管已有的 data/ 目录。"""
    if not _origin_ok(request):
        return JSONResponse({"error": "bad origin"}, status_code=403)
    if accounts.count_users() > 0:
        return JSONResponse({"error": "已经初始化过了，请直接登录"}, status_code=409)

    body = await request.json()
    email = (body.get("email") or "").strip()
    password = body.get("password") or ""
    try:
        user = accounts.create_user(
            email, password, tenancy.base_data_dir(), is_owner=True)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    token = accounts.create_session(user["id"], _client_ip(request),
                                    request.headers.get("user-agent", ""))
    logger.info("[auth] 初始化管理员账号 %s -> %s", user["email"], user["data_dir"])
    resp = JSONResponse({"ok": True, "email": user["email"]})
    _set_session_cookie(resp, token, request)
    return resp


@router.post("/api/auth/register")
async def register(request: Request):
    if not _origin_ok(request):
        return JSONResponse({"error": "bad origin"}, status_code=403)
    if not _ALLOW_SIGNUP:
        return JSONResponse({"error": "注册已关闭"}, status_code=403)

    body = await request.json()
    email = (body.get("email") or "").strip()
    password = body.get("password") or ""

    # 先校验邮箱格式，避免建了目录才发现重名
    if "@" not in email or len(email) < 5:
        return JSONResponse({"error": "邮箱格式不正确"}, status_code=400)
    if accounts.get_user_by_email(email):
        return JSONResponse({"error": "该邮箱已注册"}, status_code=409)

    import uuid
    user_id = uuid.uuid4().hex
    template = Path(__file__).resolve().parent.parent / "config.yaml"
    data_dir = tenancy.ensure_tenant_dir(user_id, template=template)

    try:
        user = accounts.create_user(email, password, data_dir, user_id=user_id)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    token = accounts.create_session(user["id"], _client_ip(request),
                                    request.headers.get("user-agent", ""))
    logger.info("[auth] 新用户注册 %s -> %s", user["email"], user["data_dir"])
    resp = JSONResponse({"ok": True, "email": user["email"]})
    _set_session_cookie(resp, token, request)
    return resp


@router.post("/api/auth/login")
async def login(request: Request):
    if not _origin_ok(request):
        return JSONResponse({"error": "bad origin"}, status_code=403)
    body = await request.json()
    email = (body.get("email") or "").strip()
    password = body.get("password") or ""

    key = (_client_ip(request), email.lower())
    wait = _check_rate_limit(key)
    if wait:
        return JSONResponse(
            {"error": f"尝试次数过多，请 {wait // 60 + 1} 分钟后再试"},
            status_code=429)

    user = accounts.authenticate(email, password)
    if not user:
        _record_failure(key)
        return JSONResponse({"error": "邮箱或密码不正确"}, status_code=401)

    _clear_failures(key)
    token = accounts.create_session(user["id"], _client_ip(request),
                                    request.headers.get("user-agent", ""))
    logger.info("[auth] 登录成功 %s", user["email"])
    resp = JSONResponse({"ok": True, "email": user["email"]})
    _set_session_cookie(resp, token, request)
    return resp


@router.post("/api/auth/logout")
async def logout(request: Request):
    token = request.cookies.get(accounts.SESSION_COOKIE)
    if token:
        accounts.revoke_session(token)
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(accounts.SESSION_COOKIE, path="/")
    return resp


@router.get("/api/auth/me")
async def me(request: Request):
    token = request.cookies.get(accounts.SESSION_COOKIE)
    session = accounts.resolve_session(token) if token else None
    if not session:
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    return {"email": session["email"], "user_id": session["user_id"]}


# ── 中间件 ──────────────────────────────────────────────────────────────

def _is_public(path: str) -> bool:
    if path in _PUBLIC_EXACT:
        return True
    return any(path.startswith(p) for p in _PUBLIC_PREFIXES)


def _is_local(request: Request) -> bool:
    host = request.client.host if request.client else ""
    return host in ("127.0.0.1", "::1", "localhost")


def _provision_from_email(email: str) -> dict:
    """CF Access 验证过的邮箱首次登录时，自动开一个租户。"""
    import uuid

    user_id = uuid.uuid4().hex
    template = Path(__file__).resolve().parent.parent / "config.yaml"
    data_dir = tenancy.ensure_tenant_dir(user_id, template=template)
    password = secrets.token_urlsafe(24)  # 随机密码，用户走 SSO 不需要它
    user = accounts.create_user(email, password, data_dir, user_id=user_id)
    logger.info("[auth] SSO 自动开通租户 %s -> %s", email, data_dir)
    return user


def _cf_login(request: Request):
    """尝试用 Cloudflare Access 的身份直接登录；成功返回 (session, new_token)。"""
    if not cf_access.enabled():
        return None
    cf_token = request.cookies.get(cf_access.COOKIE_NAME)
    email = cf_access.identity_email(cf_token) if cf_token else None
    if not email:
        return None

    user = accounts.get_user_by_email(email)
    if user is None:
        try:
            user = _provision_from_email(email)
        except ValueError:
            user = accounts.get_user_by_email(email)
        except Exception:
            logger.exception("[auth] SSO 自动开通失败 %s", email)
            return None
    if not user or user.get("status") != "active":
        return None

    token = accounts.create_session(user["id"], _client_ip(request),
                                    request.headers.get("user-agent", ""))
    logger.info("[auth] SSO 登录 %s", email)
    return ({"user_id": user["id"], "email": user["email"],
             "data_dir": user["data_dir"]}, token)


async def middleware(request: Request, call_next):
    path = request.url.path

    if _is_public(path):
        return await call_next(request)

    # 桥接进程回调本机 webhook，不走用户会话
    if path.startswith("/webhook/") and _is_local(request):
        return await call_next(request)

    token = request.cookies.get(accounts.SESSION_COOKIE)
    session = accounts.resolve_session(token) if token else None

    new_token = None
    if not session:
        # 走 Cloudflare Access 的单点登录：过一次验证就直接进
        cf_result = _cf_login(request)
        if cf_result:
            session, new_token = cf_result

    if not session:
        if path.startswith(("/api/", "/admin/api/")):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        target = "/login"
        if path not in ("/", ""):
            target += "?next=" + quote(path)
        return RedirectResponse(target, status_code=302)

    data_dir = Path(session["data_dir"])
    data_dir.mkdir(parents=True, exist_ok=True)
    tenant = Tenant(user_id=session["user_id"], email=session["email"], data_dir=data_dir)
    cv_token = tenancy.set_current(tenant)
    try:
        response = await call_next(request)
    finally:
        tenancy.reset_current(cv_token)
    if new_token:
        _set_session_cookie(response, new_token, request)
    return response


async def security_headers(request: Request, call_next):
    """基础安全响应头（点击劫持、MIME 嗅探、API 缓存）。"""
    response = await call_next(request)
    headers = response.headers
    headers.setdefault("X-Content-Type-Options", "nosniff")
    headers.setdefault("X-Frame-Options", "DENY")
    headers.setdefault("Referrer-Policy", "same-origin")
    if request.url.path.startswith(("/api/", "/admin/api/", "/webhook/")):
        headers.setdefault("Cache-Control", "no-store")
    return response


def install(app) -> None:
    """把认证与安全中间件挂到 FastAPI 应用上。"""
    app.middleware("http")(middleware)
    app.middleware("http")(security_headers)
    app.include_router(router)
