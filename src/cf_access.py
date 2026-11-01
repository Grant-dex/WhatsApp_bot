"""Cloudflare Access 单点登录。

启用后在 Cloudflare 那边通过邮箱验证的用户，不需要再看到应用自己的登录页：
浏览器里带着 ``CF_Authorization`` cookie，服务端拿它去问 Cloudflare
"这个人是谁"（`/cdn-cgi/access/get-identity`），拿到邮箱后自动创建/登录账号。

这样既不用在本地验证 JWT 签名（省掉 pyjwt + cryptography 依赖），
也不会被伪造的请求头欺骗——cookie 是 Cloudflare 签发的，验证也在 Cloudflare 侧。
"""

from __future__ import annotations

import logging
import os
import time
from typing import Dict, Optional, Tuple

import httpx

logger = logging.getLogger(__name__)

COOKIE_NAME = "CF_Authorization"
_cache: Dict[str, Tuple[float, Optional[str]]] = {}
_CACHE_TTL = 30.0


def team_domain() -> str:
    return (os.getenv("CF_ACCESS_TEAM_DOMAIN") or "").strip().rstrip("/")


def enabled() -> bool:
    return bool(team_domain()) and os.getenv("CF_ACCESS_AUTO_LOGIN", "1") != "0"


def identity_email(token: str) -> Optional[str]:
    """用 Cloudflare 的 cookie 换取邮箱；无效或网络失败返回 None。"""
    if not token:
        return None
    domain = team_domain()
    if not domain:
        return None

    now = time.time()
    cached = _cache.get(token)
    if cached and now - cached[0] < _CACHE_TTL:
        return cached[1]

    email: Optional[str] = None
    try:
        with httpx.Client(timeout=5.0, trust_env=False,
                          headers={"Cookie": f"{COOKIE_NAME}={token}"}) as client:
            resp = client.get(f"{domain}/cdn-cgi/access/get-identity")
        if resp.status_code == 200:
            data = resp.json()
            email = (data.get("email") or "").strip().lower() or None
        else:
            logger.info("[cf-access] 身份校验返回 %s", resp.status_code)
    except Exception as exc:
        logger.warning("[cf-access] 校验失败: %s", exc)

    _cache[token] = (now, email)
    # 简单的缓存清理，避免无界增长
    if len(_cache) > 500:
        for key in list(_cache)[:250]:
            _cache.pop(key, None)
    return email
