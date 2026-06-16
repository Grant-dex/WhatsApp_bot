"""Lead scoring and customer segmentation engine.

All scoring is done via SQL queries — zero AI calls, zero token cost.
Scoring factors: recency, engagement depth, reply rate, buying signals,
followup responsiveness, order history.
"""

import json
import logging
from datetime import datetime, timedelta
from typing import Optional

from database import (get_connection, get_all_lead_scores, get_segment_counts,
                       log_agent_decision)

logger = logging.getLogger(__name__)

# ── Scoring Constants ───────────────────────────────────────────────────────────

MAX_RECENCY_PTS = 20
MAX_DEPTH_PTS = 20
MAX_REPLY_RATE_PTS = 20
MAX_SIGNALS_PTS = 25
MAX_FOLLOWUP_RESPONSE_PTS = 10
ORDER_BONUS_PTS = 5
INACTIVITY_PENALTY_PER_DAY = 2
INACTIVITY_THRESHOLD_DAYS = 14

SEGMENT_THRESHOLDS = {
    "hot": 70,
    "warm": 40,
    "cold": 10,
    # < 10 → dormant
    # no score yet → new
}


# ── Core Scoring ────────────────────────────────────────────────────────────────

def score_customer(customer_id: int) -> dict:
    """Calculate a 0-100 lead score for a single customer.

    Returns:
        {
            "customer_id": int, "score": int, "segment": str,
            "breakdown": { "recency": int, "depth": int, "reply_rate": int,
                          "signals": int, "followup_response": int, "order_bonus": int,
                          "inactivity_penalty": int },
            "signals": list[str]  # active buying signals
        }
    """
    conn = get_connection()
    now = datetime.now()

    # ── Recency: when was the last INBOUND message? ──
    last_inbound = conn.execute(
        "SELECT sent_at FROM conversations "
        "WHERE customer_id=? AND direction='inbound' ORDER BY sent_at DESC LIMIT 1",
        (customer_id,)
    ).fetchone()

    recency_pts = 0
    if last_inbound:
        last_dt = datetime.fromisoformat(last_inbound["sent_at"])
        days_ago = (now - last_dt).days
        if days_ago <= 1:
            recency_pts = 20
        elif days_ago <= 3:
            recency_pts = 15
        elif days_ago <= 7:
            recency_pts = 10
        elif days_ago <= 30:
            recency_pts = 5

    # ── Engagement depth: total conversation turns ──
    total_conv = conn.execute(
        "SELECT COUNT(*) as cnt FROM conversations WHERE customer_id=?",
        (customer_id,)
    ).fetchone()["cnt"]
    depth_pts = min(total_conv // 2, MAX_DEPTH_PTS)

    # ── Reply rate: inbound replies / outbound messages ──
    outbound_cnt = conn.execute(
        "SELECT COUNT(*) as cnt FROM conversations "
        "WHERE customer_id=? AND direction='outbound'",
        (customer_id,)
    ).fetchone()["cnt"]
    inbound_cnt = conn.execute(
        "SELECT COUNT(*) as cnt FROM conversations "
        "WHERE customer_id=? AND direction='inbound'",
        (customer_id,)
    ).fetchone()["cnt"]
    if outbound_cnt > 0:
        reply_rate = inbound_cnt / outbound_cnt
    else:
        reply_rate = 0
    reply_rate_pts = min(int(reply_rate * MAX_REPLY_RATE_PTS), MAX_REPLY_RATE_PTS)

    # ── Buying signals: from existing lead_scores.signals or conversation analysis ──
    signals_pts = 0
    active_signals = []
    existing_score = conn.execute(
        "SELECT signals FROM lead_scores WHERE customer_id=?", (customer_id,)
    ).fetchone()
    if existing_score:
        try:
            sig_data = json.loads(existing_score["signals"])
            active_signals = sig_data.get("active", [])
            # Each buying signal is worth ~5 points, capped at 25
            signals_pts = min(len(active_signals) * 5, MAX_SIGNALS_PTS)
        except (json.JSONDecodeError, KeyError):
            pass

    # ── Followup responsiveness ──
    fu_sent = conn.execute(
        "SELECT COUNT(*) as cnt FROM sent_followups WHERE customer_id=? AND status='sent'",
        (customer_id,)
    ).fetchone()["cnt"]
    fu_replied = conn.execute(
        """SELECT COUNT(DISTINCT sf.id) as cnt FROM sent_followups sf
           JOIN conversations conv ON sf.conversation_id = conv.id
           WHERE sf.customer_id=? AND sf.status='sent'
           AND EXISTS (
               SELECT 1 FROM conversations c2
               WHERE c2.customer_id=sf.customer_id
               AND c2.direction='inbound'
               AND c2.sent_at > conv.sent_at
               AND c2.sent_at < datetime(conv.sent_at, '+7 days')
           )""",
        (customer_id,)
    ).fetchone()["cnt"]
    if fu_sent > 0:
        fu_response_pts = min(int((fu_replied / fu_sent) * MAX_FOLLOWUP_RESPONSE_PTS),
                              MAX_FOLLOWUP_RESPONSE_PTS)
    else:
        fu_response_pts = 0

    # ── Order bonus ──
    has_orders = conn.execute(
        "SELECT COUNT(*) as cnt FROM orders WHERE customer_id=?", (customer_id,)
    ).fetchone()["cnt"]
    order_bonus = ORDER_BONUS_PTS if has_orders > 0 else 0

    # ── Inactivity penalty ──
    last_contact = conn.execute(
        "SELECT MAX(sent_at) as last_ts FROM conversations WHERE customer_id=?",
        (customer_id,)
    ).fetchone()["last_ts"]
    inactivity_penalty = 0
    if last_contact:
        last_dt = datetime.fromisoformat(last_contact)
        days_silent = (now - last_dt).days
        if days_silent > INACTIVITY_THRESHOLD_DAYS:
            inactivity_penalty = (days_silent - INACTIVITY_THRESHOLD_DAYS) * INACTIVITY_PENALTY_PER_DAY

    # ── Total ──
    total = (recency_pts + depth_pts + reply_rate_pts + signals_pts +
             fu_response_pts + order_bonus - inactivity_penalty)
    total = max(0, min(total, 100))

    # ── Segment ──
    segment = _score_to_segment(total)

    return {
        "customer_id": customer_id,
        "score": total,
        "segment": segment,
        "breakdown": {
            "recency": recency_pts,
            "depth": depth_pts,
            "reply_rate": reply_rate_pts,
            "signals": signals_pts,
            "followup_response": fu_response_pts,
            "order_bonus": order_bonus,
            "inactivity_penalty": inactivity_penalty,
        },
        "signals": active_signals,
    }


def _score_to_segment(score: int) -> str:
    if score >= SEGMENT_THRESHOLDS["hot"]:
        return "hot"
    elif score >= SEGMENT_THRESHOLDS["warm"]:
        return "warm"
    elif score >= SEGMENT_THRESHOLDS["cold"]:
        return "cold"
    else:
        return "dormant"


# ── Batch Operations ────────────────────────────────────────────────────────────

def score_all_customers() -> dict:
    """Re-score all active customers and update lead_scores table.

    Returns summary: {"hot": N, "warm": N, "cold": N, "dormant": N, "new": N, "total": N}
    """
    from database import upsert_lead_score

    conn = get_connection()
    customers = conn.execute(
        "SELECT id FROM customers WHERE status='active'"
    ).fetchall()

    results = {"hot": 0, "warm": 0, "cold": 0, "dormant": 0, "new": 0, "total": 0}

    for c in customers:
        cid = c["id"]
        try:
            result = score_customer(cid)
            signals_json = json.dumps({"active": result["signals"]}, ensure_ascii=False)
            upsert_lead_score(cid, result["score"], result["segment"], signals_json)
            results[result["segment"]] += 1
            results["total"] += 1
        except Exception as e:
            logger.warning(f"Failed to score customer {cid}: {e}")

    logger.info(f"Scored {results['total']} customers: "
                f"hot={results['hot']}, warm={results['warm']}, "
                f"cold={results['cold']}, dormant={results['dormant']}")

    log_agent_decision(0, "batch_score",
                       f"Scored {results['total']} customers: "
                       f"H={results['hot']} W={results['warm']} "
                       f"C={results['cold']} D={results['dormant']}",
                       json.dumps(results))

    return results


# ── Prioritization ──────────────────────────────────────────────────────────────

def prioritize_daily_targets(available_slots: int) -> list[dict]:
    """Return the prioritized list of customers to contact today.

    Priority order: hot > warm > cold > dormant
    Budget allocation (from remaining slots):
      - Hot: 60%
      - Warm: 30%
      - Cold: 10%
      - Dormant: only if budget allows and they haven't been contacted in 30+ days

    Returns list of dicts with: customer_id, name, phone, segment, score, strategy
    """
    conn = get_connection()
    now_iso = datetime.now().isoformat()

    # Get all due followup customers with their scores
    due = conn.execute(
        """SELECT fs.id as schedule_id, fs.customer_id, fs.frequency_days,
                  fs.next_followup_at, fs.template,
                  c.name, c.phone, c.company,
                  COALESCE(ls.score, 0) as score,
                  COALESCE(ls.segment, 'new') as segment,
                  COALESCE(ls.signals, '{}') as signals
           FROM follow_up_schedule fs
           JOIN customers c ON fs.customer_id = c.id
           LEFT JOIN lead_scores ls ON fs.customer_id = ls.customer_id
           WHERE fs.active = 1 AND c.status = 'active'
             AND fs.next_followup_at <= ?
           ORDER BY COALESCE(ls.score, 0) DESC""",
        (now_iso,)
    ).fetchall()

    if not due:
        return []

    due_list = [dict(r) for r in due]

    # Budget allocation
    hot_slots = max(1, int(available_slots * 0.60))
    warm_slots = max(1, int(available_slots * 0.30))
    cold_slots = max(1, int(available_slots * 0.10))

    # Separate by segment
    buckets = {"hot": [], "warm": [], "cold": [], "dormant": [], "new": []}
    for c in due_list:
        seg = c.get("segment", "new")
        buckets.setdefault(seg, []).append(c)

    # Build prioritized list
    targets = []
    allocations = {"hot": hot_slots, "warm": warm_slots, "cold": cold_slots,
                   "dormant": 0, "new": min(5, available_slots // 4)}

    # Redistribute unused slots
    for seg in ["hot", "warm", "cold", "new"]:
        taken = min(len(buckets.get(seg, [])), allocations.get(seg, 0))
        unused = allocations.get(seg, 0) - taken
        if unused > 0:
            # Give unused slots to the next priority level
            if seg == "hot":
                allocations["warm"] = allocations.get("warm", 0) + unused
            elif seg == "warm":
                allocations["cold"] = allocations.get("cold", 0) + unused
            elif seg == "cold":
                allocations["dormant"] = allocations.get("dormant", 0) + unused

    # Assemble final list in priority order
    priority_order = ["hot", "warm", "new", "cold", "dormant"]
    for seg in priority_order:
        bucket = buckets.get(seg, [])
        limit = allocations.get(seg, 0)
        for c in bucket[:limit]:
            c["strategy"] = _pick_strategy_for_segment(seg, c.get("signals", "{}"))
            targets.append(c)

    return targets[:available_slots]


def _pick_strategy_for_segment(segment: str, signals_json: str) -> str:
    """Pick the best message strategy based on segment and buying signals."""
    try:
        signals = json.loads(signals_json).get("active", [])
    except (json.JSONDecodeError, KeyError):
        signals = []

    strategy_map = {
        "hot": "quote_followup" if any(s in signals for s in
            ["asked_about_price", "ready_to_order", "asked_about_delivery"])
            else "specs_solution",
        "warm": "value_add",
        "cold": "re_engage",
        "dormant": "win_back",
        "new": "introduction",
    }
    return strategy_map.get(segment, "casual_checkin")
