import html
import logging
import os
import sys
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
import uvicorn

logger = logging.getLogger(__name__)

_server_started = threading.Event()
_server_error: Optional[str] = None


def _init_app():
    """Auto-initialize config and database when running standalone (e.g., web_main.py)."""
    from config import load_config, load_dotenv, get_data_dir

    data_dir = get_data_dir()
    os.makedirs(data_dir, exist_ok=True)
    os.makedirs(data_dir / "logs", exist_ok=True)

    # Load .env and config from data dir
    load_dotenv()
    try:
        load_config()
    except FileNotFoundError:
        # Copy default config to data dir
        from config import get_bundle_dir
        default_config = get_bundle_dir() / "config.yaml"
        if default_config.exists():
            import shutil
            shutil.copy(default_config, data_dir / "config.yaml")
            load_config()
        else:
            raise

    # Initialize database
    from database import get_connection
    get_connection()
    logger.info(f"App initialized, data dir: {data_dir}")


@asynccontextmanager
async def _lifespan(app: FastAPI):
    """Runs AFTER uvicorn successfully binds the port."""
    _server_started.set()
    yield


# Auto-initialize when running standalone (web_main.py / direct uvicorn)
try:
    from config import _config
    if _config is None:
        _init_app()
except Exception:
    pass

app = FastAPI(title="WhatsApp Bot Internal API", lifespan=_lifespan)
# Expose application assets only, never design references or data directories.
app.mount("/assets", StaticFiles(directory=Path(__file__).resolve().parent / "static" / "assets"), name="admin-assets")

# ── 多租户认证 ──────────────────────────────────────────────────────────
# 必须在应用启动前挂载：中间件按 cookie 解析 session，并把租户写进
# contextvar，后续 get_config()/get_connection() 自动落到租户目录。
import accounts as _accounts
import auth as _auth

try:
    _accounts.get_conn()
except Exception as _e:  # 账号库不可用时不阻塞启动，但会打日志
    logger.error("账号库初始化失败: %s", _e)
_auth.install(app)


class IncomingMessage(BaseModel):
    from_: str = Field(alias="from")
    body: str
    msg_id: Optional[str] = None
    timestamp: Optional[str] = None


class DeliveryReceipt(BaseModel):
    conversation_id: Optional[int] = None
    whatsapp_msg_id: Optional[str] = None
    status: str
    error: Optional[str] = None
    error_code: Optional[str] = None
    phone: Optional[str] = None


_message_handler = None


def set_message_handler(handler):
    global _message_handler
    _message_handler = handler


@app.post("/webhook/message")
async def receive_message(msg: IncomingMessage):
    logger.info(f"[inbound] from={msg.from_} body={msg.body[:80]}")
    if _message_handler is None:
        return {"action": "ignore", "reason": "no handler"}
    try:
        return await _message_handler(msg.from_, msg.body, msg.msg_id)
    except Exception as e:
        logger.error(f"Message handler error: {e}", exc_info=True)
        return {"action": "ignore", "reason": "error"}


@app.post("/webhook/delivery")
async def receive_delivery(receipt: DeliveryReceipt):
    """Idempotent delivery receipt from the bridge.

    The bridge sends instant replies itself, then reports the real platform
    message id and status here. Repeating a receipt is a no-op and never
    creates a second conversation row.
    """
    if receipt.status not in ("sent", "failed", "unknown"):
        return {"ok": False, "changed": False,
                "error": "status must be sent, failed or unknown"}
    from send_service import apply_delivery_receipt
    result = apply_delivery_receipt(
        receipt.conversation_id,
        receipt.status,
        whatsapp_msg_id=receipt.whatsapp_msg_id,
        error=receipt.error or receipt.error_code,
        whatsapp_msg_id_lookup=receipt.whatsapp_msg_id,
    )
    logger.info(
        "[delivery] conversation=%s status=%s msg_id=%s changed=%s",
        receipt.conversation_id, receipt.status, receipt.whatsapp_msg_id,
        result.get("changed"),
    )
    return result


@app.post("/webhook/qr")
async def receive_qr(data: dict):
    from qr_state import set_pending_qr, clear_pending_qr
    qr_text = data.get("qr_text")
    if qr_text:
        set_pending_qr(qr_text)
        logger.info("[qr] QR code received from bridge")
    else:
        clear_pending_qr()
        logger.info("[qr] QR code cleared (WhatsApp connected)")
    return {"status": "ok"}


@app.get("/health")
async def health():
    return {"status": "ok"}


def _admin_html_path() -> Path:
    """Locate admin.html for both frozen and source runs.

    Source runs keep it at ``<repo>/src/static/admin.html``. The frozen
    fallback is kept only for compatibility with previously packaged builds.

    Note this is NOT derivable from ``config.get_bundle_dir()``: in source mode
    that returns the repo root, so ``repo/static/admin.html`` does not exist and
    ``/`` used to answer 500 even though the backend was healthy.
    """
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "static" / "admin.html"
    return Path(__file__).resolve().parent / "static" / "admin.html"


@app.get("/")
async def admin_dashboard():
    admin_html = _admin_html_path()
    if admin_html.exists():
        return HTMLResponse(content=admin_html.read_text(encoding="utf-8"))

    # Older bundles may still place the file under the bundle dir.
    from config import get_bundle_dir
    fallback = get_bundle_dir() / "static" / "admin.html"
    if fallback.exists():
        return HTMLResponse(content=fallback.read_text(encoding="utf-8"))

    logger.error("Admin panel not found; looked at %s and %s", admin_html, fallback)
    return HTMLResponse(
        content=f"<h1>Admin panel not found</h1><pre>{html.escape(str(admin_html))}</pre>",
        status_code=500,
    )


# Register admin API routes
from admin_api import router as admin_router
app.include_router(admin_router)


def run_api_server():
    global _server_error
    from config import get_config
    cfg = get_config()
    try:
        uvicorn.run(app, host=cfg.api.host, port=cfg.api.port, log_level="warning")
    except Exception as e:
        _server_error = str(e)
        logger.error(f"API server failed: {e}")
