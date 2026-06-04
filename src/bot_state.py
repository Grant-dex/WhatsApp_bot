import threading

_paused = False
_lock = threading.Lock()


def is_paused() -> bool:
    with _lock:
        return _paused


def set_paused(paused: bool):
    global _paused
    with _lock:
        _paused = paused


def toggle_paused() -> bool:
    global _paused
    with _lock:
        _paused = not _paused
        return _paused


# ── Batch push tracking ──────────────────────────────────────────

_last_manual_batch_push_date: str = ""

def _today_str() -> str:
    import datetime
    return datetime.datetime.now().strftime("%Y-%m-%d")

def mark_batch_pushed_today():
    global _last_manual_batch_push_date
    _last_manual_batch_push_date = _today_str()

def was_batch_pushed_today() -> bool:
    return _last_manual_batch_push_date == _today_str()
