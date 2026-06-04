import logging
from typing import Optional

from ai_reply import check_rate_limits, generate_reply, should_auto_reply, summarize_and_remember
from database import ensure_followup_schedule, get_or_create_customer, save_message
from bot_state import is_paused

logger = logging.getLogger(__name__)


async def handle_incoming_message(phone: str, body: str, msg_id: Optional[str] = None) -> dict:
    customer = get_or_create_customer(phone)
    if customer["status"] in ("opted_out", "blocked"):
        return {"action": "ignore", "reason": customer["status"]}

    if is_paused():
        return {"action": "ignore", "reason": "bot_paused"}

    if save_message(customer["id"], "inbound", body, whatsapp_msg_id=msg_id) is None:
        return {"action": "ignore", "reason": "duplicate"}

    ensure_followup_schedule(customer["id"])

    if not should_auto_reply(body):
        return {"action": "ignore", "reason": "no_reply_needed"}

    allowed, reason = check_rate_limits(customer["id"])
    if not allowed:
        return {"action": "ignore", "reason": reason}

    reply = generate_reply(customer, body)
    save_message(customer["id"], "outbound", reply, ai_generated=True)
    summarize_and_remember(customer["id"], body, reply)
    logger.info(f"Reply to {phone}: {reply[:60]}")
    return {"action": "reply", "message": reply, "delay_seconds": 3}
