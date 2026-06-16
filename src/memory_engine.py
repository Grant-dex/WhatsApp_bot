"""AI-driven memory extraction engine.

Replaces the keyword-based `summarize_and_remember()` in ai_reply.py.
Uses DeepSeek to extract structured sales intelligence from conversations,
then stores it in the `ai_memory_entries` table.

Cost: ~300 tokens per extraction (~$0.00007). Only triggered on actual
inbound messages that receive an AI reply (max ~20/day).
"""

import json
import logging
from datetime import datetime
from typing import Optional

from database import (add_memory_entry, get_customer_memory, get_memory_summary,
                       upsert_lead_score, get_lead_score)

logger = logging.getLogger(__name__)

EXTRACTION_PROMPT = """You are a data extraction tool. Given a customer message and the bot's reply, extract structured sales intelligence.

Return ONLY valid JSON, no other text. Use this exact schema:
{
  "intents": ["rfq", "pricing", "technical", "complaint", "general"],
  "product_interests": ["product names mentioned"],
  "key_facts": ["fact 1", "fact 2"],
  "objections": ["objection 1"],
  "buying_signals": ["asked_about_price", "asked_about_delivery", "asked_about_warranty", "asked_for_quote", "asked_for_specs", "urgent_need", "ready_to_order"],
  "engagement_level": 3,
  "should_remember": ["important thing to remember for future conversations"],
  "summary": "one-sentence summary of the exchange"
}

Rules:
- engagement_level: 1=cold/annoyed, 3=neutral, 5=hot/ready to buy
- Only include fields that have data (empty arrays = omit or [])
- key_facts: anything useful for future conversations (name, location, company, project, timeline, budget, power requirement)
- should_remember: the 1-2 most important things to remember about this customer
- Summary should be concise and in the same language as the customer message

Customer message:
{customer_msg}

Bot reply:
{bot_reply}

JSON:"""


def extract_and_store_memory(customer_id: int, incoming_message: str,
                              bot_reply: str) -> Optional[dict]:
    """Extract structured memory from a conversation exchange and store it.

    Called after every AI reply to an inbound message.
    Falls back to keyword-based extraction if AI call fails.
    """
    if not incoming_message or not bot_reply:
        return None

    try:
        extraction = _call_ai_extraction(incoming_message, bot_reply)
        if extraction:
            _store_extraction(customer_id, extraction)
            _update_signals(customer_id, extraction)
            return extraction
    except Exception as e:
        logger.warning(f"AI memory extraction failed for customer {customer_id}: {e}")

    # Fallback: keyword-based extraction (simplified version of old summarize_and_remember)
    try:
        from ai_reply import summarize_and_remember
        summarize_and_remember(customer_id, incoming_message, bot_reply)
    except Exception:
        pass

    return None


def _call_ai_extraction(customer_msg: str, bot_reply: str) -> Optional[dict]:
    """Call DeepSeek to extract structured memory from an exchange."""
    from ai_reply import _get_client
    from config import get_config

    cfg = get_config()

    prompt = EXTRACTION_PROMPT.format(
        customer_msg=customer_msg[:500],
        bot_reply=bot_reply[:500],
    )

    try:
        client = _get_client()
        resp = client.chat.completions.create(
            model=cfg.ai.model,
            max_tokens=300,
            temperature=0.1,  # Low temperature for structured extraction
            messages=[{"role": "user", "content": prompt}],
        )
        content = resp.choices[0].message.content

        # Extract JSON from response
        content = content.strip()
        # Handle cases where AI wraps JSON in markdown code blocks
        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

        return json.loads(content)
    except (json.JSONDecodeError, Exception) as e:
        logger.warning(f"AI extraction parse error: {e}")
        return None


def _store_extraction(customer_id: int, extraction: dict):
    """Store extracted facts as ai_memory_entries."""
    now = datetime.now().isoformat()

    # Store summary
    summary = extraction.get("summary", "")
    if summary:
        add_memory_entry(customer_id, "summary", summary, importance=3)

    # Store intents
    for intent in extraction.get("intents", []):
        add_memory_entry(customer_id, "intent", f"Showed intent: {intent}", importance=3)

    # Store key facts (name, company, requirements, etc.)
    for fact in extraction.get("key_facts", []):
        add_memory_entry(customer_id, "summary", fact, importance=4)

    # Store objections
    for obj in extraction.get("objections", []):
        add_memory_entry(customer_id, "objection", obj, importance=5)

    # Store product interests
    for prod in extraction.get("product_interests", []):
        add_memory_entry(customer_id, "preference", f"Interested in: {prod}", importance=4)

    # Store things to remember
    for item in extraction.get("should_remember", []):
        add_memory_entry(customer_id, "summary", item, importance=5)

    logger.debug(f"Stored {len(extraction.get('key_facts', []))} facts, "
                 f"{len(extraction.get('intents', []))} intents "
                 f"for customer {customer_id}")


def _update_signals(customer_id: int, extraction: dict):
    """Update lead_scores.signals with detected buying signals."""
    signals = extraction.get("buying_signals", [])
    engagement = extraction.get("engagement_level", 3)

    if not signals and engagement == 3:
        return  # Nothing meaningful to update

    existing = get_lead_score(customer_id)
    all_signals = signals[:]
    if existing and existing.get("signals"):
        try:
            old_signals = json.loads(existing["signals"]).get("active", [])
            for s in old_signals:
                if s not in all_signals:
                    all_signals.append(s)
        except (json.JSONDecodeError, KeyError):
            pass

    from database import upsert_lead_score

    # If lead score doesn't exist yet, create with defaults
    if not existing:
        score = engagement * 15  # Rough initial score: 15-75 based on engagement
        segment = "warm" if engagement >= 4 else "cold" if engagement >= 2 else "new"
        upsert_lead_score(customer_id, score, segment,
                          json.dumps({"active": all_signals}, ensure_ascii=False))
    else:
        # Update signals without changing score (scoring engine will recalculate)
        upsert_lead_score(customer_id, existing.get("score", 0),
                          existing.get("segment", "new"),
                          json.dumps({"active": all_signals}, ensure_ascii=False))
