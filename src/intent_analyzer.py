"""Pattern-based intent and sales-stage detection.

All detection is done via regex/keyword matching — no AI calls, zero token cost.
Used by the agent brain to understand where each customer is in the sales funnel.
"""

import re
from typing import Optional


# ── Intent Patterns ──────────────────────────────────────────────────────────────

INTENT_PATTERNS = {
    "rfq": [
        r"\b(?:quotation|quote|offer|price|pricing|how much|what.?s the price|cost of|estimate)\b",
        r"\b(?:报价|价格|多少钱|什么价|价位|询价|报价单)\b",
        r"\b(?:RFQ|request for quot(?:e|ation))\b",
    ],
    "technical": [
        r"\b(?:spec(?:ification)?s?|datasheet|catalog|brochure|manual|parameter|datasheet)\b",
        r"\b(?:参数|规格|型号|技术|说明书|样本|资料|数据表)\b",
        r"\b(?:power output|fuel consumption|efficiency|dimension|weight|noise|emission)\b",
        r"\b(?:功率|油耗|效率|尺寸|重量|噪音|排放|千瓦|兆瓦|KW|MW|kVA)\b",
    ],
    "delivery_inquiry": [
        r"\b(?:delivery|shipping|lead time|ETA|when can|how long|available|in stock)\b",
        r"\b(?:交期|发货|交货|到货|多长时间|什么时候|库存|现货)\b",
    ],
    "warranty_inquiry": [
        r"\b(?:warranty|guarantee|after.sales|service|maintenance|spare parts|support)\b",
        r"\b(?:保修|质保|售后|服务|维护|配件|维修|保养)\b",
    ],
    "payment_inquiry": [
        r"\b(?:payment|deposit|LC|T/T|terms|installment|down.?payment|MOQ)\b",
        r"\b(?:付款|定金|支付|信用证|电汇|起订量|最小订单)\b",
    ],
    "urgent": [
        r"\b(?:urgent|ASAP|as soon as|emergency|immediately|right away|rush)\b",
        r"\b(?:紧急|急|尽快|马上|立刻|立即|急需)\b",
    ],
    "complaint": [
        r"\b(?:problem|issue|broken|not working|defect|fail|fault|damage|wrong|bad)\b",
        r"\b(?:问题|坏了|不行|故障|有问题|不对|错误|投诉|退货|退款|refund)\b",
    ],
    "competitor_mention": [
        r"\b(?:competitor|compare|vs\.? |versus|alternative|other supplier|cheaper from)\b",
        r"\b(?:对比|比较|别家|其他厂家|竞品|对手|比.*便宜|更便宜)\b",
        r"\b(?:Cummins|Caterpillar|Perkins|Kohler|Generac|Yanmar|MTU|Volvo)\b",
    ],
    "closing_signal": [
        r"\b(?:order|buy|purchase|proceed|go ahead|send.*invoice|PI|proforma|contract|PO)\b",
        r"\b(?:下单|购买|订购|买|合同|发票|PI|形式发票)\b",
        r"\b(?:let.?s do|I.?ll take|I want.*order|please prepare)\b",
    ],
    "stop_request": [
        r"\b(?:stop|unsubscribe|不要再发|别发了|取消订阅|退订|remove|do not contact)\b",
        r"\b(?:not interested|不感兴趣|不要联系)\b",
    ],
}

# ── Sales Stage Detection ────────────────────────────────────────────────────────

