"""HTTP client for the local Node.js WhatsApp bridge.

The bridge is the only component that knows whether WhatsApp accepted a
message. This module therefore returns a structured delivery result instead of
a bare boolean. In particular:

* ``sent``    — the bridge returned a platform message id.
* ``failed``  — a definite pre-send failure (not connected, 4xx, bridge down).
* ``unknown`` — the request may have reached WhatsApp (timeout, 5xx, unclear
  body). Unknown results are never retried automatically, because a retry
  could send the customer a duplicate message.

Only connect failures are retried, and only when the request could not have
been sent. All retries use the same payload, so a successful retry is reported
as a single sent result.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

import httpx

from config import get_config

logger = logging.getLogger(__name__)


def _result(status: str, *, message_id: Optional[str] = None,
            error: Optional[str] = None, error_code: Optional[str] = None,
            jid: Optional[str] = None) -> dict:
    return {
        "status": status,
        "message_id": message_id,
        "whatsapp_msg_id": message_id,
        "error": error,
        "error_code": error_code,
        "jid": jid,
    }


async def send_message(phone: str, message: str, max_retries: int = 2,
                       timeout: float = 40.0) -> dict:
    """Send a text message.

    ``max_retries`` applies only to connection failures where no request reached
    the bridge. Timeouts and ambiguous responses return ``unknown`` immediately.
    """
    if phone.endswith("@lid"):
        phone = phone.replace("@lid", "@c.us")
    cfg = get_config()
    import bridge_manager
    port = bridge_manager.current_port()
    url = f"http://{cfg.bridge.host}:{port}/send"
    payload = {"phone": phone, "message": message}

    attempts = max(1, int(max_retries))
    last_connect_error = None
    for attempt in range(attempts):
        try:
            async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
                resp = await client.post(url, json=payload)
        except httpx.ConnectError as e:
            # The TCP connection was never established. It is safe to retry.
            last_connect_error = e
            if attempt + 1 < attempts:
                await asyncio.sleep(2 ** attempt)
                continue
            logger.error("Bridge unreachable for %s: %s", phone, e)
            return _result("failed", error=f"bridge unreachable: {e}",
                           error_code="bridge_unreachable")
        except httpx.TimeoutException as e:
            # The request may have been delivered and acted on. Do not retry.
            logger.warning("Bridge send timed out (result unknown) for %s: %s", phone, e)
            return _result("unknown", error=f"bridge timeout: {e}",
                           error_code="timeout")
        except httpx.TransportError as e:
            logger.warning("Bridge transport error (result unknown) for %s: %s", phone, e)
            return _result("unknown", error=f"bridge transport error: {e}",
                           error_code="transport_error")
        except Exception as e:  # pragma: no cover - defensive
            logger.error("Bridge send failed before acceptance for %s: %s", phone, e)
            return _result("failed", error=str(e), error_code="client_error")

        if resp.status_code == 503:
            return _result("failed", error=_error_from_response(resp),
                           error_code="bridge_unauthenticated")
        if 400 <= resp.status_code < 500:
            return _result("failed", error=_error_from_response(resp),
                           error_code=f"http_{resp.status_code}")
        if resp.status_code >= 500:
            # The bridge accepted the HTTP request but errored. It might have
            # sent before crashing, so classify as unknown rather than failed.
            return _result("unknown", error=_error_from_response(resp),
                           error_code=f"http_{resp.status_code}")

        try:
            data = resp.json()
        except Exception:
            return _result("unknown", error="invalid JSON from bridge",
                           error_code="invalid_response")

        if not isinstance(data, dict):
            return _result("unknown", error="unexpected JSON from bridge",
                           error_code="invalid_response")
        status = data.get("status")
        message_id = data.get("message_id") or data.get("whatsapp_msg_id") or data.get("id")
        if status == "sent":
            return _result("sent", message_id=message_id, jid=data.get("jid"))
        if status == "unknown":
            return _result("unknown", error=data.get("error") or "bridge result unknown",
                           error_code=data.get("error_code") or "bridge_unknown",
                           jid=data.get("jid"))
        # Explicit bridge failure (e.g. unauthenticated, send threw before
        # acceptance). The bridge returns 200 with a JSON body for these.
        return _result("failed", error=data.get("error") or "bridge send failed",
                       error_code=data.get("error_code") or "bridge_failed",
                       jid=data.get("jid"))

    return _result("failed", error=str(last_connect_error or "bridge unreachable"),
                   error_code="bridge_unreachable")


def _error_from_response(resp: httpx.Response) -> str:
    try:
        data = resp.json()
        if isinstance(data, dict) and data.get("error"):
            return str(data["error"])
    except Exception:
        pass
    return f"bridge returned HTTP {resp.status_code}"
