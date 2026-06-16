import asyncio
import logging
import threading
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from bridge_client import send_message
from config import get_config
from database import get_connection, get_customers_due_for_followup, record_followup, save_message, update_followup_schedule
from followup import generate_followup_message, get_random_delay
from bot_state import is_paused
from agent_brain import daily_agent_workflow

logger = logging.getLogger(__name__)
_check_lock = threading.Lock()


def _count_today_auto_sent() -> int:
    """Return how many auto-generated messages were sent today."""
    try:
        conn = get_connection()
        today = datetime.now().strftime("%Y-%m-%d")
        row = conn.execute(
            "SELECT COUNT(*) as cnt FROM conversations "
            "WHERE ai_generated=1 AND direction='outbound' AND date(sent_at)=?",
            (today,)
        ).fetchone()
        return row["cnt"] if row else 0
    except Exception:
        return 0


def is_quiet_hours() -> bool:
    cfg = get_config()
    now = datetime.now().hour
    s, e = cfg.business.quiet_hours_start, cfg.business.quiet_hours_end
    return (now >= s or now < e) if s > e else (s <= now < e)


async def check_followups():
    if not _check_lock.acquire(blocking=False):
        return
    try:
        if is_paused():
            logger.info("Follow-up check skipped: bot is paused")
            return
        if is_quiet_hours():
            return
        cfg = get_config()
        daily_limit = cfg.business.max_auto_replies_per_day
        already_sent = _count_today_auto_sent()
        remaining = daily_limit - already_sent
        if remaining <= 0:
            logger.info(f"Follow-up check: daily limit reached ({already_sent}/{daily_limit})")
            return

        # ── Agent Brain: get prioritized targets ──
        from scoring_engine import prioritize_daily_targets
        targets = prioritize_daily_targets(remaining)
        if not targets:
            return

        sent = 0
        for target in targets:
            if sent >= remaining:
                logger.info(f"Follow-up check: daily limit hit ({already_sent + sent}/{daily_limit})")
                break
            if is_quiet_hours():
                break
            customer = target
            # ── Build strategy context for personalized messaging ──
            from database import get_memory_summary, get_connection as _get_conn
            from country_utils import get_country_from_phone

            # Determine country for context
            phone = customer.get("phone", "")
            country_name = ""
            try:
                ci = get_country_from_phone(phone)
                country_name = ci.get("country_name", "")
            except Exception:
                pass

            # Check if customer has recent activity
            conn2 = _get_conn()
            last_msg = conn2.execute(
                "SELECT MAX(sent_at) FROM conversations WHERE customer_id=?",
                (customer["customer_id"],)
            ).fetchone()
            has_recent = False
            if last_msg and last_msg[0]:
                try:
                    from datetime import datetime as dt, timedelta
                    days_since = (dt.now() - dt.fromisoformat(last_msg[0])).days
                    has_recent = days_since <= 14
                except Exception:
                    pass

            strategy_ctx = {
                "message_type": target.get("strategy", "casual_checkin"),
                "segment": target.get("segment", "new"),
                "memory_summary": get_memory_summary(target["customer_id"]),
                "country": country_name,
                "has_recent_activity": has_recent,
            }
            message = generate_followup_message(customer, strategy_context=strategy_ctx)
            result = await send_message(customer["phone"], message)
            cid = customer["customer_id"]
            sid = customer["schedule_id"]
            if result.get("status") == "sent":
                conv_id = save_message(cid, "outbound", message, ai_generated=True)
                record_followup(cid, sid, conv_id, status="sent")
                update_followup_schedule(sid)
                sent += 1
            else:
                record_followup(cid, sid, None, status="failed", error_message=result.get("error", "unknown"))
            await asyncio.sleep(get_random_delay())
        logger.info(f"Follow-up: {sent} sent, {len(targets)-sent} failed "
                     f"({already_sent + sent}/{daily_limit} daily)")
    except Exception as e:
        logger.error(f"Follow-up error: {e}", exc_info=True)
    finally:
        _check_lock.release()


