# WhatsApp Bot

AI 驱动的 WhatsApp 商务助手桌面应用，支持自动回复、客户管理、多平台运行。

## 下载

| 平台 | 下载 |
|------|------|
| macOS | [下载 DMG](https://github.com/Grant-dex/WhatsApp_bot/releases/latest/download/WhatsApp-Bot-macOS.dmg) |
| Windows | [下载安装包](https://github.com/Grant-dex/WhatsApp_bot/releases/latest/download/WhatsApp-Bot-Windows-Setup.exe) |

> 也可以前往 [Releases 页面](https://github.com/Grant-dex/WhatsApp_bot/releases) 查看所有版本。

## 功能特性

- AI 自动回复客户消息
- 客户信息管理（Excel 导入导出）
- 定时跟进提醒
- 工作时间静音模式
- 多平台支持（macOS / Windows）

## 安装与运行

### 下载安装包（推荐）

从上方下载链接获取对应平台的安装包，安装后直接运行即可。

### 从源码运行

**前置要求：**
- Python 3.12+
- Node.js 20+

```bash
# 1. 克隆仓库
git clone https://github.com/Grant-dex/WhatsApp_bot.git
cd WhatsApp_bot

# 2. 安装 Python 依赖
pip install -r requirements.txt

# 3. 配置
cp .env.example .env
# 编辑 .env 文件，填写你的 API Key 等配置

# 4. 启动后端
python src/main.py

# 5. 启动桌面客户端（另一个终端）
cd desktop
npm install
npm start
```

## 配置

编辑 `config.yaml` 配置文件：

- `business` — 商家信息、静音时段、回复频率限制
- `ai` — AI 模型配置（支持 OpenAI 兼容接口）
- `scheduler` — 跟进检查间隔
- `bridge` — WhatsApp 桥接配置

## 技术栈

- **桌面端：** Electron
- **后端：** Python FastAPI
- **AI：** OpenAI 兼容接口（DeepSeek 等）
- **打包：** PyInstaller + electron-builder
