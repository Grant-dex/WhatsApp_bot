#!/usr/bin/env python3
"""Standalone web entry point — run the admin console in a browser.

This replaces the Electron shell for local use: no packaging, no dynamic port
allocation, no ``pkill``, and no desktop window owning the backend lifecycle.

    python src/web_main.py                  # http://127.0.0.1:8000
    python src/web_main.py --port 8080
    python src/web_main.py --with-bridge    # also start the Node WhatsApp bridge
    python src/web_main.py --host 0.0.0.0   # reachable from a phone on the LAN

Data (SQLite, config.yaml, .env, logs) lives in ``--data-dir`` (default:
``<repo>/data``), so updating the code never touches customer data.
"""
from __future__ import annotations

import argparse
import logging
import logging.handlers
import os
import shutil
import socket
import subprocess
import sys
import threading
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

logger = logging.getLogger("whatsapp-bot.web")


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the WhatsApp Bot admin console in a browser.")
    parser.add_argument("--host", default="127.0.0.1",
                        help="bind address; use 0.0.0.0 to reach it from your phone")
    parser.add_argument("--port", type=int, default=8000, help="HTTP port (default: 8000)")
    parser.add_argument("--bridge-port", type=int, default=3001,
                        help="port for the Node bridge when --with-bridge is used")
    parser.add_argument("--data-dir", default=None,
                        help="data folder (default: <repo>/data)")
    parser.add_argument("--with-bridge", action="store_true",
                        help="also start the Node WhatsApp bridge")
    parser.add_argument("--no-scheduler", action="store_true",
                        help="do not run follow-up automation / daily batch push")
    parser.add_argument("--no-browser", action="store_true",
                        help="do not open a browser window")
    return parser.parse_args(argv)


def port_in_use(host: str, port: int) -> bool:
    probe_host = "127.0.0.1" if host in ("0.0.0.0", "") else host
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((probe_host, port)) == 0


def setup_logging(data_dir: Path) -> None:
    log_dir = data_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler = logging.handlers.RotatingFileHandler(
        log_dir / "web.log", maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8")
    file_handler.setFormatter(fmt)
    file_handler.setLevel(logging.DEBUG)
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(fmt)
    console.setLevel(logging.INFO)
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    root.addHandler(file_handler)
    root.addHandler(console)


def ensure_data_dir(data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "data").mkdir(parents=True, exist_ok=True)
    target = data_dir / "config.yaml"
    if not target.exists():
        default = ROOT / "config.yaml"
        if default.exists():
            shutil.copy(default, target)
            logger.info("Created %s from the bundled default", target)
        else:
            raise FileNotFoundError(f"config.yaml not found in {ROOT} or {data_dir}")


def start_bridge(bridge_port: int, api_port: int, data_dir: Path):
    script = ROOT / "bridge" / "index.js"
    if not script.exists():
        logger.error("Bridge script not found: %s", script)
        return None
    if not (ROOT / "bridge" / "node_modules").exists():
        logger.warning(
            "bridge/node_modules is missing — skipping the bridge. "
            "Install it once with: npm --prefix %s install", ROOT / "bridge")
        return None

    env = os.environ.copy()
    env.update({
        "PYTHON_API": f"http://127.0.0.1:{api_port}",
        "BRIDGE_HOST": "127.0.0.1",
        "BRIDGE_PORT": str(bridge_port),
        "NO_PROXY": "127.0.0.1,localhost",
        "no_proxy": "127.0.0.1,localhost",
        "WHATSAPP_BOT_DATA_DIR": str(data_dir),
    })
    logger.info("Starting bridge on port %s: node %s", bridge_port, script)
    return subprocess.Popen(["node", str(script)], cwd=str(ROOT), env=env)


def _start_owner_bridge(_api_port: int) -> None:
    """兼容旧参数：为管理员账号拉起 bridge（其余用户按需启动）。"""
    import accounts
    import bridge_manager
    from tenancy import Tenant

    users = accounts.list_users()
    owner = next((u for u in users if u.get("is_owner")), users[0] if users else None)
    if not owner:
        logger.warning("尚无账号，跳过 --with-bridge")
        return
    tenant = Tenant(owner["id"], owner["email"], Path(owner["data_dir"]))
    try:
        status = bridge_manager.start(tenant)
        logger.info("Bridge 已启动（%s）: port=%s", owner["email"], status.get("port"))
    except Exception as exc:
        logger.error("Bridge 启动失败: %s", exc)


def main(argv=None) -> int:
    args = parse_args(argv)

    data_dir = (Path(args.data_dir).expanduser().resolve()
                if args.data_dir else ROOT / "data")
    # config.get_data_dir() reads this, so it must be set before importing config.
    os.environ["WHATSAPP_BOT_DATA_DIR"] = str(data_dir)

    ensure_data_dir(data_dir)
    setup_logging(data_dir)

    # Never kill whatever is on the port (main.py does); report it instead.
    if port_in_use(args.host, args.port):
        logger.error(
            "Port %s is already in use on %s. Stop that process or pass --port.",
            args.port, args.host)
        return 1

    from config import get_api_key, get_config, load_config, load_dotenv

    load_dotenv(str(data_dir / ".env"))
    load_config(str(data_dir / "config.yaml"))
    cfg = get_config()
    logger.info("Data dir: %s", data_dir)
    logger.info("Model: %s via %s", cfg.ai.model, cfg.ai.base_url)

    try:
        get_api_key()
        logger.info("LLM API key loaded")
    except RuntimeError:
        logger.warning(
            "LLM_API_KEY is not set. The console works, but AI replies will fail "
            "until you add LLM_API_KEY=... to %s", data_dir / ".env")

    from database import get_connection
    get_connection()
    logger.info("Database ready: %s", cfg.database.path)

    # 账号库（全局，和租户目录并列）
    import accounts as _accounts
    _accounts.get_conn()
    if _accounts.count_users() == 0:
        logger.info("尚未创建账号：打开 %s/login 初始化管理员账号", f"http://127.0.0.1:{args.port}")
    else:
        logger.info("已注册用户: %d", _accounts.count_users())

    # Config is loaded, so api_server's auto-init (which swallows errors) stays off.
    from api_server import app, set_message_handler
    from message_router import handle_incoming_message
    set_message_handler(handle_incoming_message)

    if args.with_bridge:
        _start_owner_bridge(args.port)
    else:
        logger.info("Bridge 未启动（用户可在控制台点击“启动连接”按需拉起）")

    if args.no_scheduler:
        logger.info("Scheduler disabled (--no-scheduler)")
    else:
        from scheduler import start_scheduler
        start_scheduler()

    shown_host = "127.0.0.1" if args.host in ("0.0.0.0", "") else args.host
    url = f"http://{shown_host}:{args.port}"
    logger.info("Admin console: %s", url)
    if not args.no_browser:
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()

    import uvicorn

    try:
        uvicorn.run(app, host=args.host, port=args.port, log_level="info")
    except KeyboardInterrupt:
        pass
    finally:
        try:
            import bridge_manager
            logger.info("Stopping bridges...")
            bridge_manager.shutdown_all()
        except Exception:
            logger.exception("关闭 bridge 进程失败")
        logger.info("Stopped.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
