"""Inbound message handling.

Ordering matters: persist and de-duplicate the inbound message first, THEN
decide whether any automatic action is allowed. Pausing the bot or marking a
customer as opted_out/blocked/inactive must never lose the customer's message.
"""
import logging
from typing import Optional

from ai_reply import check_rate_limits, generate_reply, should_auto_reply
from database import ensure_followup_schedule, get_or_create_customer, save_message
from bot_state import is_paused
from memory_engine import extract_and_store_memory

logger = logging.getLogger(__name__)

# Statuses that may still receive/store messages but must never get an
# automatic reply or proactive follow-up.
NO_REPLY_STATUSES = ("opted_out", "blocked", "inactive")


async def handle_incoming_message(phone: str, body: str, msg_id: Optional[str] = None) -> dict:
    customer = get_or_create_customer(phone)

    # 1) Persist first. Duplicate platform message ids are ignored atomically.
    #    A short content window is used only when the bridge did not supply an
    #    id, so retried webhooks cannot create duplicate history entries.
    inbound_id = save_message(
        customer["id"], "inbound", body,
        whatsapp_msg_id=msg_id,
        status="received",
        send_kind="inbound",
        dedupe_content_window_seconds=5,
    )
    if inbound_id is None:
        return {"action": "ignore", "reason": "duplicate", "stored": False}

    base = {"stored": True, "conversation_id": inbound_id,
            "customer_id": customer["id"]}

    # 2) Contact status only suppresses replies, not storage.
    if customer["status"] in NO_REPLY_STATUSES:
        logger.info("Inbound stored without reply: customer=%s status=%s",
                    customer["id"], customer["status"])
        return {**base, "action": "ignore", "reason": customer["status"],
                "reply_blocked_by": "contact_status"}

    # 3) Global pause suppresses automatic generation/sending, not storage.
    if is_paused():
        return {**base, "action": "ignore", "reason": "bot_paused",
                "reply_blocked_by": "global_pause"}

    # 4) Only active, unpaused customers enter the automatic follow-up plan.
    ensure_followup_schedule(customer["id"])

    if not should_auto_reply(body):
        return {**base, "action": "ignore", "reason": "no_reply_needed"}

    allowed, reason = check_rate_limits(customer["id"])
    if not allowed:
        return {**base, "action": "ignore", "reason": reason}

    reply = generate_reply(customer, body)
    # Pause can be toggled while the LLM is generating; do not send then.
    if is_paused():
        return {**base, "action": "ignore", "reason": "bot_paused",
                "reply_blocked_by": "global_pause", "after_generation": True}

    # 5) The reply is only a pending outbound message at this point. The bridge
    #    sends it and posts /webhook/delivery; only that receipt may mark it sent.
    outbound_id = save_message(
        customer["id"], "outbound", reply,
        ai_generated=True,
        status="pending",
        send_kind="instant_reply",
    )
    extract_and_store_memory(customer["id"], body, reply)
    logger.info("Reply queued for %s (conversation=%s): %s", phone, outbound_id, reply[:60])
    return {
        **base,
        "action": "reply",
        "message": reply,
        "conversation_id": outbound_id,
        "inbound_conversation_id": inbound_id,
        "delay_seconds": 3,
        "delivery_status": "pending",
    }
