"""Automated follow-up scheduling.

Both automatic proactive paths (the 5-minute due check and the daily 10:00
batch) call the same send service and therefore honour the same backend
proactive switch, global pause, customer status, schedule validity, quiet hours
and atomically reserved daily quota. The switch is read at execution time, not
cached at start-up.
"""
import asyncio
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Iterator, Optional

import tenancy
from tenancy import Tenant

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from bot_state import is_paused, is_proactive_followups_enabled, was_batch_pushed_today
from config import get_config
from database import get_connection, get_daily_quota_usage
from followup import get_random_delay
from send_service import is_quiet_hours, send_followup_now

logger = logging.getLogger(__name__)
_check_lock = threading.Lock()


# ── 多租户：每个用户各跑一遍 ────────────────────────────────────────────

def _iter_tenants() -> Iterator[Optional[Tenant]]:
    """依次产出已注册用户；一个都没注册时退回无租户模式跑一次。"""
    import accounts

    try:
        users = accounts.list_users()
    except Exception:
        logger.exception("读取账号列表失败，退回单租户模式")
        users = []
    if not users:
        yield None
        return
    for user in users:
        yield Tenant(user_id=user["id"], email=user["email"],
                     data_dir=Path(user["data_dir"]))


def _run_for_tenants(job) -> None:
    for tenant in _iter_tenants():
        token = tenancy.set_current(tenant) if tenant else None
        try:
            job()
        except Exception:
            logger.exception("定时任务失败 tenant=%s",
                             tenant.user_id if tenant else "default")
        finally:
            if token is not None:
                tenancy.reset_current(token)


def _count_today_auto_sent() -> int:
    """Return confirmed proactive sends today (pending/failed/unknown excluded)."""
    try:
        conn = get_connection()
        today = datetime.now().strftime("%Y-%m-%d")
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM conversations "
            "WHERE direction='outbound' AND status='sent' AND send_kind='proactive' "
            "AND date(sent_at)=?",
            (today,),
        ).fetchone()
        return row["cnt"] if row else 0
    except Exception:
        return 0


def _remaining_quota() -> tuple[int, int, int, int]:
    cfg = get_config()
    daily_limit = cfg.business.max_auto_replies_per_day
    usage = get_daily_quota_usage()
    remaining = max(0, daily_limit - usage["total"])
    return daily_limit, usage["total"], usage["used"], remaining


def _stop_reason(result: dict) -> str | None:
    """Return a reason when the rest of the batch must stop."""
    if result.get("status") == "blocked":
        reason = result.get("reason")
        if reason in ("bot_paused", "proactive_disabled", "quota_exceeded", "quiet_hours"):
            return reason
    return None


async def _run_followup_pass(label: str, inter_message_delay) -> dict:
    if not _check_lock.acquire(blocking=False):
        logger.info("%s: another follow-up pass is already running", label)
        return {"skipped": "already_running"}

    sent = 0
    unknown = 0
    failed = 0
    blocked = 0
    try:
        # Re-read at execution time: the user may have switched the feature off
        # or paused the bot after the scheduler was created.
        if is_paused():
            logger.info("%s skipped: bot is paused", label)
            return {"skipped": "bot_paused"}
        if not is_proactive_followups_enabled():
            logger.info("%s skipped: proactive follow-ups disabled", label)
            return {"skipped": "proactive_disabled"}
        if is_quiet_hours():
            logger.info("%s skipped: quiet hours", label)
            return {"skipped": "quiet_hours"}

        daily_limit, used_and_reserved, confirmed, remaining = _remaining_quota()
        if remaining <= 0:
            logger.info("%s: daily quota reached (%s/%s)", label, used_and_reserved, daily_limit)
            return {"skipped": "quota_exceeded"}

        from scoring_engine import prioritize_daily_targets
        targets = prioritize_daily_targets(remaining)
        if not targets:
            logger.info("%s: no due follow-ups", label)
            return {"targets": 0}

        for target in targets:
            # The send service re-checks pause/switch/status/schedule/quiet and
            # reserves quota immediately before every individual send.
            result = await send_followup_now(target["schedule_id"], manual=False)
            status = result.get("status")
            if status == "sent":
                sent += 1
            elif status == "unknown":
                unknown += 1
            elif status == "blocked":
                blocked += 1
            else:
                failed += 1

            stop = _stop_reason(result)
            if stop:
                logger.info("%s stopped early: %s", label, stop)
                break
            await asyncio.sleep(inter_message_delay)

        logger.info(
            "%s complete: sent=%s unknown=%s failed=%s blocked=%s (quota %s/%s)",
            label, sent, unknown, failed, blocked,
            _remaining_quota()[1], daily_limit,
        )
        return {"sent": sent, "unknown": unknown, "failed": failed,
                "blocked": blocked}
    except Exception as e:
        logger.error("%s error: %s", label, e, exc_info=True)
        return {"error": str(e)}
    finally:
        _check_lock.release()


