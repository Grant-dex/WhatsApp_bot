"""Sub-agent message reviewer — the "checker" in the maker/checker pattern.

A separate AI call with a CLEAN context reviews every followup message before
it's sent. The reviewer doesn't see the original prompt that generated the
message — it only sees the output + customer context. This eliminates the
"grading your own homework" bias.

If the message fails review, it's sent back for regeneration with specific
feedback. Max 2 retries before falling back to a safe default.
"""

import json
import logging
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)

# ── Review prompt — deliberately does NOT see the original generation prompt ──

REVIEW_PROMPT = """You are a quality reviewer for WhatsApp business messages.
You receive a message that another AI wrote, and your job is to judge it.

Evaluate the message against these criteria. For each, answer YES or NO:

1. HUMAN: Does it sound like a real person typing on WhatsApp? (no markdown, no formal letter tone, no "Dear Sir/Madam", no bullet points)
2. NATURAL_LANG: Is the language natural and fluent? (no weird grammar, no mixed languages, no awkward phrasing)
3. APPROPRIATE: Is it appropriate for a {message_type} message?
   - quote_followup: gently moving toward a decision, not pushy
   - casual_checkin: light and friendly, not salesy
   - re_engage: fresh angle, not repeating old approaches
   - win_back: very low pressure, not desperate
   - value_add: sharing insight, not hard selling
   - introduction: warm first impression, not overwhelming
4. PERSONAL: Does it use the customer's actual name naturally? (no [Name] placeholders, no wrong names)
5. CONCISE: Is it short enough for WhatsApp? (1-3 sentences, not a wall of text)
6. SAFE: Is it free of red flags? (no false claims, no made-up prices, no promises about delivery/warranty without qualification, no spammy urgency like "limited time offer")

Return a JSON object ONLY, no other text:
{{
  "pass": true or false,
  "scores": {{"human": "YES/NO", "natural_lang": "YES/NO", "appropriate": "YES/NO", "personal": "YES/NO", "concise": "YES/NO", "safe": "YES/NO"}},
  "fail_reason": "if pass=false, explain the ONE biggest problem briefly",
  "fix_suggestion": "if pass=false, give a SHORT concrete suggestion for fixing it"
}}

Message to review:
---
{message}
---

Customer context:
- Name: {customer_name}
- Company: {customer_company}
- Country: {country}
- Recent interaction: {has_recent_activity}
"""

# ── Minimum bar for passing ──

MINIMUM_PASS_SCORE = 4  # At least 4 out of 6 criteria must be YES


def review_message(message: str, customer: dict, message_type: str,
                   country: str = "", has_recent_activity: bool = False) -> dict:
    """Review a followup message before sending.

    Returns:
        {
            "pass": True/False,
            "scores": {"human": "YES/NO", ...},
            "fail_reason": str or "",
            "fix_suggestion": str or "",
        }
    """
    if not message or len(message.strip()) < 5:
        return {
            "pass": False,
            "scores": {},
            "fail_reason": "Message too short or empty",
            "fix_suggestion": "Generate a complete, natural message of 1-3 sentences",
        }

    try:
        from ai_reply import _get_client
        from config import get_config

        cfg = get_config()
        client = _get_client()

        review_prompt = REVIEW_PROMPT.format(
            message_type=message_type,
            message=message,
            customer_name=customer.get("name", "Valued Customer"),
            customer_company=customer.get("company", "N/A"),
            country=country or "Unknown",
            has_recent_activity="Yes" if has_recent_activity else "No (dormant or new customer)",
        )

        resp = client.chat.completions.create(
            model=cfg.ai.model,
            max_tokens=200,
            temperature=0.1,  # Low temp for consistent judgment
            messages=[{"role": "user", "content": review_prompt}],
        )

        content = resp.choices[0].message.content.strip()

        # Parse JSON from response
        if content.startswith("```"):
            lines = content.split("\n")
            content = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

        result = json.loads(content)

        # Count passing criteria
        scores = result.get("scores", {})
        pass_count = sum(1 for v in scores.values() if v == "YES")

        # Override: reviewer's judgment + minimum threshold
        reviewer_says_pass = result.get("pass", False)
        meets_threshold = pass_count >= MINIMUM_PASS_SCORE

        result["pass"] = reviewer_says_pass and meets_threshold
        result["pass_count"] = pass_count

        return result

    except (json.JSONDecodeError, Exception) as e:
        logger.warning(f"Message review failed (will pass through): {e}")
        # If the reviewer itself fails, don't block the message
        return {
            "pass": True,
            "scores": {},
            "pass_count": 6,
            "fail_reason": "",
            "fix_suggestion": "",
            "reviewer_error": str(e),
        }


def review_and_refine(message: str, customer: dict, message_type: str,
                       country: str = "", memory_summary: str = "",
                       max_retries: int = 2) -> str:
    """Review a message and regenerate if it fails.

    This is the main entry point. It:
    1. Reviews the message
    2. If it fails, sends feedback back to the generator to try again
    3. If it still fails after max_retries, returns the original

    Returns the final (possibly regenerated) message.
    """
    if not message:
        return message

    has_recent = True  # Will be checked in first review

    for attempt in range(max_retries):
        result = review_message(message, customer, message_type, country, has_recent)

        if result.get("pass"):
            if attempt > 0:
                logger.info(f"Message passed review after {attempt} retries")
            return message

        # Failed — log and retry with feedback
        fail_reason = result.get("fail_reason", "Unknown")
        fix_suggestion = result.get("fix_suggestion", "")

        logger.warning(
            f"Message review failed (attempt {attempt + 1}/{max_retries}): "
            f"{fail_reason} | Fix: {fix_suggestion}"
        )

        # Regenerate with feedback
        message = _regenerate_with_feedback(
            customer, message_type, message, fail_reason, fix_suggestion,
            memory_summary
        )

    # All retries exhausted — log and return the last attempt
    logger.warning(f"Message failed review after {max_retries} retries, using last attempt")
    return message


def _regenerate_with_feedback(customer: dict, message_type: str,
                                failed_message: str, fail_reason: str,
                                fix_suggestion: str,
                                memory_summary: str = "") -> str:
    """Regenerate a message with specific feedback from the reviewer."""
    from ai_reply import generate_strategic_message

    # Create a modified memory summary that includes the feedback
    feedback_memory = (
        f"Previous attempt was rejected because: {fail_reason}\n"
        f"Fix: {fix_suggestion}\n"
    )
    if memory_summary:
        feedback_memory += f"\nOriginal context: {memory_summary}"

    return generate_strategic_message(customer, message_type, feedback_memory)
