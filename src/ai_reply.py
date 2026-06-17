from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Optional

from openai import OpenAI

from config import get_config
from database import get_last_ai_reply_time, get_recent_conversations

logger = logging.getLogger(__name__)

_client: Optional[OpenAI] = None
_hourly_reply_count = 0
_hourly_reset_at = time.time()
_counter_lock = threading.Lock()

def _get_client() -> OpenAI:
    global _client
    if _client is None:
        from config import get_api_key
        cfg = get_config()
        _client = OpenAI(api_key=get_api_key(), base_url=cfg.ai.base_url)
    return _client


# ── Specs loader ─────────────────────────────────────────────────────────────

def _load_product_specs() -> str:
    try:
        from database import get_connection
        conn = get_connection()
        rows = conn.execute("SELECT title, content FROM product_docs ORDER BY updated_at DESC").fetchall()
        if rows:
            parts = []
            for r in rows:
                parts.append(f"## {r['title']}\n{r['content']}")
            return "\n\n".join(parts)
    except Exception:
        pass
    # Fallback to file
    from config import get_bundle_dir
    p = get_bundle_dir() / "product_specs.txt"
    if not p.exists():
        logger.warning(f"product_specs.txt not found at {p}")
        return "(参数文档暂未加载)"
    try:
        return p.read_text(encoding="utf-8")
    except Exception as e:
        logger.error(f"Failed to read product_specs.txt: {e}")
        return "(参数文档读取失败)"


# ── Lean system prompt (~1.3K) ───────────────────────────────────────────────

def _build_system_prompt(customer: dict) -> str:
    notes = customer.get("notes", "")
    memory = f"\nCustomer history: {notes}" if (notes and notes.strip() and notes.strip() != "N/A") else ""
    return f"""You are a professional sales consultant communicating with customers via WhatsApp. Your company manufactures gas generator sets (7kW-4.5MW), with OEM partnerships including MWM, Lister Petter, CNPC Jichai, and MAN.{memory}

## Communication Style
- Chat like a real salesperson on WhatsApp: conversational, natural, warm. Never sound like a chatbot.
- Absolutely NO Markdown formatting: no asterisks, no hash headers, no numbered lists, no horizontal rules.
- Use plain text with line breaks. Separate paragraphs with a blank line.
- Ask only ONE question at a time. Wait for the customer's answer before asking the next.
- Keep replies to 3-5 sentences max. If the topic is complex, offer to send a spec sheet or schedule a call.

## Language Rules (CRITICAL)
- You MUST reply in the SAME language the customer uses.
- If the customer writes in English → reply in English.
- If the customer writes in Chinese → reply in Chinese.
- If the customer writes in Arabic / French / Spanish / Russian etc. → reply in that language.
- NEVER mix languages in a single reply.
- For short/ambiguous messages (like "Hi", "Hello", "OK"), default to ENGLISH.

## Product & Pricing
- Only use specs and figures from the product database. If you're not sure, say "Let me check with our technical team" — never make up numbers.
- Give price ranges only. Never give a formal quote in chat — say "I'll send you a formal quotation."
- Lead time is typically 12-20 weeks. Specific models can be checked for the customer.
- Warranty: 12 months or 1,000 hours.

## Conversation Flow
- After answering, naturally guide to the next step: ask about power requirements, recommend a model, send a spec sheet, or schedule a call.
- Don't be pushy, but every message should move the conversation forward.

Customer: {customer.get('name', 'Unknown')} | Company: {customer.get('company', 'N/A')}"""


def _build_specs_message() -> str:
    return "## PRODUCT SPECS DATABASE (reference only — use for answering questions)\nIf a spec is not found below, do NOT invent it.\n\n" + _load_product_specs()


def _build_chat_messages(customer_id: int, max_turns: int = 10) -> list[dict]:
    cfg = get_config()
    msgs = get_recent_conversations(customer_id, cfg.ai.max_context_messages)
    if not msgs:
        return []
    turns = []
    for m in msgs[-max_turns:]:
        turns.append({"role": "user" if m["direction"] == "inbound" else "assistant", "content": m["content"]})
    return turns


