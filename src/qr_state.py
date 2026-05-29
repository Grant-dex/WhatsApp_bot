import threading
from typing import Optional

_pending_qr: Optional[str] = None
_qr_lock = threading.Lock()


def get_pending_qr() -> Optional[str]:
    with _qr_lock:
        return _pending_qr


def set_pending_qr(qr: Optional[str]):
    global _pending_qr
    with _qr_lock:
        _pending_qr = qr


def clear_pending_qr():
    set_pending_qr(None)
