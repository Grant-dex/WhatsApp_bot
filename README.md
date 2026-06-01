# WhatsApp Bot — AI 驱动的 WhatsApp 销售助手

> 像真人销售一样，在 WhatsApp 上 7x24 小时自动跟进客户、记住偏好、推荐产品。

[![GitHub release](https://img.shields.io/github/v/release/Grant-dex/WhatsApp_bot?color=0F766E)](https://github.com/Grant-dex/WhatsApp_bot/releases)
[![License](https://img.shields.io/badge/license-MIT-green)](LICENSE)

## 下载

| 平台 | 下载 |
|------|------|
| macOS | [下载 DMG](https://github.com/Grant-dex/WhatsApp_bot/releases/latest/download/WhatsApp-Bot-macOS.dmg) |
| Windows | [下载安装包](https://github.com/Grant-dex/WhatsApp_bot/releases/latest/download/WhatsApp-Bot-Windows-Setup.exe) |

> 也可以前往 [Releases 页面](https://github.com/Grant-dex/WhatsApp_bot/releases) 查看所有历史版本。

---

## 这是什么？

一款开箱即用的 **WhatsApp AI 销售机器人**，安装到电脑上，扫码登录 WhatsApp，就能自动帮你：

- 7x24 小时智能回复客户消息
- 像真人销售一样自然对话，不是冷冰冰的客服机器人
- 自动记住每位客户的偏好和聊过的话题
- 定时跟进潜在客户，不会让任何一个商机溜走
- 管理客户信息、产品资料、订单状态

本质上是给 WhatsApp 接上一个 AI 大脑，让它在你不看手机的时候，也能像你最靠谱的销售同事一样工作。

---

## 核心功能

### AI 智能回复

接入了 DeepSeek / OpenAI 兼容的大模型，自动回复客户的 WhatsApp 消息：

- **口语化聊天风格** — 不是机器人客服那种"您好，请问有什么可以帮您"的模板话术，而是像真人销售在 WhatsApp 上聊天一样自然、有温度
- **多语言自动切换** — 客户用什么语言发消息，AI 就用什么语言回复（支持中文、英文、俄语、阿拉伯语等）
- **产品知识库驱动** — 上传你的产品参数文档（PDF、Word、Excel、图片），AI 会基于真实数据回复，不会胡编乱造
- **智能追问推进** — 每次回复都会自然引导下一步：了解需求 → 推荐机型 → 发选型表 → 安排通话
- **反骚扰保护** — 对 "ok"、"好的"、"谢谢" 等终结性消息不回复，不打扰客户

### 客户管理

- **Excel 一键导入** — 支持 `.xlsx` / `.csv` 批量导入客户，自动识别姓名、电话、公司等列
- **智能字段解析** — 支持带 `N:/E:/M:` 标记的客户信息列，兼容主流 CRM 导出格式
- **客户标签与状态** — 标记活跃/沉默/已成交/已拉黑，分类管理
- **对话历史** — 每位客户的完整聊天记录，随时回溯
- **客户记忆** — AI 自动记录客户关心的话题（问过功率、问过价格、对某个品牌感兴趣等），下次聊天时自动带上历史上下文

### 智能跟进

- **自动排程** — 每位新客户自动纳入 7 天跟进计划，无需手动设置
- **AI 生成跟进消息** — 不是群发模板，而是针对每位客户的偏好、国家、行业自动生成个性化跟进文案
- **国家感知** — 自动识别客户手机号所属国家（覆盖全球 60+ 国家/地区），结合当地电力市场情况生成更有针对性的内容。比如：
  - 南非客户 → 提到 "load shedding" 缺电问题
  - 尼日利亚客户 → 提到油气田现场的可靠供电需求
  - 德国客户 → 提到能源转型和沼气发电
- **跟进控制台** — 查看今日待跟进、已发送、发送失败的跟进消息，支持手动触发
- **防骚扰机制** — 每次回复后有冷却时间，每小时有自动回复上限，不会对同一客户频繁轰炸

### 产品知识库

- **多格式上传** — 支持 PDF、Word (.docx)、Excel (.xlsx/.xls)、CSV、TXT、Markdown，甚至直接上传图片
- **OCR 文字识别** — 即使上传的是扫描版 PDF 或手机拍的产品参数图，也能自动 OCR 提取文字
- **AI 实时检索** — 客户问到产品参数时，AI 会搜索知识库中的真实数据来回复，不会编造
- **在线编辑** — 可以在管理后台直接编辑知识库内容

### 订单管理

- 创建订单 → 确认 → 生产中 → 发货 → 已交付 → 已取消，完整订单流程
- 自动生成订单编号（格式：TP + 日期 + 序号）
- 订单关联客户，一站式查看客户的所有订单
- 支持多币种

### 后台管理面板

内置 Web 管理后台，通过桌面应用打开：

- **Dashboard 仪表盘** — 客户总数、今日 AI 回复数、待跟进数、桥接状态一目了然
- **实时活动日志** — 实时查看每一通对话和系统事件
- **一键暂停/恢复** — 需要人工介入时，点一下就能暂停 AI 自动回复，不会对客户乱发消息
- **代理支持** — 内置 HTTP 代理配置，方便在需要网络加速的地区使用

### 桌面应用体验

- **Mac & Windows 原生安装包** — 下载 DMG 或 EXE，双击安装，像普通软件一样使用
- **自带 Python 后端** — 不需要装 Python 环境，安装包里已经包含所有依赖
- **崩溃自动重启** — 后端或 Bridge 挂了会自动拉起来，不用手动干预
- **本地数据存储** — 所有客户数据、聊天记录都存在本地 SQLite，不上传云端

---

## 适用场景

- 外贸 SOHO / 跨境电商卖家用 WhatsApp 跟客户沟通
- B2B 工业品销售（发电机、机械设备、建材等），客户咨询需要专业参数回复
- 有大量重复咨询问题的商家，让 AI 先过滤一轮再人工接手
- 跨时区业务，睡觉时 AI 帮你回复欧美客户

---

## 快速开始

### 下载安装包（推荐）

从上方下载链接获取对应平台的安装包，安装后直接运行即可。

第一次启动会引导配置 AI API Key，填入后扫码登录 WhatsApp 即可使用。

> 支持 DeepSeek API（推荐，便宜好用）或任何 OpenAI 兼容接口。

### 从源码运行

**前置要求：** Python 3.12+、Node.js 20+

```bash
git clone https://github.com/Grant-dex/WhatsApp_bot.git
cd WhatsApp_bot

# 1. 安装 Python 依赖
pip install -r requirements.txt

# 2. 配置 API Key
cp .env.example .env
# 编辑 .env，填入 LLM_API_KEY=你的key

# 3. 启动完整服务（后端 + Bridge + 管理后台）
python src/main.py

# 4. 启动桌面客户端（可选，也可以用浏览器打开管理后台）
cd desktop
npm install && npm start
```

---

## 配置说明

编辑 `config.yaml` 可以调整所有参数：

```yaml
ai:
  provider: openai_compatible   # AI 接口类型
  model: deepseek-chat         # 模型名称
  base_url: https://api.deepseek.com  # API 地址
  reply_cooldown_minutes: 1    # 同一客户两次回复最小间隔（分钟）
  reply_max_length: 800        # AI 回复最大字数

business:
  quiet_hours_start: 21        # 静音时段开始（晚9点）
  quiet_hours_end: 8           # 静音时段结束（早8点）
  max_auto_replies_per_hour: 30  # 每小时最大自动回复数
```

---

## 技术栈

| 模块 | 技术 |
|------|------|
| 桌面客户端 | Electron |
| 后端 API | Python FastAPI |
| AI 引擎 | OpenAI 兼容接口 (DeepSeek / GPT 等) |
| WhatsApp 桥接 | Node.js + whatsapp-web.js |
| 数据库 | SQLite (本地存储) |
| OCR | RapidOCR + PyMuPDF |
| 打包 | PyInstaller + electron-builder |

---

## 开发计划

- [ ] 支持多 WhatsApp 账号同时在线
- [ ] 消息模板系统
- [ ] 数据分析与导出报表
- [ ] 多语言管理后台界面
- [ ] 自动翻译（客户发任意语言，AI 翻译后回复）
- [ ] Telegram / Line 多平台扩展

---

## License

MIT
