# WhatsApp Bot — 网页版

这是从原 Electron 桌面版精简出的**网页端**版本，保留 Python 后端、Web 管理台、WhatsApp Bridge、跟进调度和发送可靠性机制；已移除 Electron 桌面壳、PyInstaller 打包和安装包构建。

原桌面版仍保留在 `~/Desktop/ai应用工程师项目/WhatsApp_bot-main`，可随时回滚。

## 快速开始

```bash
cd ~/Desktop/ai应用工程师项目/WhatsApp_bot-web

# 首次安装网页版依赖
./run_web.sh --setup

# 启动网页控制台
./run_web.sh
```

浏览器打开：`http://127.0.0.1:8000`。

默认数据目录是项目下的 `data/`；`run_web.sh` 会自动创建 `config.yaml` 副本和 SQLite 数据库。API Key 写入 `data/.env` 或通过首次配置页保存。

## 连接 WhatsApp（可选）

网页控制台本身不依赖 Electron。需要收发 WhatsApp 时：

```bash
cd ~/Desktop/ai应用工程师项目/WhatsApp_bot-web
npm --prefix bridge install   # 首次一次
./run_web.sh --with-bridge
```

然后在「桥接状态」页扫码登录。没有配置 Bridge 时，网页控制台仍可查看客户、订单、资料和日志。

## 常用参数

```bash
./run_web.sh --port 8080          # 换端口
./run_web.sh --host 0.0.0.0       # 允许局域网访问（注意安全）
./run_web.sh --no-scheduler       # 只开网页，不跑自动跟进调度
./run_web.sh --with-bridge        # 同时启动 Node WhatsApp Bridge
./run_web.sh --no-browser         # 不自动打开浏览器
```

## 可选 OCR

精简依赖默认不含 OCR。需要上传扫描版 PDF/图片时：

```bash
.venv/bin/pip install -r requirements-ocr.txt
```

普通 PDF/Word/Excel/CSV/TXT 文本读取已包含在 `requirements.txt`。

## 测试

```bash
PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v
node --check bridge/index.js
node --test bridge/test/*.test.js tests/js/*.test.js
```

## 网页版结构

- `src/web_main.py`：网页版启动入口
- `src/api_server.py` + `src/admin_api.py`：FastAPI 与后台 API
- `src/static/admin.html`：管理控制台
- `src/database.py`、`src/send_service.py`、`src/scheduler.py`：数据、发送、调度
- `bridge/`：WhatsApp Node Bridge（可选运行）
- `run_web.sh` / `requirements.txt`：网页版启动与依赖
- `tests/`：Python 与 Node 回归测试

## 安全与回滚

- 默认只监听 `127.0.0.1`；不要在没有认证/防火墙保护时使用 `--host 0.0.0.0`。
- 不连接真实 WhatsApp、不执行真实发送前，建议加 `--no-scheduler` 并使用测试数据库。
- 原桌面项目未改动：`~/Desktop/ai应用工程师项目/WhatsApp_bot-main`。
- 停止网页版：运行 `run_web.sh` 的终端按 `Ctrl+C`。


## 八页界面与隔离验收

管理台沿用原生 HTML/CSS/JavaScript。公共样式与页面脚本位于 `src/static/assets/`，仅该资源目录通过 `/assets` 提供；`design-reference/` 不对外公开。八页设计参考已规范命名，确认稿为 `design-reference/dashboard-preview.html`。

```bash
# 首次准备依赖
./run_web.sh --setup
# 隔离测试；不启动 WhatsApp Bridge，也不启动调度器
./run_web.sh --no-scheduler --no-browser --data-dir ./data-ui-test --port 8080
```

缺少 AI Key 时仍可查看管理台，右上角“配置 AI”进入原有设置流程；实际 AI 回复仍需要有效凭据。未连接 Bridge 时会如实显示离线与认证未知，不会显示已连接。

浏览器截图与隔离验证方式见 `tests/ui/README.md`；本轮改动、验收结果、差异及回退说明见 `UI-DELIVERY.md`。发布到互联网前需要另外完成认证授权、HTTPS、网络边界、凭据管理、数据备份与运行监控，本轮没有部署。