def run_check_followups():
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(check_followups())
    finally:
        loop.close()


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
                f"+ daily agent workflow at 08:00 + daily auto-batch at 10:00")
    return scheduler


def run_daily_agent_workflow():
    """Wrapper to run the async daily agent workflow in the scheduler thread."""
    try:
        daily_agent_workflow()
    except Exception as e:
        logger.error(f"Daily agent workflow error: {e}", exc_info=True)


async def auto_batch_push():
    """Daily auto-batch-push: if no manual batch push was done today, send all due followups."""
    from bot_state import was_batch_pushed_today
    if was_batch_pushed_today():
        logger.info("Auto-batch skipped: manual batch push already done today")
        return
    if not _check_lock.acquire(blocking=False):
        return
    try:
        if is_paused():
            logger.info("Auto-batch skipped: bot is paused")
            return
        if is_quiet_hours():
            logger.info("Auto-batch skipped: quiet hours")
            return
        cfg = get_config()
        daily_limit = cfg.business.max_auto_replies_per_day
        already_sent = _count_today_auto_sent()
        remaining = daily_limit - already_sent
        if remaining <= 0:
            logger.info(f"Auto-batch: daily limit reached ({already_sent}/{daily_limit})")
            return

        # ── Agent Brain: get prioritized targets ──
        from scoring_engine import prioritize_daily_targets
        targets = prioritize_daily_targets(remaining)
        if not targets:
            logger.info("Auto-batch: no due followups")
            return

        logger.info(f"Auto-batch: sending followups to up to {min(len(targets), remaining)}/{len(targets)} candidates (daily: {already_sent}/{daily_limit})")
        sent = 0
        for target in targets:
            if sent >= remaining:
                logger.info(f"Auto-batch: daily limit hit ({already_sent + sent}/{daily_limit})")
                break
            if is_quiet_hours():
                break
            customer = target
            from database import get_memory_summary, get_connection as _get_conn2
            from country_utils import get_country_from_phone

            phone = customer.get("phone", "")
            country_name = ""
            try:
                ci = get_country_from_phone(phone)
                country_name = ci.get("country_name", "")
            except Exception:
                pass

            conn3 = _get_conn2()
            last_msg = conn3.execute(
                "SELECT MAX(sent_at) FROM conversations WHERE customer_id=?",
                (customer["customer_id"],)
            ).fetchone()
            has_recent = False
            if last_msg and last_msg[0]:
                try:
                    days_since = (datetime.now() - datetime.fromisoformat(last_msg[0])).days
                    has_recent = days_since <= 14
                except Exception:
                    pass

            strategy_ctx = {
                "message_type": target.get("strategy", "casual_checkin"),
                "segment": target.get("segment", "new"),
                "memory_summary": get_memory_summary(target["customer_id"]),
                "country": country_name,
                "has_recent_activity": has_recent,
            }
            message = generate_followup_message(customer, strategy_context=strategy_ctx)
            result = await send_message(customer["phone"], message)
            cid = customer["customer_id"]
            sid = customer["schedule_id"]
            if result.get("status") == "sent":
                conv_id = save_message(cid, "outbound", message, ai_generated=True)
                record_followup(cid, sid, conv_id, status="sent")
                update_followup_schedule(sid)
                sent += 1
            else:
                record_followup(cid, sid, None, status="failed", error_message=result.get("error", "unknown"))
            await asyncio.sleep(120)  # 2 min interval for auto-batch
        logger.info(f"Auto-batch complete: {sent}/{len(targets)} sent")
    except Exception as e:
        logger.error(f"Auto-batch error: {e}", exc_info=True)
    finally:
        _check_lock.release()


def run_auto_batch_push():
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(auto_batch_push())
    finally:
        loop.close()


def _wal_checkpoint():
    """Periodically checkpoint SQLite WAL to prevent unbounded growth."""
    try:
        from database import get_connection
        conn = get_connection()
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE);")
    except Exception as e:
        logger.warning(f"WAL checkpoint failed: {e}")
