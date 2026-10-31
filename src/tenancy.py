"""多租户上下文。

设计（路线 B）：每个登录用户拥有一个独立的数据目录，
``data/tenants/<user_id>/``，里面放该用户的 customers.db、config.yaml、
.env、logs/ 和 bridge 的认证目录。所有状态天然隔离，不需要给 13 张表加
tenant_id，也不需要给 55 个接口加过滤条件。

请求进来时由 ``auth`` 中间件解析 session，调用 :func:`set_current` 把租户
写进 contextvar；``config.get_data_dir()`` 和 ``database.get_connection()``
都会读它，于是整个应用“自动”落到当前租户目录里。
"""

from __future__ import annotations

import os
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Optional


@dataclass(frozen=True)
class Tenant:
    """当前请求所属的租户。"""

    user_id: str
    email: str
    data_dir: Path

    @property
    def config_path(self) -> Path:
        return self.data_dir / "config.yaml"

    @property
    def env_path(self) -> Path:
        return self.data_dir / ".env"


_current: ContextVar[Optional[Tenant]] = ContextVar("wa_current_tenant", default=None)


def set_current(tenant: Optional[Tenant]):
    """设置当前租户，返回可用于 reset 的 token。"""
    return _current.set(tenant)


def reset_current(token) -> None:
    _current.reset(token)


def current() -> Optional[Tenant]:
    return _current.get()


def current_data_dir() -> Optional[Path]:
    tenant = _current.get()
    return tenant.data_dir if tenant else None


# ── 目录布局 ────────────────────────────────────────────────────────────

def base_data_dir() -> Path:
    """与 ``config.get_data_dir()`` 一致的“根”数据目录（忽略租户上下文）。

    这里刻意不 import config，避免循环依赖；两处读取的是同一个环境变量。
    """
    raw = os.getenv("WHATSAPP_BOT_DATA_DIR", "").strip()
    return Path(raw) if raw else Path.cwd()


def tenants_root() -> Path:
    return base_data_dir() / "tenants"


def tenant_dir(user_id: str) -> Path:
    return tenants_root() / user_id


def ensure_tenant_dir(user_id: str, template: Optional[Path] = None) -> Path:
    """创建租户目录并补齐默认 config.yaml / logs 目录。"""
    path = tenant_dir(user_id)
    (path / "logs").mkdir(parents=True, exist_ok=True)
    (path / "data").mkdir(parents=True, exist_ok=True)
    cfg = path / "config.yaml"
    if not cfg.exists() and template and template.exists():
        cfg.write_text(template.read_text(encoding="utf-8"), encoding="utf-8")
    return path


# ── 租户级 .env ─────────────────────────────────────────────────────────
# 不能复用 config.load_dotenv()：它会把值写进 os.environ，A 用户的 key 会
# 泄漏给 B 用户。这里按目录缓存，只在本租户的请求里返回。

_env_cache: Dict[str, Dict[str, str]] = {}


def load_tenant_env(data_dir: Path) -> Dict[str, str]:
    key = str(data_dir)
    cached = _env_cache.get(key)
    if cached is not None:
        return cached

    values: Dict[str, str] = {}
    env_file = data_dir / ".env"
    if env_file.exists():
        try:
            for line in env_file.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k:
                    values[k] = v
        except OSError:
            values = {}
    _env_cache[key] = values
    return values


def invalidate_env(data_dir: Path) -> None:
    _env_cache.pop(str(data_dir), None)
