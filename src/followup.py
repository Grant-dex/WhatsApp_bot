import logging
import random
from ai_reply import generate_followup

logger = logging.getLogger(__name__)


def generate_followup_message(customer: dict) -> str:
    template = customer.get("template")
    name = customer.get("name", "")
    if template:
        try:
            return template.format(name=name, company=customer.get("company", ""))
        except KeyError:
            return template
    return generate_followup(customer)


def get_random_delay(min_s: int = 60, max_s: int = 300) -> int:
    return random.randint(min_s, max_s)