# ── Memory ───────────────────────────────────────────────────────────────────

def summarize_and_remember(customer_id: int, incoming: str, reply: str):
    try:
        from database import get_connection
        conn = get_connection()
        row = conn.execute("SELECT notes FROM customers WHERE id=?", (customer_id,)).fetchone()
        if not row:
            return
        old = row["notes"] or ""
        kw = {"功率":"问过功率","价格":"问过价格","price":"asked price","power":"asked power",
              "燃气":"对燃气机感兴趣","gas":"interested in gas","天然气":"需要天然气发电",
              "沼气":"需要沼气发电","biogas":"interested in biogas","CHP":"问过热电联产",
              "交付":"问过交期","delivery":"asked delivery","并机":"问过并机",
              "MWM":"对MWM感兴趣","Lister":"对LP感兴趣","MAN":"对MAN感兴趣",
              "济柴":"对济柴感兴趣","玉柴":"对玉柴感兴趣","潍柴":"对潍柴感兴趣"}
        topics = [v for k, v in kw.items() if k.lower() in incoming.lower()]
        if not topics:
            topics = ["有过一般咨询"]
        new = "；".join(list(dict.fromkeys(topics))[:3])
        combined = (old + "；" + new) if old and old.strip() and new not in old else (old or new)
        if len(combined) > 200:
            combined = combined[-200:]
            idx = combined.find("；")
            if idx > 0:
                combined = combined[idx + 1:]
        conn.execute("UPDATE customers SET notes=?, updated_at=? WHERE id=?",
                     (combined, datetime.now().isoformat(), customer_id))
        conn.commit()
    except Exception as e:
        logger.warning(f"Memory update failed: {e}")


# ── Gates ────────────────────────────────────────────────────────────────────

def should_auto_reply(message_body: str) -> bool:
    text = message_body.strip().lower()
    if len(text) < 1 or len(text) > 1000:
        return False
    return text not in {"ok","okay","thanks","thx","thank you","got it","k","kk","👍","好的","谢谢","收到","嗯","哦","好","👌"}


def check_rate_limits(customer_id: int) -> tuple[bool, str]:
    cfg = get_config()
    global _hourly_reply_count, _hourly_reset_at
    last = get_last_ai_reply_time(customer_id)
    if last and (datetime.now() - last) < timedelta(minutes=cfg.ai.reply_cooldown_minutes):
        return False, "cooldown"
    with _counter_lock:
        if time.time() - _hourly_reset_at > 3600:
            _hourly_reply_count = 0
            _hourly_reset_at = time.time()
        if _hourly_reply_count >= cfg.business.max_auto_replies_per_hour:
            return False, "hourly limit"
        _hourly_reply_count += 1
    return True, "ok"


# ── Language Detection ───────────────────────────────────────────────────────

import re

