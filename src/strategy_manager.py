"""Strategy Manager — automatic strategy adaptation based on customer behavior.

Evaluates each customer's engagement patterns and adjusts followup strategy
accordingly. All rules are SQL-based — zero AI calls.

Rules:
- 5+ outbound, 0 inbound ever → downgrade to dormant, 30-day cadence
- 3+ outbound, 0 inbound in 60 days → downgrade 1 segment, extend cadence 50%
- First inbound reply after 4+ outbounds → upgrade to warm, 5-day cadence
- Inbound message with RFQ/buying intent → upgrade to hot, 3-day cadence
- Customer says "stop" → auto-set opted_out, deactivate all followups
- Customer sent inbound but we didn't reply → flag for immediate attention
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Optional

from database import (get_connection, get_lead_score, upsert_lead_score,
                       log_agent_decision, get_customer_memory)
from intent_analyzer import detect_stop_request, analyze_conversation_intent

logger = logging.getLogger(__name__)

# ── Strategy Rules ───────────────────────────────────────────────────────────────


def evaluate_customer_strategy(customer_id: int) -> Optional[dict]:
    """Evaluate and potentially adjust strategy for a single customer.

    Returns a dict with changes made, or None if no changes were needed.
    """
    conn = get_connection()
    changes = []

    # ── Check for stop request ──
    last_inbound = conn.execute(
        "SELECT content FROM conversations WHERE customer_id=? AND direction='inbound' "
        "ORDER BY sent_at DESC LIMIT 1", (customer_id,)
    ).fetchone()

    if last_inbound and detect_stop_request(last_inbound["content"]):
        conn.execute("UPDATE customers SET status='opted_out', updated_at=? WHERE id=?",
                     (datetime.now().isoformat(), customer_id))
        conn.execute("UPDATE follow_up_schedule SET active=0 WHERE customer_id=?",
                     (customer_id,))
        conn.commit()
        log_agent_decision(customer_id, "opt_out",
                           "Customer requested to stop receiving messages — auto opted out")
        return {"customer_id": customer_id, "action": "opted_out",
                "reason": "Customer requested stop"}

    # ── Count outbound/inbound ──
    outbound_count = conn.execute(
        "SELECT COUNT(*) as cnt FROM conversations WHERE customer_id=? AND direction='outbound'",
        (customer_id,)
    ).fetchone()["cnt"]
    inbound_count = conn.execute(
        "SELECT COUNT(*) as cnt FROM conversations WHERE customer_id=? AND direction='inbound'",
        (customer_id,)
    ).fetchone()["cnt"]

    # ── Check recent activity ──
    sixty_days_ago = (datetime.now() - timedelta(days=60)).isoformat()
    recent_outbound = conn.execute(
        "SELECT COUNT(*) as cnt FROM conversations WHERE customer_id=? "
        "AND direction='outbound' AND sent_at >= ?",
        (customer_id, sixty_days_ago)
    ).fetchone()["cnt"]
    recent_inbound = conn.execute(
        "SELECT COUNT(*) as cnt FROM conversations WHERE customer_id=? "
        "AND direction='inbound' AND sent_at >= ?",
        (customer_id, sixty_days_ago)
    ).fetchone()["cnt"]

    score_data = get_lead_score(customer_id)
    current_segment = score_data["segment"] if score_data else "new"
    current_score = score_data["score"] if score_data else 0

    # ── Rule 1: 5+ outbound, 0 inbound ever → dormant ──
    if outbound_count >= 5 and inbound_count == 0:
        if current_segment != "dormant":
            conn.execute("UPDATE follow_up_schedule SET frequency_days=30, active=0 "
                         "WHERE customer_id=? AND active=1", (customer_id,))
            conn.commit()
            upsert_lead_score(customer_id, max(0, current_score - 10), "dormant",
                              score_data.get("signals", "{}") if score_data else "{}")
            changes.append(f"Downgraded to dormant: {outbound_count} outbound, 0 inbound")

    # ── Rule 2: 3+ outbound, 0 inbound in 60 days → downgrade ──
    elif recent_outbound >= 3 and recent_inbound == 0 and inbound_count == 0:
        downgrade_map = {"hot": "warm", "warm": "cold", "cold": "dormant", "new": "cold"}
        new_segment = downgrade_map.get(current_segment, "dormant")
        if new_segment != current_segment:
            upsert_lead_score(customer_id, max(0, current_score - 15), new_segment,
                              score_data.get("signals", "{}") if score_data else "{}")
            changes.append(f"Downgraded {current_segment} → {new_segment}: no replies in 60 days")

    # ── Rule 3: First inbound reply after many outbounds → upgrade ──
    if inbound_count > 0 and recent_inbound > 0 and outbound_count >= 4:
        if current_segment in ("cold", "dormant", "new"):
            if recent_inbound >= 2:
                upsert_lead_score(customer_id, min(100, current_score + 25), "warm",
                                  score_data.get("signals", "{}") if score_data else "{}")
                changes.append("Upgraded to warm: customer re-engaged after silence")

    # ── Rule 4: RFQ/buying intent → hot ──
    intent = analyze_conversation_intent(customer_id)
    if intent.get("buying_signals"):
        if "ready_to_order" in intent["buying_signals"]:
            if current_segment != "hot":
                # Add "ready_to_order" to signals
                sigs = []
                if score_data and score_data.get("signals"):
                    try:
                        sigs = json.loads(score_data["signals"]).get("active", [])
                    except (json.JSONDecodeError, KeyError):
                        pass
                if "ready_to_order" not in sigs:
                    sigs.append("ready_to_order")
                upsert_lead_score(customer_id, min(100, current_score + 30), "hot",
                                  json.dumps({"active": sigs}, ensure_ascii=False))
                conn.execute("UPDATE follow_up_schedule SET frequency_days=3 "
                             "WHERE customer_id=? AND active=1", (customer_id,))
                conn.commit()
                changes.append("Upgraded to hot: ready to order signal detected")

    # ── Rule 5: No reply needed — customer sent inbound, we didn't reply ──

    # ── Commit and log ──
    if changes:
        log_agent_decision(customer_id, "strategy_change",
                           "; ".join(changes),
                           json.dumps({"from_segment": current_segment}))
        return {"customer_id": customer_id, "changes": changes}

    return None


def evaluate_all_strategies() -> dict:
    """Run strategy evaluation on all active customers with followup schedules.

    Returns summary: {"evaluated": N, "changed": N, "details": [...]}
    """
    conn = get_connection()
    customers = conn.execute(
        "SELECT DISTINCT fs.customer_id FROM follow_up_schedule fs "
        "JOIN customers c ON fs.customer_id = c.id "
        "WHERE fs.active = 1 AND c.status = 'active'"
    ).fetchall()

    results = {"evaluated": 0, "changed": 0, "details": []}

    for c in customers:
        cid = c["customer_id"]
        try:
            result = evaluate_customer_strategy(cid)
            results["evaluated"] += 1
            if result:
                results["changed"] += 1
                results["details"].append(result)
        except Exception as e:
            logger.warning(f"Strategy evaluation failed for customer {cid}: {e}")

    logger.info(f"Strategy evaluation: {results['evaluated']} evaluated, "
                f"{results['changed']} changed")
    return results
