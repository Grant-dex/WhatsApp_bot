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
