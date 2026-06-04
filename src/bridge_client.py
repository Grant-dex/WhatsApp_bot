import asyncio
import logging
import httpx
from config import get_config

logger = logging.getLogger(__name__)


async def send_message(phone: str, message: str, max_retries: int = 3) -> dict:
    if phone.endswith("@lid"):
        phone = phone.replace("@lid", "@c.us")
    cfg = get_config()
    url = f"http://{cfg.bridge.host}:{cfg.bridge.port}/send"
    payload = {"phone": phone, "message": message}
    last_error = None
    for attempt in range(max_retries):
        try:
            async with httpx.AsyncClient(timeout=30.0, trust_env=False) as client:
                resp = await client.post(url, json=payload)
                data = resp.json()
                if resp.is_error:
                    error_detail = data.get("error", resp.reason_phrase)
                    raise httpx.HTTPStatusError(
                        f"Bridge returned {resp.status_code}: {error_detail}",
                        request=resp.request,
                        response=resp
                    )
                return data
        except Exception as e:
            last_error = e
            await asyncio.sleep(2 ** attempt)
    logger.error(f"Failed to send to {phone}: {last_error}")
    return {"status": "failed", "error": str(last_error)}