def _detect_message_language(text: str) -> str:
    """Detect the primary language of a message based on Unicode character ranges.

    Returns a language name for use in AI prompts
    (e.g. 'English', 'Chinese', 'Arabic', 'Russian').
    Returns empty string when the message is too short or ambiguous.
    """
    if not text or not text.strip():
        return ""

    text = text.strip()

    cjk = 0       # Chinese / Japanese / Korean
    arabic = 0    # Arabic / Persian / Urdu scripts
    cyrillic = 0  # Russian / Ukrainian / etc.
    latin = 0     # English / European languages

    for ch in text:
        cp = ord(ch)
        if (0x4E00 <= cp <= 0x9FFF       # CJK Unified Ideographs
                or 0x3400 <= cp <= 0x4DBF  # CJK Ext-A
                or 0x3000 <= cp <= 0x303F  # CJK punctuation
                or 0xFF00 <= cp <= 0xFFEF  # Fullwidth forms
                or 0x2E80 <= cp <= 0x2FDF  # CJK Radicals
                or 0x3200 <= cp <= 0x33FF  # Enclosed CJK
                or 0xF900 <= cp <= 0xFAFF  # CJK Compatibility
                or 0xFE30 <= cp <= 0xFE4F  # CJK Compatibility Forms
        ):
            cjk += 1
        elif (0x0600 <= cp <= 0x06FF       # Arabic
              or 0x0750 <= cp <= 0x077F     # Arabic Supplement
              or 0xFB50 <= cp <= 0xFDFF     # Arabic Presentation Forms-A
              or 0xFE70 <= cp <= 0xFEFF     # Arabic Presentation Forms-B
              or 0x08A0 <= cp <= 0x08FF     # Arabic Extended-A
        ):
            arabic += 1
        elif (0x0400 <= cp <= 0x04FF       # Cyrillic
              or 0x0500 <= cp <= 0x052F     # Cyrillic Supplement
        ):
            cyrillic += 1
        elif (0x0041 <= cp <= 0x005A        # A-Z
              or 0x0061 <= cp <= 0x007A     # a-z
              or 0x00C0 <= cp <= 0x024F     # Latin Extensions
              or 0x1E00 <= cp <= 0x1EFF     # Latin Extended Additional
        ):
            latin += 1

    total = cjk + arabic + cyrillic + latin
    if total == 0:
        return ""

    # CJK dominant → Chinese (threshold conservative to avoid false positives)
    if cjk > total * 0.3:
        return "Chinese"
    if arabic > total * 0.3:
        return "Arabic"
    if cyrillic > total * 0.4:
        return "Russian"
    # Latin-script messages → English (the international business default)
    return "English"


def _country_to_language(country_name: str) -> str:
    """Map a country name to its primary business language for follow-up messages.

    Returns a human-readable language name (e.g. 'English', 'Arabic').
    Returns empty string when the country cannot be mapped.
    """
    if not country_name:
        return ""

    COUNTRY_LANG = {
        # East Asia
        "China": "Chinese (Simplified)",
        "Japan": "English",
        "South Korea": "English",
        # Southeast Asia
        "Vietnam": "Vietnamese",
        "Indonesia": "English",
        "Thailand": "English",
        "Malaysia": "English",
        "Philippines": "English",
        "Singapore": "English",
        "Myanmar": "English",
        "Cambodia": "English",
        # South Asia
        "India": "English",
        "Pakistan": "English",
        "Bangladesh": "English",
        # Middle East
        "Saudi Arabia": "Arabic",
        "United Arab Emirates": "English",
        "Qatar": "English",
        "Oman": "English",
        "Kuwait": "English",
        "Bahrain": "English",
        "Iraq": "Arabic",
        "Jordan": "Arabic",
        "Lebanon": "Arabic",
        "Sudan": "Arabic",
        "Morocco": "French",
        "Algeria": "French",
        "Tunisia": "French",
        # Africa
        "Egypt": "Arabic",
        "Nigeria": "English",
        "South Africa": "English",
        "Kenya": "English",
        "Tanzania": "English",
        "Ghana": "English",
        "Ethiopia": "English",
        # Central Asia / Caucasus
        "Kazakhstan": "Russian",
        "Uzbekistan": "Russian",
        "Azerbaijan": "Russian",
        "Turkmenistan": "Russian",
        # Europe
        "Germany": "German",
        "France": "French",
        "Spain": "Spanish",
        "Italy": "Italian",
        "Netherlands": "English",
        "Belgium": "English",
        "Poland": "English",
        "Czech Republic": "English",
        "Romania": "English",
        "United Kingdom": "English",
        # CIS
        "Russia": "Russian",
        "Ukraine": "Ukrainian",
        "Turkey": "English",
        # Americas
        "Brazil": "Portuguese",
        "Mexico": "Spanish",
        "Argentina": "Spanish",
        "Chile": "Spanish",
        "Colombia": "Spanish",
        "Peru": "Spanish",
        # Oceania
        "Australia": "English",
    }

    # Exact match
    if country_name in COUNTRY_LANG:
        return COUNTRY_LANG[country_name]

    # Partial match (e.g. "Saudi Arabia" contained in longer string)
    for key, lang in COUNTRY_LANG.items():
        if key.lower() in country_name.lower() or country_name.lower() in key.lower():
            return lang

    return ""


