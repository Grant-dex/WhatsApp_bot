import logging
import random
from typing import Optional

from ai_reply import generate_followup, generate_strategic_message

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

    If strategy_context is provided, uses the AI strategy-aware message generator.
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
        return generate_strategic_message(customer, message_type, memory_summary)

    return generate_followup(customer)


def get_random_delay(min_s: int = 60, max_s: int = 300) -> int:
    return random.randint(min_s, max_s)
