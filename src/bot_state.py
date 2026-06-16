"""Persistent bot state using SQLite-backed KV store.

State survives process restarts — no more lost pause state or batch-push markers.
"""

import threading
from datetime import datetime


def _today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _get_state(key: str, default: str = "") -> str:
    """Read a state value from the database."""
    from database import get_bot_state
    val = get_bot_state(key)
    return val if val is not None else default


def _set_state(key: str, value: str):
    """Write a state value to the database."""
    from database import set_bot_state
    set_bot_state(key, value)


# ── Bot Pause/Resume ─────────────────────────────────────────────────────────

_lock = threading.Lock()


def is_paused() -> bool:
    return _get_state("paused", "0") == "1"


def set_paused(paused: bool):
    _set_state("paused", "1" if paused else "0")


def toggle_paused() -> bool:
    with _lock:
        new_state = not is_paused()
        _set_state("paused", "1" if new_state else "0")
        return new_state


# ── Batch push tracking ──────────────────────────────────────────────────────

def mark_batch_pushed_today():
    _set_state("last_batch_push_date", _today_str())


def was_batch_pushed_today() -> bool:
    return _get_state("last_batch_push_date", "") == _today_str()
