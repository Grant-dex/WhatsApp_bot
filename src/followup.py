import logging
import random
from typing import Optional

from ai_reply import generate_followup, generate_strategic_message
from message_reviewer import review_and_refine

logger = logging.getLogger(__name__)


def generate_followup_message(customer: dict,
                               strategy_context: Optional[dict] = None) -> str:
    """Generate a followup message, optionally using agent strategy context.

    Args:
        customer: Customer dict with name, phone, company, notes, etc.
        strategy_context: Optional dict from agent_brain with:
            - message_type: 'quote_followup', 'specs_solution', 'casual_checkin',
                           'value_add', 're_engage', 'win_back', 'introduction',
                           'reactivation'
            - segment: 'hot', 'warm', 'cold', 'dormant', 'new'
            - memory_summary: pre-fetched memory string for prompt injection
            - country: customer's country for context
            - has_recent_activity: whether customer has been active recently

    If strategy_context is provided, uses the AI strategy-aware message generator.
    Then runs through the checker sub-agent (maker/checker pattern).
    Otherwise falls back to the standard followup generation.
    """
    template = customer.get("template")
    name = customer.get("name", "")

    if template:
        try:
            return template.format(name=name, company=customer.get("company", ""))
        except KeyError:
            return template

    if strategy_context:
        message_type = strategy_context.get("message_type", "casual_checkin")
        memory_summary = strategy_context.get("memory_summary", "")
        country = strategy_context.get("country", "")

        # Step 1: Maker — AI generates the message
        message = generate_strategic_message(customer, message_type, memory_summary)

        # Step 2: Checker — sub-agent reviews with clean context
        has_recent = strategy_context.get("has_recent_activity", False)
        message = review_and_refine(
            message, customer, message_type,
            country=country,
            memory_summary=memory_summary,
        )

        return message

    return generate_followup(customer)


def get_random_delay(min_s: int = 60, max_s: int = 300) -> int:
    return random.randint(min_s, max_s)