STAGE_INDICATORS = {
    "initial_inquiry": {
        "patterns": [
            r"\b(?:hi|hello|hey|greetings|你好|您好|嗨)\b",
            r"\b(?:interest|interested|tell me|产品|介绍|了解)\b",
        ],
        "description": "初次接触，了解基本信息",
    },
    "qualification": {
        "patterns": [
            r"\b(?:need|require|looking for|project|requirement|application)\b",
            r"\b(?:需要|项目|需求|用途|用在|应用)\b",
        ],
        "description": "明确需求，评估是否匹配",
    },
    "technical_evaluation": {
        "patterns": [
            r"\b(?:spec|specification|datasheet|parameter|technical|功率|参数|规格|型号)\b",
            r"\b(?:compare|comparison|对比|比较|哪个好)\b",
        ],
        "description": "技术评估，对比选型",
    },
    "pricing_negotiation": {
        "patterns": [
            r"\b(?:price|pricing|quote|quotation|cost|discount|价格|报价|折扣|便宜)\b",
            r"\b(?:negotiate|bargain|best price|最低|优惠)\b",
        ],
        "description": "价格谈判阶段",
    },
    "closing": {
        "patterns": [
            r"\b(?:order|buy|purchase|proceed|go ahead|下单|购买|订购)\b",
            r"\b(?:PI|proforma|invoice|deposit|定金|付款)\b",
        ],
        "description": "即将成交",
    },
    "post_sale": {
        "patterns": [
            r"\b(?:delivery|shipping|installation|commissioning|training|交期|发货|安装|调试)\b",
            r"\b(?:after.*sale|warranty|service|售后|保修)\b",
        ],
        "description": "售后跟进",
    },
}


# ── Public API ───────────────────────────────────────────────────────────────────

def detect_intents(text: str) -> dict[str, bool]:
    """Detect all intents in a message. Returns dict of intent_name -> bool."""
    if not text:
        return {}
    text_lower = text.lower()
    results = {}
    for intent, patterns in INTENT_PATTERNS.items():
        results[intent] = any(re.search(p, text_lower) for p in patterns)
    return results


def detect_sales_stage(text: str) -> Optional[str]:
    """Detect the most likely sales stage from a message."""
    if not text:
        return None
    text_lower = text.lower()
    # Return the last matching stage (most advanced)
    matched = None
    for stage, info in STAGE_INDICATORS.items():
        if any(re.search(p, text_lower) for p in info["patterns"]):
            matched = stage
    return matched


def analyze_conversation_intent(customer_id: int) -> dict:
    """Analyze recent conversations to determine sales stage and key intents.

    Returns:
        {
            "stage": "technical_evaluation" or None,
            "stage_desc": "技术评估，对比选型" or "",
            "detected_intents": ["rfq", "technical"],
            "buying_signals": ["asked_about_price", "asked_about_delivery"],
            "has_recent_activity": True/False,
        }
    """
    from database import get_connection

    conn = get_connection()
    # Get last 10 inbound messages
    rows = conn.execute(
        "SELECT content FROM conversations "
        "WHERE customer_id=? AND direction='inbound' "
        "ORDER BY sent_at DESC LIMIT 10",
        (customer_id,)
    ).fetchall()

    if not rows:
        return {
            "stage": None,
            "stage_desc": "",
            "detected_intents": [],
            "buying_signals": [],
            "has_recent_activity": False,
        }

    all_text = " ".join(r["content"] or "" for r in rows)

    # Detect intents across all recent messages
    intents = detect_intents(all_text)
    active_intents = [k for k, v in intents.items() if v]

    # Detect sales stage
    stage = detect_sales_stage(all_text)
    stage_desc = STAGE_INDICATORS[stage]["description"] if stage else ""

    # Classify buying signals
    buying_signals = []
    signal_mapping = {
        "rfq": "asked_about_price",
        "technical": "asked_for_specs",
        "delivery_inquiry": "asked_about_delivery",
        "warranty_inquiry": "asked_about_warranty",
        "closing_signal": "ready_to_order",
        "payment_inquiry": "asked_about_payment",
        "urgent": "urgent_need",
    }
    for intent, signal in signal_mapping.items():
        if intents.get(intent):
            buying_signals.append(signal)

    return {
        "stage": stage,
        "stage_desc": stage_desc,
        "detected_intents": active_intents,
        "buying_signals": buying_signals,
        "has_recent_activity": True,
    }


def detect_stop_request(text: str) -> bool:
    """Check if the customer wants to stop receiving messages."""
    if not text:
        return False
    text_lower = text.lower()
    return any(re.search(p, text_lower) for p in INTENT_PATTERNS["stop_request"])
