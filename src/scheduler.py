import asyncio
import logging
import threading
from datetime import datetime

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from bridge_client import send_message
from config import get_config
from database import get_customers_due_for_followup, record_followup, save_message, update_followup_schedule
from followup import generate_followup_message, get_random_delay
from bot_state import is_paused

logger = logging.getLogger(__name__)
_check_running = False


def is_quiet_hours() -> bool:
    cfg = get_config()
    now = datetime.now().hour
    s, e = cfg.business.quiet_hours_start, cfg.business.quiet_hours_end
    return (now >= s or now < e) if s > e else (s <= now < e)


async def check_followups():
    global _check_running
    if _check_running:
        return
    _check_running = True
    try:
        if is_paused():
            logger.info("Follow-up check skipped: bot is paused")
            return
        if is_quiet_hours():
            return
        candidates = get_customers_due_for_followup()
        if not candidates:
            return
        sent = 0
        for customer in candidates:
            if is_quiet_hours():
                break
            message = generate_followup_message(customer)
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
        logger.info(f"Follow-up: {sent} sent, {len(candidates)-sent} failed")
    except Exception as e:
        logger.error(f"Follow-up error: {e}", exc_info=True)
    finally:
        _check_running = False


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
    scheduler.start()
    logger.info(f"Scheduler started: every {config.scheduler.followup_check_interval_minutes}min")
    return scheduler