# ── AI Reply ─────────────────────────────────────────────────────────────────

def _clean_reply(text: str) -> str:
    """Strip Markdown formatting and normalize newlines for WhatsApp."""
    # Strip bold/italic: **bold**, *italic*, ***both***
    text = re.sub(r'\*{1,3}(.+?)\*{1,3}', r'\1', text)
    # Strip underscore: __bold__, _italic_
    text = re.sub(r'_{1,2}(.+?)_{1,2}', r'\1', text)
    # Strip strikethrough: ~~text~~
    text = re.sub(r'~~(.+?)~~', r'\1', text)
    # Strip backtick code: `code`
    text = re.sub(r'`(.+?)`', r'\1', text)
    # Strip markdown headers: ###, ##, # at line start
    text = re.sub(r'^#{1,4}\s+', '', text, flags=re.MULTILINE)
    # Strip horizontal rules: ---, ***, ___
    text = re.sub(r'^[-*_]{3,}\s*$', '', text, flags=re.MULTILINE)
    # Normalize newlines
    text = text.replace('\r\n', '\n').replace('\r', '\n')
    text = re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


def generate_reply(customer: dict, incoming_message: str) -> str:
    cfg = get_config()
    try:
        client = _get_client()

        # Detect the customer's language from the actual message content.
        # Character-level detection is not affected by the system prompt language,
        # so CJK / Arabic / Cyrillic scripts are reliably identified.
        detected_lang = _detect_message_language(incoming_message)

        messages = [
            {"role": "system", "content": _build_system_prompt(customer)},
            {"role": "system", "content": _build_specs_message()},
        ]
        messages.extend(_build_chat_messages(customer["id"], 10))

        # Explicit language instruction prevents the AI from defaulting to
        # Chinese when the incoming message is short or ambiguous.
        if detected_lang:
            messages.append({
                "role": "system",
                "content": f"IMPORTANT: The customer wrote in {detected_lang}. You MUST reply in {detected_lang}."
            })
        else:
            # Short/ambiguous message (e.g. "Hi", "OK") — default to English,
            # not Chinese. This is an international business context.
            messages.append({
                "role": "system",
                "content": "IMPORTANT: Default to English for this reply."
            })

        messages.append({"role": "user", "content": incoming_message})
        resp = client.chat.completions.create(model=cfg.ai.model, max_tokens=800, messages=messages)
        reply = _clean_reply(resp.choices[0].message.content)
        if len(reply) > cfg.ai.reply_max_length:
            reply = reply[:cfg.ai.reply_max_length].rsplit(" ", 1)[0]
        return reply
    except Exception as e:
        logger.error(f"AI reply failed: {e}")
        return _fallback_reply(incoming_message)


def _fallback_reply(message: str) -> str:
    """Fallback reply when the AI API call fails.

    Returns English replies by default. For Chinese-speaking customers,
    the AI should not be failing — but if it does, a polite English
    message is safer than accidentally sending Chinese to a non-Chinese customer.
    """
    t = message.strip().lower()
    if any(w in t for w in ["hi","hello","hey","你好","哈喽","嗨"]):
        return "Hi! Thanks for reaching out — I'll get back to you shortly. How can I help?"
    if "?" in t or "？" in t:
        return "Great question — let me check with our technical team and get back to you!"
    return "Got it! I'll follow up with you soon. 😊"


