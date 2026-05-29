import logging
import os
import sys
import threading
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
import uvicorn

logger = logging.getLogger(__name__)

_server_started = threading.Event()
_server_error: Optional[str] = None


def _init_app():
    """Auto-initialize config and database when running standalone (e.g., via Electron)."""
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


# Auto-initialize when running standalone (e.g., via Electron's uvicorn spawn)
try:
    from config import _config
    if _config is None:
        _init_app()
except Exception:
    pass

app = FastAPI(title="WhatsApp Bot Internal API", lifespan=_lifespan)


class IncomingMessage(BaseModel):
    from_: str = Field(alias="from")
    body: str
    msg_id: Optional[str] = None
    timestamp: Optional[str] = None


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


@app.get("/")
async def admin_dashboard():
    from pathlib import Path
    from config import get_bundle_dir
    admin_html = get_bundle_dir() / "static" / "admin.html"
    if admin_html.exists():
        from fastapi.responses import HTMLResponse
        return HTMLResponse(content=admin_html.read_text(encoding="utf-8"))
    # Fallback
    from fastapi.responses import HTMLResponse
    return HTMLResponse(content="<h1>Admin panel not found</h1>", status_code=500)


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
