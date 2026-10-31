"""待扫码的二维码，按租户隔离。

bridge 回调时带着 ``X-Tenant-Id``，服务端在租户上下文里写入；
前端轮询时读到的是自己那份二维码，不会看到别的租户的。
"""

import threading
from typing import Dict, Optional

import tenancy

_pending: Dict[str, Optional[str]] = {}
_lock = threading.Lock()


def _key(tenant_id: Optional[str] = None) -> str:
    if tenant_id:
        return tenant_id
    tenant = tenancy.current()
    return tenant.user_id if tenant else ""


def get_pending_qr(tenant_id: Optional[str] = None) -> Optional[str]:
    with _lock:
        return _pending.get(_key(tenant_id))


def set_pending_qr(qr: Optional[str], tenant_id: Optional[str] = None) -> None:
    with _lock:
        key = _key(tenant_id)
        if qr:
            _pending[key] = qr
        else:
            _pending.pop(key, None)


def clear_pending_qr(tenant_id: Optional[str] = None) -> None:
    set_pending_qr(None, tenant_id)