def generate_followup(customer: dict) -> str:
    from country_utils import get_country_from_phone, get_power_context, GLOBAL_POWER_TRENDS

    cfg = get_config()
    phone = customer.get("phone", "")
    country_info = get_country_from_phone(phone)
    country_name = country_info.get("country_name", "")
    power_context = get_power_context(country_name)

    # Determine the customer's language from their phone country prefix.
    # This prevents the AI from guessing (and often defaulting to Chinese)
    # when no chat history exists.
    language = _country_to_language(country_name)

    try:
        client = _get_client()
        country_hint = ""
        if country_name:
            country_hint = f"\nThe customer is in {country_name}."
            if power_context:
                country_hint += f"\nLocal electricity context: {power_context}"
            else:
                country_hint += f"\nGlobal power industry trends: {GLOBAL_POWER_TRENDS}"

        # Build an explicit language instruction instead of the vague
        # "Match the customer's language" which the AI often misinterprets.
        if language:
            lang_instruction = f"You MUST write this message in {language}."
        elif country_name:
            lang_instruction = f"Write this message in the most common business language for {country_name}."
        else:
            lang_instruction = "Write this message in English."

        resp = client.chat.completions.create(
            model=cfg.ai.model, max_tokens=400,
            messages=[
                {"role": "system", "content": f"""You are a technical sales follow-up assistant for a gas generator manufacturer (7kW-4.5MW, OEM partner of MWM, Lister Petter, CNPC Jichai, MAN).

Write a short, warm follow-up message. One or two sentences max, casual not pushy.

{lang_instruction}

IMPORTANT: Sign off with the sender's real name which is {cfg.business.owner_name}. NEVER use placeholder text like [Your Name], [Name], or any bracket text — always use the actual name.

When there is local electricity/power industry context, naturally reference it to show you understand their market. For example:
- If their country has grid reliability issues, mention how gas gensets help with backup power
- If they're in oil & gas, mention reliable power for remote operations
- If they're transitioning from coal, mention cleaner natural gas alternatives
- Don't force it — if the context doesn't fit naturally, just be warmly casual"""},
                {"role": "user", "content": f"""Customer: {customer.get('name','Valued Customer')} from {customer.get('company','N/A')}.
Notes: {customer.get('notes','N/A')}.{country_hint}

Write a short follow-up message in {language if language else 'English'}, and sign off as {cfg.business.owner_name}:"""},
            ])
        return _clean_reply(resp.choices[0].message.content)
    except Exception as e:
        logger.error(f"Follow-up failed: {e}")
        if country_name and power_context:
            return f"Hi {customer.get('name','there')}, following up — just a quick note on the power situation in {country_name}, our gas generators might be a great fit for your needs. Happy to chat when you have a moment!"
        return f"Hi {customer.get('name','there')}, just checking in — anything I can help with regarding the gas generators?"


# ── Strategy-Aware Message Generation ─────────────────────────────────────────