async def check_followups():
    """5-minute due-follow-up check. No longer bypasses the proactive switch."""
    return await _run_followup_pass("Follow-up check", get_random_delay())


def _check_followups_once():
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(check_followups())
    finally:
        loop.close()


def run_check_followups():
    """每个租户各检查一次到期跟进。"""
    _run_for_tenants(_check_followups_once)


def start_scheduler():
    config = get_config()
    scheduler = BackgroundScheduler(timezone=config.app.timezone)
    scheduler.add_job(run_check_followups, trigger=IntervalTrigger(minutes=config.scheduler.followup_check_interval_minutes),
                      id="followup_check", replace_existing=True)
    scheduler.add_job(
        _wal_checkpoint,
        trigger=IntervalTrigger(minutes=30),
        id="wal_checkpoint", replace_existing=True
    )
    # Daily auto-batch push at 10:00 AM
    scheduler.add_job(
        run_auto_batch_push,
        trigger=IntervalTrigger(hours=24, start_date=f"{datetime.now().strftime('%Y-%m-%d')} 10:00:00"),
        id="auto_batch_push", replace_existing=True
    )
    # Daily agent morning workflow at 8:00 AM
    scheduler.add_job(
        run_daily_agent_workflow,
        trigger=IntervalTrigger(hours=24, start_date=f"{datetime.now().strftime('%Y-%m-%d')} 08:00:00"),
        id="daily_agent_workflow", replace_existing=True
    )
    scheduler.start()
    logger.info(f"Scheduler started: every {config.scheduler.followup_check_interval_minutes}min "
                f"+ daily agent workflow at 08:00 + daily auto-batch at 10:00 "
                f"(proactive switch={'on' if is_proactive_followups_enabled() else 'off'})")
    return scheduler


def _daily_agent_workflow_once():
    from agent_brain import daily_agent_workflow
    daily_agent_workflow()


def run_daily_agent_workflow():
    """每个租户各跑一次每日 agent 工作流。"""
    _run_for_tenants(_daily_agent_workflow_once)


async def auto_batch_push():
    """Daily 10:00 auto-batch-push.

    This path is gated by the same proactive switch as the 5-minute check. It
    is skipped when a manual batch was confirmed and started today.
    """
    if was_batch_pushed_today():
        logger.info("Auto-batch skipped: manual batch push already started today")
        return {"skipped": "manual_batch_already_started"}
    return await _run_followup_pass("Auto-batch", 120)


def _auto_batch_push_once():
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(auto_batch_push())
    finally:
        loop.close()


def run_auto_batch_push():
    """每个租户各跑一次 10:00 自动跟进。"""
    _run_for_tenants(_auto_batch_push_once)


def _wal_checkpoint():
    """Periodically checkpoint SQLite WAL to prevent unbounded growth."""
    try:
        from database import get_connection
        conn = get_connection()
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
    except Exception as e:
        logger.warning(f"WAL checkpoint failed: {e}")
