#!/usr/bin/env python3
import logging
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

from api_server import run_api_server, set_message_handler
from config import load_config, load_dotenv
from database import close_db, get_connection
from message_router import handle_incoming_message
from qr_state import set_pending_qr, clear_pending_qr
from scheduler import start_scheduler

logger = logging.getLogger("whatsapp-bot")
_shutdown_flag = threading.Event()
_bridge_process = None


def setup_logging():
    (d := Path("logs")).mkdir(exist_ok=True)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
    fh = logging.FileHandler(d / "bot.log"); fh.setFormatter(fmt); fh.setLevel(logging.DEBUG)
    ch = logging.StreamHandler(sys.stdout); ch.setFormatter(fmt); ch.setLevel(logging.INFO)
    root = logging.getLogger(); root.setLevel(logging.DEBUG); root.addHandler(fh); root.addHandler(ch)


def kill_port(port):
    """Kill any process occupying the given port."""
    subprocess.run(
        f"lsof -ti :{port} | xargs kill -9 2>/dev/null",
        shell=True, capture_output=True
    )


def start_bridge():
    """Start the Node.js WhatsApp bridge as a subprocess."""
    bridge_script = Path(__file__).parent.parent / "bridge" / "index.js"
    if not bridge_script.exists():
        logger.error(f"Bridge script not found: {bridge_script}")
        sys.exit(1)

    env = os.environ.copy()
    env["PYTHON_API"] = "http://127.0.0.1:8000"
    env["BRIDGE_PORT"] = "3001"
    env["BRIDGE_HOST"] = "127.0.0.1"
    env["NO_PROXY"] = "127.0.0.1,localhost"
    env["no_proxy"] = "127.0.0.1,localhost"

    logger.info(f"Starting bridge: node {bridge_script}")
    proc = subprocess.Popen(
        ["node", str(bridge_script)],
        cwd=str(Path(__file__).parent.parent),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    return proc


def monitor_bridge(proc):
    """Monitor bridge stdout and restart if it crashes."""
    global _bridge_process
    restart_count = 0
    restart_window_start = time.time()

    while not _shutdown_flag.is_set():
        if proc.poll() is not None:
            exit_code = proc.returncode
            logger.error(f"Bridge process exited with code {exit_code}")
            if _shutdown_flag.is_set():
                break

            now = time.time()
            if now - restart_window_start > 600:
                restart_count = 0
                restart_window_start = now

            restart_count += 1
            if restart_count > 5:
                logger.critical("Bridge crashed >5 times in 10 min, giving up")
                os.kill(os.getpid(), signal.SIGTERM)
                return

            delay = min(5 * restart_count, 60)
            logger.info(f"Restarting bridge in {delay}s (attempt {restart_count})")
            _shutdown_flag.wait(delay)
            if _shutdown_flag.is_set():
                break

            if not _shutdown_flag.is_set():
                kill_port(3001)
                time.sleep(1)
                proc = start_bridge()
                _bridge_process = proc
            continue

        if proc.stdout:
            line = proc.stdout.readline()
            if line:
                line = line.strip()
                if not line or line.startswith('{"level":'):
                    pass
                elif '>>> QR_RECEIVED <<<' in line:
                    raw_qr = None
                    for inner in proc.stdout:
                        inner = inner.strip()
                        if '>>> QR_END <<<' in inner:
                            break
                        if inner.startswith('RAW_QR:'):
                            raw_qr = inner[7:]
                    set_pending_qr(raw_qr)
                    if raw_qr:
                        logger.info('[bridge] QR code ready — scan in admin panel')
                elif 'WHATSAPP_READY' in line:
                    clear_pending_qr()
                    logger.info(f'[bridge] {line}')
                else:
                    logger.info(f'[bridge] {line}')

        time.sleep(0.05)


def shutdown(signum=None, frame=None):
    logger.info(f"Shutting down (signal={signum})...")
    _shutdown_flag.set()
    if _bridge_process and _bridge_process.poll() is None:
        logger.info("Terminating bridge...")
        _bridge_process.terminate()
        try:
            _bridge_process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            _bridge_process.kill()
    close_db()
    logger.info("Bot stopped.")
    sys.exit(0)


def main():
    setup_logging()
    logger.info("=" * 50)
    logger.info("WhatsApp Bot starting...")
    logger.info("=" * 50)

    load_dotenv()

    config_path = sys.argv[1] if len(sys.argv) > 1 else "config.yaml"
    if not Path(config_path).exists():
        logger.error(f"Config not found: {config_path}"); sys.exit(1)
    config = load_config(config_path)
    logger.info(f"Config loaded: {config_path}")

    from config import get_api_key
    try:
        get_api_key()
        logger.info("API key verified")
    except RuntimeError as e:
        logger.error(str(e)); sys.exit(1)

    data_dir = Path("data")
    data_dir.mkdir(exist_ok=True)
    if not os.access(data_dir, os.W_OK):
        logger.error(f"Data dir not writable: {data_dir.absolute()}"); sys.exit(1)

    get_connection()
    logger.info(f"Database ready: {config.database.path}")

    # Clean up ports before starting
    kill_port(8000)
    kill_port(3001)
    time.sleep(1)

    # Start bridge
    global _bridge_process
    _bridge_process = start_bridge()

    # Monitor bridge in background
    bridge_thread = threading.Thread(target=monitor_bridge, args=(_bridge_process,), daemon=True)
    bridge_thread.start()

    # Wait for bridge to be ready
    logger.info("Waiting for bridge to connect...")
    for _ in range(30):
        if _shutdown_flag.is_set():
            return
        time.sleep(1)
        try:
            import urllib.request
            urllib.request.urlopen("http://127.0.0.1:3001/status", timeout=2)
            logger.info("Bridge is ready")
            break
        except Exception:
            continue

    set_message_handler(handle_incoming_message)

    # Start API server
    import api_server
    api_thread = threading.Thread(target=run_api_server, daemon=True)
    api_thread.start()
    if not api_server._server_started.wait(timeout=10):
        err = api_server._server_error or "API server failed to start"
        logger.error(f"API server failed: {err}"); sys.exit(1)
    logger.info(f"API server on {config.api.host}:{config.api.port}")

    start_scheduler()

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    logger.info("Bot is running. Press Ctrl+C to stop.")
    while not _shutdown_flag.is_set():
        time.sleep(1)


if __name__ == "__main__":
    main()