STRATEGY_PROMPTS = {
    "quote_followup": """You are following up on a pricing/quote discussion.
The customer has shown buying intent. Write a warm follow-up that:
- References the previous pricing discussion naturally
- Asks about their decision timeline without being pushy
- Offers to provide additional specs or answer questions
- Keeps it to 2-3 sentences max
{lang_instruction}
Sign off as {owner_name}.""",

    "specs_solution": """You are a technical sales engineer following up with a customer
who has shown interest in specific technical details. Write a message that:
- References their specific technical requirements if you know them
- Offers relevant technical information or documentation
- Shows technical competence without being overwhelming
- Keeps it to 2-3 sentences max
{lang_instruction}
Sign off as {owner_name}.""",

    "casual_checkin": """You are a friendly sales rep checking in on a customer.
Write a warm, casual message that:
- Feels like a natural WhatsApp message from a real person
- Doesn't push for a sale — just maintains the relationship
- References something from previous conversations if possible
- Keeps it to 1-2 sentences max
{lang_instruction}
Sign off as {owner_name}.""",

    "value_add": """You are sharing valuable market or product insight with a customer.
Write a message that:
- Shares one interesting fact or insight relevant to their business
- Positions you as a helpful industry resource, not a salesperson
- Invites conversation naturally
- Keeps it to 2-3 sentences max
{lang_instruction}
Sign off as {owner_name}.""",

    "re_engage": """You are trying to re-engage a customer who hasn't responded in a while.
Write a message that:
- Takes a fresh angle — don't repeat what you've said before
- Is light and low-pressure
- Gives them an easy way to respond (a simple question)
- Keeps it to 1-2 sentences max
{lang_instruction}
Sign off as {owner_name}.""",

    "win_back": """You are reaching out to a dormant customer who hasn't engaged in months.
Write a message that:
- Is very low-pressure — they may have forgotten about you
- Reminds them gently that you're still here if they need anything
- Does NOT sound desperate or spammy
- Keeps it to 1 sentence max
{lang_instruction}
Sign off as {owner_name}.""",

    "introduction": """You are introducing yourself to a new customer for the first time.
Write a message that:
- Briefly introduces who you are and what your company does
- Shows you understand their market/country context
- Opens the door for conversation without being salesy
- Keeps it to 2-3 sentences max
{lang_instruction}
Sign off as {owner_name}.""",

    "reactivation": """You are reactivating a customer who may have gone quiet.
Write a message that:
- Has a timely hook (market update, new product, industry news)
- Feels fresh and worth responding to
- Is casual and non-committal
- Keeps it to 1-2 sentences max
{lang_instruction}
Sign off as {owner_name}.""",
}


def generate_strategic_message(customer: dict, message_type: str,
                                 memory_summary: str = "") -> str:
    """Generate a strategy-aware AI followup message.

    Args:
        customer: Customer dict (name, phone, company, notes, etc.)
        message_type: One of the STRATEGY_PROMPTS keys
        memory_summary: Pre-fetched AI memory text for personalization

    Returns the generated message string.
    """
    from country_utils import get_country_from_phone, get_power_context, GLOBAL_POWER_TRENDS

    cfg = get_config()
    phone = customer.get("phone", "")
    country_info = get_country_from_phone(phone)
    country_name = country_info.get("country_name", "")
    power_context = get_power_context(country_name)
    language = _country_to_language(country_name)

    # Build language instruction
    if language:
        lang_instruction = f"You MUST write this message in {language}."
    elif country_name:
        lang_instruction = f"Write this message in the most common business language for {country_name}."
    else:
        lang_instruction = "Write this message in English."

    # Get the strategy prompt template
    prompt_template = STRATEGY_PROMPTS.get(message_type, STRATEGY_PROMPTS["casual_checkin"])

    # Build system prompt
    system_prompt = prompt_template.format(
        lang_instruction=lang_instruction,
        owner_name=cfg.business.owner_name,
    )

    # Build user message with customer context
    user_parts = [
        f"Customer: {customer.get('name', 'Valued Customer')}",
        f"Company: {customer.get('company', 'N/A')}",
    ]
    if country_name:
        country_hint = f"Location: {country_name}."
        if power_context:
            country_hint += f" Power context: {power_context}"
        else:
            country_hint += f" Industry context: {GLOBAL_POWER_TRENDS}"
        user_parts.append(country_hint)
    if memory_summary:
        user_parts.append(f"Customer memory:\n{memory_summary}")
    if customer.get("notes") and customer["notes"] != "N/A":
        user_parts.append(f"Notes: {customer['notes']}")

    user_message = "\n".join(user_parts)

    try:
        client = _get_client()
        resp = client.chat.completions.create(
            model=cfg.ai.model,
            max_tokens=400,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
        )
        return _clean_reply(resp.choices[0].message.content)
    except Exception as e:
        logger.error(f"Strategic message failed (type={message_type}): {e}")
        # Fallback to standard followup
        return generate_followup(customer)