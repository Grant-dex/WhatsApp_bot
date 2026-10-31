"""每租户一个 WhatsApp Bridge 进程。

一个 Node 进程只能登录一个 WhatsApp 账号，所以多租户必须一租户一进程：
端口从池子里分配，会话目录落在各自的 ``<data_dir>/data/.baileys-auth``，
进程环境里带上 ``WA_TENANT_ID``，让 webhook 回调能认领到正确的租户。
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import socket
import subprocess
import threading
import time
from pathlib import Path
from typing import Dict, Optional

import tenancy
from config import get_config
from tenancy import Tenant

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
_PORT_BASE = 3101
_PORT_MAX = 3999

_lock = threading.RLock()
_procs: Dict[str, subprocess.Popen] = {}
_ports: Dict[str, int] = {}


def _registry_path() -> Path:
    return tenancy.base_data_dir() / "bridges.json"


def _load_registry() -> None:
    path = _registry_path()
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return
    for tenant_id, info in (data or {}).items():
        port = info.get("port")
        if isinstance(port, int):
            _ports.setdefault(tenant_id, port)


def _save_registry() -> None:
    path = _registry_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {tid: {"port": port} for tid, port in _ports.items()}
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tmp.replace(path)


_load_registry()


# ── 端口 ────────────────────────────────────────────────────────────────

def _port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def _alive(port: int, timeout: float = 0.6) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout):
            return True
    except OSError:
        return False


def _allocate_port() -> int:
    used = set(_ports.values())
    for port in range(_PORT_BASE, _PORT_MAX + 1):
        if port in used or not _port_free(port):
            continue
        return port
    raise RuntimeError("没有可用的 bridge 端口")


def port_for(tenant_id: str) -> Optional[int]:
    return _ports.get(tenant_id)


def current_port() -> int:
    """当前请求租户的 bridge 端口；没有租户时退回配置里的默认端口。"""
    tenant = tenancy.current()
    if tenant is not None:
        port = _ports.get(tenant.user_id)
        if port:
            return port
    return get_config().bridge.port


# ── 进程 ────────────────────────────────────────────────────────────────

def _node_bin() -> str:
    node = shutil.which("node")
    if not node:
        raise RuntimeError("找不到 node，请先安装 Node.js")
    return node


def _api_port() -> int:
    return get_config().api.port


def _log_path(data_dir: Path) -> Path:
    logs = data_dir / "logs"
    logs.mkdir(parents=True, exist_ok=True)
    return logs / "bridge.log"


def start(tenant: Tenant) -> dict:
    """确保该租户的 bridge 在运行，返回状态。"""
    with _lock:
        proc = _procs.get(tenant.user_id)
        port = _ports.get(tenant.user_id)

        if port and _alive(port) and (proc is None or proc.poll() is None):
            return {"online": True, "port": port, "started": False}

        if (ROOT / "bridge" / "index.js").exists() is False:
            raise RuntimeError("缺少 bridge/index.js")
        if not (ROOT / "bridge" / "node_modules").exists():
            raise RuntimeError("bridge 依赖未安装：npm --prefix bridge install")

        port = _allocate_port()
        env = os.environ.copy()
        env.update({
            "WHATSAPP_BOT_DATA_DIR": str(tenant.data_dir),
            "WA_TENANT_ID": tenant.user_id,
            "BRIDGE_PORT": str(port),
            "BRIDGE_HOST": "127.0.0.1",
            "PYTHON_API": f"http://127.0.0.1:{_api_port()}",
            "NO_PROXY": "127.0.0.1,localhost",
            "no_proxy": "127.0.0.1,localhost",
        })

        log = open(_log_path(tenant.data_dir), "a", encoding="utf-8")
        proc = subprocess.Popen(
            [_node_bin(), str(ROOT / "bridge" / "index.js")],
            cwd=str(ROOT), env=env,
            stdout=log, stderr=subprocess.STDOUT,
        )
        _procs[tenant.user_id] = proc
        _ports[tenant.user_id] = port
        _save_registry()

        logger.info("[bridge] 启动租户 %s 的 bridge: pid=%s port=%s",
                    tenant.user_id, proc.pid, port)

        # 等端口起来（最多 8 秒）
        for _ in range(32):
            if _alive(port):
                break
            if proc.poll() is not None:
                raise RuntimeError("bridge 启动失败，查看 data/logs/bridge.log")
            time.sleep(0.25)

        return {"online": _alive(port), "port": port, "pid": proc.pid, "started": True}


def stop(tenant_id: str) -> None:
    with _lock:
        proc = _procs.pop(tenant_id, None)
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        _ports.pop(tenant_id, None)
        _save_registry()


def status(tenant: Optional[Tenant] = None) -> dict:
    tenant = tenant or tenancy.current()
    if tenant is None:
        return {"online": False, "port": None, "reason": "no tenant"}
    port = _ports.get(tenant.user_id)
    proc = _procs.get(tenant.user_id)
    online = bool(port) and _alive(port)
    return {
        "online": online,
        "port": port,
        "pid": proc.pid if proc and proc.poll() is None else None,
        "running": bool(proc and proc.poll() is None),
    }


def shutdown_all() -> None:
    for tenant_id in list(_procs):
        try:
            stop(tenant_id)
        except Exception:
            logger.exception("[bridge] 停止租户 %s 失败", tenant_id)
