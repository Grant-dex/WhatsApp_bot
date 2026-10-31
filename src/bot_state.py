"""Persistent bot state using SQLite-backed KV store.

State survives process restarts — no more lost pause state or batch-push markers.
"""

import threading
from datetime import datetime
from typing import Optional


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


# ── Proactive follow-up switch ────────────────────────────────────────────────
#
# This is the single backend source of truth for the user-facing "主动自动跟进"
# switch. It intentionally applies to BOTH automatic proactive paths:
#   * the 5-minute due-follow-up check
#   * the daily 10:00 auto-batch push
# Instant replies to inbound customer messages are not gated by this switch;
# they are gated by the global pause, customer contact status and rate limits.
#
# Default is OFF (fail-safe) because the previous UI stored this preference only
# in localStorage and defaulted to unchecked. A browser-side one-time migration
# copies a legacy localStorage value into this backend setting.

PROACTIVE_FOLLOWUPS_KEY = "proactive_followups_enabled"


def _get_optional_state(key: str) -> Optional[str]:
    from database import get_bot_state
    return get_bot_state(key)


def is_proactive_followups_enabled() -> bool:
    return _get_state(PROACTIVE_FOLLOWUPS_KEY, "0") == "1"


def is_proactive_followups_configured() -> bool:
    """True when the user (or the legacy migration) has explicitly set it."""
    return _get_optional_state(PROACTIVE_FOLLOWUPS_KEY) is not None


def set_proactive_followups_enabled(enabled: bool):
    _set_state(PROACTIVE_FOLLOWUPS_KEY, "1" if enabled else "0")


# ── Batch push tracking ──────────────────────────────────────────────────────

def mark_batch_pushed_today():
    _set_state("last_batch_push_date", _today_str())


def was_batch_pushed_today() -> bool:
    return _get_state("last_batch_push_date", "") == _today_str()
