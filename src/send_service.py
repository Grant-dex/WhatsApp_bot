"""Single send/policy service for proactive follow-ups.

All automatic and page-triggered follow-up sends go through this module so the
scheduler and the UI cannot drift apart. Instant replies use the same delivery
status semantics but do not consume the proactive daily quota (they are
reactive, rate-limited separately in ``ai_reply.check_rate_limits``).

Rules
-----
* Global pause blocks automatic and manual follow-up sends. It is never
  overridden implicitly.
* The proactive auto-follow-up switch gates only automatic/proactive sends.
  A manual "send now" may explicitly override ``proactive_disabled``,
  ``quiet_hours`` and ``not_due``; the API response records those overrides.
* Contact status (opted_out/blocked/inactive) and inactive schedules are not
  overridable.
* One daily quota is shared by the 5-minute check, the 10:00 batch and manual
  send-now. Slots are reserved atomically before sending. Definite failures
  release the slot; unknown results keep it (they may have reached WhatsApp).
* Unknown results are never retried automatically and advance the schedule to
  prevent a blind retry on the next scheduler tick.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Optional

from bot_state import is_paused, is_proactive_followups_enabled
from bridge_client import send_message
from config import get_config
from database import (
    claim_followup_schedule,
    commit_daily_quota,
    get_connection,
    record_followup,
    release_daily_quota,
    release_followup_claim,
    reserve_daily_quota,
    save_message,
    update_followup_schedule,
    update_message_delivery,
)
from followup import generate_followup_message

logger = logging.getLogger(__name__)

OVERRIDABLE_REASONS = {"proactive_disabled", "quiet_hours", "not_due"}
NO_REPLY_STATUSES = {"opted_out", "blocked", "inactive"}

_REASON_MESSAGES = {
    "bot_paused": "机器人已暂停，主动跟进与人工批量发送均被阻止",
    "proactive_disabled": "主动自动跟进开关已关闭",
    "quiet_hours": "当前处于静默时段",
    "not_due": "该跟进计划尚未到期",
    "schedule_inactive": "该跟进计划已停用",
    "quota_exceeded": "今日主动跟进配额已用完",
    "no_phone": "客户缺少有效电话号码",
    "already_sending": "该跟进计划正在由另一个请求发送",
    "not_found": "跟进计划不存在",
    "customer_opted_out": "客户已退订",
    "customer_blocked": "客户已拉黑",
    "customer_inactive": "客户已标记为不活跃",
    "customer_status": "客户联系状态不允许主动跟进",
}


def is_quiet_hours(now: Optional[datetime] = None) -> bool:
    cfg = get_config()
    now = now or datetime.now()
    s, e = cfg.business.quiet_hours_start, cfg.business.quiet_hours_end
    hour = now.hour
    return (hour >= s or hour < e) if s > e else (s <= hour < e)


def _blocker(code: str, *, overridable: bool = False) -> dict:
    return {"code": code, "message": _REASON_MESSAGES.get(code, code),
            "overridable": overridable}


def check_proactive_eligibility(customer: dict, schedule: Optional[dict], *,
                                manual: bool = False,
                                overrides: Optional[list[str]] = None,
                                now: Optional[datetime] = None) -> dict:
    """Check all pre-send rules without mutating state.

    Returns a dict with ``allowed``, ``blockers``, ``overrides_applied`` and
    ``overridable_reasons``. Quota is reserved separately by the caller.
    """
    now = now or datetime.now()
    blockers: list[dict] = []

    if is_paused():
        blockers.append(_blocker("bot_paused"))
    if not is_proactive_followups_enabled():
        blockers.append(_blocker("proactive_disabled", overridable=manual))

    status = (customer or {}).get("status") or "active"
    if status in NO_REPLY_STATUSES:
        blockers.append(_blocker(f"customer_{status}"))
    elif status != "active":
        blockers.append(_blocker("customer_status"))

    phone = (customer or {}).get("phone") or ""
    if not phone.strip():
        blockers.append(_blocker("no_phone"))

    if schedule:
        if not schedule.get("active"):
            blockers.append(_blocker("schedule_inactive"))
        next_at = schedule.get("next_followup_at")
        if next_at:
            try:
                if datetime.fromisoformat(str(next_at)) > now:
                    blockers.append(_blocker("not_due", overridable=manual))
            except (TypeError, ValueError):
                blockers.append(_blocker("not_due", overridable=manual))
    elif manual:
        blockers.append(_blocker("not_found"))
    else:
        blockers.append(_blocker("not_found"))

    if is_quiet_hours(now):
        blockers.append(_blocker("quiet_hours", overridable=manual))

    requested = set(overrides or []) if manual else set()
    applied = sorted({b["code"] for b in blockers
                      if b["overridable"] and b["code"] in requested})
    remaining = [b for b in blockers
                 if not (b["overridable"] and b["code"] in requested)]

    return {
        "allowed": not remaining,
        "blockers": remaining,
        "overrides_applied": applied,
        "overridable_reasons": sorted({b["code"] for b in remaining if b["overridable"]}),
        "checked_at": now.isoformat(),
    }


def _fetch_schedule(schedule_id: int) -> Optional[dict]:
    conn = get_connection()
    row = conn.execute(
        "SELECT fs.*, c.name, c.phone, c.company, c.notes, c.tags, "
        "c.status AS customer_status, "
        "COALESCE(ls.score, 0) AS score, COALESCE(ls.segment, 'new') AS segment, "
        "COALESCE(ls.signals, '{}') AS signals "
        "FROM follow_up_schedule fs JOIN customers c ON fs.customer_id=c.id "
        "LEFT JOIN lead_scores ls ON fs.customer_id=ls.customer_id "
        "WHERE fs.id=?",
        (schedule_id,),
    ).fetchone()
    if not row:
        return None
    data = dict(row)
    # The joined customer status lives under customer_status; build the customer
    # shape expected by generators and checkers.
    data["customer"] = {
        "id": data["customer_id"],
        "name": data.get("name"),
        "phone": data.get("phone"),
        "company": data.get("company"),
        "notes": data.get("notes"),
        "tags": data.get("tags"),
        "status": data.get("customer_status"),
        "template": data.get("template"),
    }
    data["status"] = data.get("customer_status", "active")
    try:
        from scoring_engine import _pick_strategy_for_segment
        data["strategy"] = _pick_strategy_for_segment(
            data.get("segment", "new"), data.get("signals", "{}")
        )
    except Exception:
        data["strategy"] = "casual_checkin"
    return data


def _strategy_context(target: dict) -> dict:
    from country_utils import get_country_from_phone
    from database import get_memory_summary

    phone = target.get("phone", "")
    country_name = ""
    try:
        country_name = get_country_from_phone(phone).get("country_name", "")
    except Exception:
        pass

    has_recent = False
    try:
        conn = get_connection()
        last_msg = conn.execute(
            "SELECT MAX(sent_at) FROM conversations WHERE customer_id=? "
            "AND status IN ('received','sent')",
            (target["customer_id"],),
        ).fetchone()
        if last_msg and last_msg[0]:
            has_recent = (datetime.now() - datetime.fromisoformat(last_msg[0])).days <= 14
    except Exception:
        pass

    return {
        "message_type": target.get("strategy", "casual_checkin"),
        "segment": target.get("segment", "new"),
        "memory_summary": get_memory_summary(target["customer_id"]),
        "country": country_name,
        "has_recent_activity": has_recent,
    }


def _message_for_target(target: dict, strategy: Optional[str] = None) -> str:
    if strategy:
        target = {**target, "strategy": strategy}
    return generate_followup_message(
        target["customer"], strategy_context=_strategy_context(target)
    )


def _normalize_bridge_result(result: dict) -> dict:
    result = result or {}
    status = result.get("status")
    if status not in ("sent", "failed", "unknown"):
        status = "unknown"
    return {
        "status": status,
        "message_id": result.get("message_id") or result.get("whatsapp_msg_id"),
        "error": result.get("error"),
        "error_code": result.get("error_code"),
    }


def _recheck_blocked(schedule_id: int, manual: bool,
                     overrides: Optional[list[str]]) -> Optional[dict]:
    fresh = _fetch_schedule(schedule_id)
    if not fresh:
        return {"allowed": False, "blockers": [_blocker("not_found")],
                "overrides_applied": [], "overridable_reasons": []}
    decision = check_proactive_eligibility(
        fresh["customer"], fresh, manual=manual, overrides=overrides
    )
    return None if decision["allowed"] else decision


async def send_followup_now(schedule_id: int, *, manual: bool = False,
                            overrides: Optional[list[str]] = None) -> dict:
    """Send one schedule through the unified proactive path."""
    target = _fetch_schedule(schedule_id)
    if not target:
        return {"ok": False, "status": "not_found", "reason": "not_found",
                "error": _REASON_MESSAGES["not_found"]}

    decision = check_proactive_eligibility(
        target["customer"], target, manual=manual, overrides=overrides
    )
    if not decision["allowed"]:
        first = decision["blockers"][0]
        return {
            "ok": False, "status": "blocked", "reason": first["code"],
            "error": first["message"], "blockers": decision["blockers"],
            "overridable_reasons": decision["overridable_reasons"],
            "overrides_applied": decision["overrides_applied"],
        }

    cfg = get_config()
    daily_limit = cfg.business.max_auto_replies_per_day
    # Pin the quota day so a send that crosses midnight releases/commits the
    # reservation it actually made.
    quota_day = datetime.now().strftime("%Y-%m-%d")
    if not reserve_daily_quota(daily_limit, day=quota_day):
        return {
            "ok": False, "status": "blocked", "reason": "quota_exceeded",
            "error": _REASON_MESSAGES["quota_exceeded"], "blockers": [_blocker("quota_exceeded")],
            "overridable_reasons": [], "overrides_applied": decision["overrides_applied"],
            "daily_limit": daily_limit,
        }

    # Claim the schedule atomically so a manual send-now and an automatic tick
    # cannot send the same follow-up concurrently.
    try:
        claimed = claim_followup_schedule(schedule_id)
    except Exception as e:
        release_daily_quota(day=quota_day)
        logger.error("Could not claim schedule %s: %s", schedule_id, e, exc_info=True)
        return {"ok": False, "status": "failed", "error": str(e)}
    if not claimed:
        release_daily_quota(day=quota_day)
        return {
            "ok": False, "status": "blocked", "reason": "already_sending",
            "error": _REASON_MESSAGES["already_sending"],
            "blockers": [_blocker("already_sending")],
            "overridable_reasons": [], "overrides_applied": decision["overrides_applied"],
        }

    conversation_id = None
    bridge = None
    quota_finalized = False
    try:
        message = _message_for_target(target, target.get("strategy"))

        # Pause/switch/status can change while the LLM is generating. Re-check
        # immediately before touching the bridge.
        blocked = _recheck_blocked(schedule_id, manual, overrides)
        if blocked:
            release_daily_quota(day=quota_day)
            quota_finalized = True
            first = blocked["blockers"][0]
            return {
                "ok": False, "status": "blocked", "reason": first["code"],
                "error": first["message"], "blockers": blocked["blockers"],
                "overridable_reasons": blocked["overridable_reasons"],
                "overrides_applied": blocked["overrides_applied"],
                "after_generation": True,
            }

        # Use the freshest row for phone/customer after the LLM call.
        target = _fetch_schedule(schedule_id) or target

        conversation_id = save_message(
            target["customer_id"], "outbound", message,
            ai_generated=True, status="pending", send_kind="proactive",
        )
        bridge = _normalize_bridge_result(await send_message(target["phone"], message))
        update_message_delivery(
            conversation_id, bridge["status"],
            whatsapp_msg_id=bridge["message_id"], error_message=bridge["error"],
        )

        if bridge["status"] == "sent":
            commit_daily_quota(day=quota_day)
            quota_finalized = True
            # Advance the schedule before the audit row so a bookkeeping failure
            # cannot cause an automatic duplicate retry on the next tick.
            update_followup_schedule(schedule_id)
            record_followup(target["customer_id"], schedule_id, conversation_id, status="sent")
            return {
                "ok": True, "status": "sent", "conversation_id": conversation_id,
                "message_id": bridge["message_id"], "message": message,
                "overrides_applied": decision["overrides_applied"],
            }

        if bridge["status"] == "unknown":
            # Keep the quota slot: the message may have reached WhatsApp. Advance
            # the schedule so the next automatic tick does not retry blindly.
            commit_daily_quota(day=quota_day)
            quota_finalized = True
            update_followup_schedule(schedule_id)
            record_followup(target["customer_id"], schedule_id, conversation_id,
                            status="unknown", error_message=bridge["error"] or "unknown result")
            logger.warning("Follow-up result unknown for schedule %s; no automatic retry", schedule_id)
            return {
                "ok": False, "status": "unknown", "conversation_id": conversation_id,
                "error": bridge["error"] or "结果待确认", "message": message,
                "overrides_applied": decision["overrides_applied"],
            }

        release_daily_quota(day=quota_day)
        quota_finalized = True
        record_followup(target["customer_id"], schedule_id, conversation_id,
                        status="failed", error_message=bridge["error"] or "send failed")
        return {
            "ok": False, "status": "failed", "conversation_id": conversation_id,
            "error": bridge["error"] or "send failed", "message": message,
            "overrides_applied": decision["overrides_applied"],
        }
    except Exception as e:
        if not quota_finalized:
            # If the bridge had already reported sent/unknown, the message may
            # have reached the customer. Keep the quota slot rather than
            # releasing it and risking a duplicate on the next tick.
            if bridge and bridge.get("status") in ("sent", "unknown"):
                commit_daily_quota(day=quota_day)
            else:
                release_daily_quota(day=quota_day)
        if conversation_id:
            try:
                if bridge and bridge.get("status") in ("sent", "unknown"):
                    update_message_delivery(
                        conversation_id, bridge["status"],
                        whatsapp_msg_id=bridge.get("message_id"),
                        error_message=bridge.get("error"),
                    )
                else:
                    update_message_delivery(conversation_id, "failed", error_message=str(e))
            except Exception:
                logger.error("Could not update conversation %s after error", conversation_id)
        logger.error("Follow-up send/record failed for schedule %s: %s", schedule_id, e, exc_info=True)
        if bridge and bridge.get("status") == "sent":
            # The platform accepted the message; do not report a failed send just
            # because local bookkeeping failed.
            return {"ok": True, "status": "sent",
                    "conversation_id": conversation_id,
                    "message_id": bridge.get("message_id"),
                    "bookkeeping_error": str(e)}
        if bridge and bridge.get("status") == "unknown":
            return {"ok": False, "status": "unknown",
                    "conversation_id": conversation_id,
                    "error": str(e), "bookkeeping_error": str(e)}
        return {"ok": False, "status": "failed", "error": str(e),
                "conversation_id": conversation_id}
    finally:
        try:
            release_followup_claim(schedule_id)
        except Exception:
            logger.error("Could not release send claim for schedule %s", schedule_id)


async def send_manual_message(customer_id: Optional[int], phone: str, message: str) -> dict:
    """Human-initiated chat message.

    This is not a proactive follow-up: it is not gated by the proactive switch,
    quiet hours or the proactive daily quota. It still records the same delivery
    states and never claims success before the bridge confirms.
    """
    conversation_id = None
    if customer_id:
        conversation_id = save_message(
            customer_id, "outbound", message, ai_generated=False,
            status="pending", send_kind="manual",
        )
    bridge = _normalize_bridge_result(await send_message(phone, message))
    if conversation_id:
        update_message_delivery(
            conversation_id, bridge["status"],
            whatsapp_msg_id=bridge["message_id"], error_message=bridge["error"],
        )
    return {
        "ok": bridge["status"] == "sent",
        "status": bridge["status"],
        "conversation_id": conversation_id,
        "message_id": bridge["message_id"],
        "error": bridge["error"],
    }


def apply_delivery_receipt(conversation_id: Optional[int], status: str,
                           whatsapp_msg_id: Optional[str] = None,
                           error: Optional[str] = None,
                           whatsapp_msg_id_lookup: Optional[str] = None) -> dict:
    """Apply a bridge callback idempotently.

    Receipts normally identify the local conversation. As a compatibility path,
    a receipt may instead carry only the platform id; we then look up the local
    row. Repeated receipts are no-ops and never create new rows.
    """
    from database import get_message_by_whatsapp_id

    if conversation_id is None and whatsapp_msg_id_lookup:
        found = get_message_by_whatsapp_id(whatsapp_msg_id_lookup)
        if found:
            conversation_id = found["id"]
    if conversation_id is None:
        return {"ok": False, "error": "conversation_id or known whatsapp_msg_id required",
                "changed": False}
    return update_message_delivery(
        conversation_id, status, whatsapp_msg_id=whatsapp_msg_id,
        error_message=error,
    )
