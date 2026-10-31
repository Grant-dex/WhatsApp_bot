#!/usr/bin/env bash
# 启动网页版控制台（不需要 Electron、不需要打包）。
#
#   ./run_web.sh                      # http://127.0.0.1:8000
#   ./run_web.sh --port 8080
#   ./run_web.sh --host 0.0.0.0       # 手机也能访问（同一局域网）
#   ./run_web.sh --with-bridge        # 同时连 WhatsApp
#
# 首次使用请先执行：./run_web.sh --setup
# 可选 OCR： .venv/bin/pip install -r requirements-ocr.txt
set -euo pipefail
cd "$(dirname "$0")"

VENV=".venv"
PY="$VENV/bin/python"

if [[ "${1:-}" == "--setup" ]]; then
  echo "==> 创建虚拟环境 $VENV"
  python3 -m venv "$VENV"
  echo "==> 安装网页版依赖"
  "$VENV/bin/python" -m pip install --upgrade pip
  "$VENV/bin/python" -m pip install -r requirements.txt
  echo
  echo "完成。现在运行： ./run_web.sh"
  exit 0
fi

if [[ ! -x "$PY" ]]; then
  echo "未找到 $VENV。请先执行：" >&2
  echo "    ./run_web.sh --setup" >&2
  exit 1
fi

exec "$PY" src/web_main.py "$@"
