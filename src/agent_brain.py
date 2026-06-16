"""Central Agent Brain — autonomous decision-making for the WhatsApp sales bot.

The brain coordinates all proactive decisions:
- daily_plan(): which customers to contact today and in what order
- determine_strategy(): what message type to use for each customer
- decide_followup_cadence(): when to next contact each customer
- check_escalation_triggers(): detect hot leads that need immediate attention

All decision logic is rule-based (zero AI calls). AI is only used for
message content generation in ai_reply.py.
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Optional

from config import get_config
from database import (get_connection, get_customer_memory, get_memory_summary,
                       get_lead_score, upsert_lead_score, log_agent_decision,
                       get_segment_counts)
from scoring_engine import score_all_customers, prioritize_daily_targets
from intent_analyzer import analyze_conversation_intent, detect_stop_request

logger = logging.getLogger(__name__)

# ── Strategy definitions ─────────────────────────────────────────────────────────

STRATEGY_CADENCE = {
    "hot": (3, 5),       # 3-5 days
    "warm": (7, 10),     # 7-10 days
    "cold": (14, 21),    # 14-21 days
    "dormant": (30, 30), # monthly
    "new": (7, 7),       # standard 7-day intro
}

STRATEGY_MESSAGE_TYPE = {
    "hot": "quote_followup",     # Push toward closing
    "warm": "value_add",         # Share insights, case studies
    "cold": "re_engage",         # Fresh angle
    "dormant": "win_back",       # Low-pressure reconnection
    "new": "introduction",       # First contact
}

BUDGET_ALLOCATION = {
    "hot": 0.60,
    "warm": 0.30,
    "cold": 0.08,
    "dormant": 0.02,
}


# ── Daily Planning ───────────────────────────────────────────────────────────────

def daily_plan(available_slots: Optional[int] = None) -> dict:
    """Run the full daily planning cycle.

    1. Score all customers
    2. Prioritize today's targets
    3. Return the plan

    Called at 8:00 AM daily and on-demand.

    Returns:
        {
            "plan_date": "2026-06-16",
            "available_slots": 35,
            "segment_counts": {"hot": N, "warm": N, ...},
            "targets": [ {customer_id, name, phone, segment, score, strategy}, ... ],
            "summary": "human-readable summary"
        }
    """
    cfg = get_config()
    today = datetime.now().strftime("%Y-%m-%d")

    # Step 1: Re-score all customers
    segment_counts = score_all_customers()

    # Step 2: Determine available slots (daily limit minus already sent today)
    if available_slots is None:
        daily_limit = cfg.business.max_auto_replies_per_day
        from scheduler import _count_today_auto_sent
        already_sent = _count_today_auto_sent()
        available_slots = max(0, daily_limit - already_sent)

    if available_slots <= 0:
        logger.info(f"Daily plan: no slots available (already used all {cfg.business.max_auto_replies_per_day})")
        return {
            "plan_date": today,
            "available_slots": 0,
            "segment_counts": segment_counts,
            "targets": [],
            "summary": f"Daily limit of {cfg.business.max_auto_replies_per_day} already reached.",
        }

    # Step 3: Prioritize targets
    targets = prioritize_daily_targets(available_slots)

    # Step 4: Log decisions
    for t in targets:
        log_agent_decision(
            t["customer_id"], "followup",
            f"Priority followup: {t.get('segment', 'unknown')} (score={t.get('score', 0)}), "
            f"strategy={t.get('strategy', 'unknown')}",
            json.dumps({"segment": t.get("segment"), "score": t.get("score"),
                        "strategy": t.get("strategy")})
        )

    summary = (f"Today's plan: {len(targets)} follow-ups from {available_slots} slots. "
               f"Segments: H={segment_counts.get('hot', 0)} "
               f"W={segment_counts.get('warm', 0)} "
               f"C={segment_counts.get('cold', 0)} "
               f"D={segment_counts.get('dormant', 0)}")

    logger.info(f"Daily plan: {summary}")

    return {
        "plan_date": today,
        "available_slots": available_slots,
        "segment_counts": segment_counts,
        "targets": targets,
        "summary": summary,
    }


# ── Strategy Determination ───────────────────────────────────────────────────────

def determine_strategy(customer_id: int) -> dict:
    """Determine the best strategy for a specific customer.

    Returns:
        {
            "action": "followup" | "skip" | "escalate" | "reactivate",
            "cadence_days": int,
            "message_type": str,
            "segment": str,
            "reasoning": str,
        }
    """
    score_data = get_lead_score(customer_id)
    intent_data = analyze_conversation_intent(customer_id)

    segment = score_data["segment"] if score_data else "new"

    # Check escalation triggers
    if intent_data.get("buying_signals"):
        if "ready_to_order" in intent_data["buying_signals"]:
            return {
                "action": "escalate",
                "cadence_days": 2,
                "message_type": "quote_followup",
                "segment": segment,
                "reasoning": "Customer shows buying signals — escalate to closing sequence",
            }
        if "urgent_need" in intent_data["buying_signals"]:
            return {
                "action": "escalate",
                "cadence_days": 3,
                "message_type": "specs_solution",
                "segment": segment,
                "reasoning": "Customer has urgent need — respond with specific solution",
            }

    # Standard strategy based on segment
    cadence_min, cadence_max = STRATEGY_CADENCE.get(segment, (7, 7))
    message_type = STRATEGY_MESSAGE_TYPE.get(segment, "casual_checkin")

    return {
        "action": "followup",
        "cadence_days": cadence_min,
        "message_type": message_type,
        "segment": segment,
        "reasoning": f"Standard {segment} segment followup, cadence {cadence_min}-{cadence_max} days",
    }


def decide_followup_cadence(customer_id: int) -> int:
    """Return the recommended followup cadence in days for a customer."""
    strategy = determine_strategy(customer_id)
    return strategy["cadence_days"]


# ── Proactive Checks ─────────────────────────────────────────────────────────────

def daily_agent_workflow():
    """Run the daily morning workflow (called by scheduler at 8:00 AM).

    - Re-scores all customers
    - Updates followup cadences based on new segments
    - Detects dormant leads for reactivation
    - Logs a daily summary
    """
    logger.info("Daily agent workflow starting...")

    cfg = get_config()
    conn = get_connection()

    # Step 1: Score and segment all customers
    segment_counts = score_all_customers()

    # Step 2: Update followup cadences for customers whose segment changed
    # This ensures the follow_up_schedule reflects the agent's strategy
    all_scores = conn.execute(
        "SELECT ls.customer_id, ls.segment, fs.frequency_days, fs.id as schedule_id "
        "FROM lead_scores ls "
        "JOIN follow_up_schedule fs ON ls.customer_id = fs.customer_id "
        "WHERE fs.active = 1"
    ).fetchall()

    updated = 0
    for row in all_scores:
        expected_cadence = STRATEGY_CADENCE.get(row["segment"], (7, 7))[0]
        if row["frequency_days"] != expected_cadence:
            conn.execute(
                "UPDATE follow_up_schedule SET frequency_days = ? WHERE id = ?",
                (expected_cadence, row["schedule_id"])
            )
            updated += 1

    if updated > 0:
        conn.commit()
        logger.info(f"Updated {updated} followup cadences to match new segments")

    # Step 3: Identify dormant leads for potential reactivation
    dormant = conn.execute(
        """SELECT c.id, c.name, c.phone FROM customers c
           JOIN lead_scores ls ON c.id = ls.customer_id
           WHERE ls.segment = 'dormant' AND c.status = 'active'
           AND NOT EXISTS (
               SELECT 1 FROM follow_up_schedule fs
               WHERE fs.customer_id = c.id AND fs.active = 1
                 AND fs.next_followup_at > datetime('now')
           )
           LIMIT 5"""
    ).fetchall()

    if dormant:
        logger.info(f"Found {len(dormant)} dormant leads eligible for reactivation")

    # Step 4: Check for hot leads without recent contact
    hot_stale = conn.execute(
        """SELECT c.id, c.name, c.phone, ls.score FROM customers c
           JOIN lead_scores ls ON c.id = ls.customer_id
           LEFT JOIN follow_up_schedule fs ON c.id = fs.customer_id AND fs.active = 1
           WHERE ls.segment = 'hot' AND c.status = 'active'
           AND (fs.next_followup_at IS NULL OR fs.next_followup_at <= datetime('now', '+1 day'))
           ORDER BY ls.score DESC LIMIT 10"""
    ).fetchall()

    if hot_stale:
        names = [r["name"] for r in hot_stale]
        logger.info(f"Hot leads needing attention: {', '.join(names)}")

    # Step 5: Run daily plan
    plan = daily_plan()

    # Log summary
    log_agent_decision(0, "daily_workflow",
                       f"Morning workflow: {plan['summary']}. "
                       f"Cadences updated: {updated}. "
                       f"Dormant: {len(dormant)}. Hot-stale: {len(hot_stale)}.",
                       json.dumps(segment_counts))

    logger.info(f"Daily agent workflow complete: {plan['summary']}")
    return plan


def check_escalation_triggers(customer_id: int) -> Optional[dict]:
    """Check if a customer needs escalation and return the trigger if so.

    Returns None if no escalation needed, or a dict with escalation info.
    """
    intent = analyze_conversation_intent(customer_id)

    if not intent.get("has_recent_activity"):
        return None

    triggers = []

    # Check for stop requests
    conn = get_connection()
    last_msg = conn.execute(
        "SELECT content FROM conversations WHERE customer_id=? AND direction='inbound' "
        "ORDER BY sent_at DESC LIMIT 1", (customer_id,)
    ).fetchone()
    if last_msg and detect_stop_request(last_msg["content"]):
        triggers.append({
            "type": "stop_request",
            "action": "opt_out",
            "reasoning": "Customer requested to stop receiving messages",
        })

    # Check for buying signals
    signals = intent.get("buying_signals", [])
    if "ready_to_order" in signals:
        triggers.append({
            "type": "ready_to_order",
            "action": "escalate",
            "reasoning": "Customer is ready to order — needs immediate quote/invoice",
        })
    if "urgent_need" in signals:
        triggers.append({
            "type": "urgent_need",
            "action": "prioritize",
            "reasoning": "Customer has urgent need — prioritize response",
        })

    # Check if hot lead with no recent followup
    score = get_lead_score(customer_id)
    if score and score.get("segment") == "hot":
        last_fu = conn.execute(
            "SELECT MAX(sent_at) FROM sent_followups WHERE customer_id=? AND status='sent'",
            (customer_id,)
        ).fetchone()
        if last_fu and last_fu[0]:
            days_since = (datetime.now() - datetime.fromisoformat(last_fu[0])).days
            if days_since > 3:
                triggers.append({
                    "type": "hot_lead_stale",
                    "action": "prioritize",
                    "reasoning": f"Hot lead without followup for {days_since} days",
                })

    if not triggers:
        return None

    return {
        "customer_id": customer_id,
        "triggers": triggers,
    }
