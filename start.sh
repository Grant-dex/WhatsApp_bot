#!/bin/bash
cd ~/Desktop/whatsapp-bot
# 杀掉所有残留的 Python bot 进程
pkill -f "python3 src/main.py" 2>/dev/null
sleep 2
# 再清理端口
lsof -ti :8000 | xargs kill -9 2>/dev/null
sleep 1
export NO_PROXY=127.0.0.1,localhost
/opt/homebrew/bin/python3 src/main.py
