"""PyInstaller launcher for WhatsApp Bot backend."""
import os, sys, datetime, traceback


def _get_log_path():
    data_dir = os.getenv("WHATSAPP_BOT_DATA_DIR", "")
    if data_dir:
        return os.path.join(data_dir, "logs", "backend.log")
    return os.path.join(os.path.expanduser("~"), "Library", "Application Support",
                         "WhatsAppBot", "logs", "backend.log")


LOG_PATH = _get_log_path()


def log(msg):
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, "a") as f:
            f.write(f"{datetime.datetime.now()} [{os.getpid()}] {msg}\n")
            f.flush()
    except Exception:
        pass


def fatal(msg):
    log(f"FATAL: {msg}")
    log(traceback.format_exc())
    sys.exit(1)


log("=== Backend starting ===")

try:
    # Set up data directory
    if not os.getenv("WHATSAPP_BOT_DATA_DIR"):
        os.environ["WHATSAPP_BOT_DATA_DIR"] = os.path.join(
            os.path.expanduser("~"), "Library", "Application Support", "WhatsAppBot"
        )
    data_dir = os.environ["WHATSAPP_BOT_DATA_DIR"]
    os.makedirs(data_dir, exist_ok=True)
    os.makedirs(os.path.join(data_dir, "data"), exist_ok=True)
    os.makedirs(os.path.join(data_dir, "logs"), exist_ok=True)
    log(f"data_dir={data_dir}")

    # Determine API port
    api_port = int(os.getenv("API_PORT", "8000"))
    log(f"api_port={api_port}")

    # Import core modules
    import yaml
    import pydantic
    from config import load_dotenv, load_config

    load_dotenv()
    import shutil
    try:
        load_config()
    except Exception:
        log("load_config failed, copying default config from bundle")
        bundle_dir = getattr(sys, '_MEIPASS', os.path.dirname(os.path.abspath(sys.argv[0])))
        cfg_src = os.path.join(bundle_dir, "config.yaml")
        if os.path.exists(cfg_src):
            shutil.copy(cfg_src, os.path.join(data_dir, "config.yaml"))
            load_config()
        else:
            fatal(f"Default config.yaml not found at {cfg_src}")
    log("config loaded")

    from database import get_connection
    get_connection()
    log("DB initialized")

    # Set up message handler so WhatsApp messages get AI replies
    from message_router import handle_incoming_message
    from api_server import set_message_handler
    set_message_handler(handle_incoming_message)
    log("message handler set")

    # Start follow-up scheduler
    from scheduler import start_scheduler
    start_scheduler()
    log("scheduler started")

    import uvicorn
    from api_server import app
    log(f"Starting uvicorn on 127.0.0.1:{api_port}")
    uvicorn.run(app, host="127.0.0.1", port=api_port, log_level="info")

except SystemExit:
    raise
except Exception as e:
    fatal(str(e))
