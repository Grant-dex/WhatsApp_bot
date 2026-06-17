# BUG-EXPERIENCE — WhatsApp-Bot 踩坑经验库

> 只记录反直觉的、容易重复踩的坑。完整排查流程见 `桌面/文件整理/WhatsApp-Bot-完整问题手册.md`。

---

## Bridge

**【坑】Bridge 启动即崩溃，无有用错误信息**
→ 根因：JS 源码中混入了不可见 Unicode 控制字符（U+200B、U+202A 等），正则字面量解析失败 → `SyntaxError: missing /`
→ 正确做法：永远用 `\uXXXX` 转义写 Unicode；崩溃第一步跑 `node -c bridge/index.js`
> ⚡ Claude 曾误判为网络/代理问题，浪费 2 小时。

**【坑】Bridge 显示 `authenticated: true` 但消息发不出去（"幽灵连接"）**
→ 根因：WhatsApp Web 协议会话过期，加密 session 损坏
→ 正确做法：删 `data/.baileys-auth` 重新扫码；**不要频繁重启 bridge**（每次重启都可能损坏 session）

---

## Python 后端 & AI

**【坑】AI 对非中文客户回复中文 — System Prompt 语言污染**
→ 现象：机器人用中文回复只说 "Hi"、"OK" 的客户（以及偶尔对正常英文对话突然切中文）
→ 根因：三重中文倾向叠加：
  1. `_build_system_prompt()` 整个 system prompt 是中文写的 → DeepSeek 看到中文 prompt 偏向中文输出
  2. 客户消息太短（"Hi"、"Thanks"）时 `_detect_message_language()` 返回空字符串 → 不加语言指令 → AI 自由发挥回中文
  3. API 调用失败时 `_fallback_reply()` 三句兜底全硬编码中文（"你好！有什么可以帮你的吗？" 等）
→ 正确做法：(1) System prompt 改英文 (2) `detected_lang` 为空时显式注入 "Default to English" (3) Fallback 回复英文化
> ⚡ 直觉会以为只要 prompt 里写一句"跟着客户语言走"就够了，但 LLM 的语言偏向主要由 system prompt 的语言决定，不是由 instruction 内容决定。短消息场景下这个偏向会被放大。

**【坑】`send-now` 返回 500 Internal Server Error，但 `send-manual` 正常，backend.log 无任何错误**
→ 根因：PyInstaller 未打包 `country_utils.py`（且其依赖 `phonenumbers` 库也未打包）→ `from country_utils import ...` ModuleNotFoundError → 未捕获异常 → 500
→ 正确做法：(1) 重写模块去掉第三方依赖 (2) 手动 cp + `zip base_library.zip` 同步进 app (3) spec 的 `hiddenimports` 加 `'country_utils'`
> ⚡ Claude 曾误判为号码格式问题，逐个测试后才定位到 module missing。

**【坑】编译版后端进程工作目录是 `/`（根目录），不是源码目录**
→ 根因：Electron `spawn()` 继承的 cwd 为 `/`
→ 后果：所有相对路径（`.env`、`config.yaml`、`*.py` 模块）全部解析失败
→ 正确做法：后端通过 `WHATSAPP_BOT_DATA_DIR` 环境变量找数据目录；修改文件用绝对路径 cp + zip

**【坑】AI 给阿拉伯客户发中文回复**
→ 根因：`generate_followup` 的 prompt 只写了 "Match the customer's language"，AI 在有中文 system prompt 干扰下随机选语言
→ 正确做法：通过电话号码国家前缀 → `_country_to_language()` 映射 → prompt 中明确 "You MUST write this message in Arabic"
> ⚡ 直觉会以为是 prompt 语言问题（换成英文 prompt 就好），但根本原因是缺少显式语言约束。

**【坑】`generate_reply` 对短消息（如 "hi"）误判语言**
→ 根因：system prompt 是中文的，短消息没有足够字符让 AI 判断语言，AI 默认跟了 system prompt 的语言
→ 正确做法：Unicode 字符范围检测（`_detect_message_language`）→ 显式注入 "You MUST reply in English"

**【坑】AI 回复出现 `[Your Name]` 占位符**
→ 根因：prompt 没有传销售员姓名，AI 自行生成了占位符
→ 正确做法：prompt 中显式写入 `{cfg.business.owner_name}`，加禁止占位符的约束

---

## Electron / asar

**【坑】点击所有页面导航都没反应，但 curl API 全部正常**
→ 根因：编译版 `admin.html` 中残留了一个裸露的 `${old5}` 占位符（不在模板字符串内），整个 `<script>` 块 JS 解析失败
→ 正确做法：在 Electron 主进程加 filter proxy 过滤 `${old5}`；永远不要在 JS 源码中留未替换的 `${...}` 占位符
> ⚡ 极难定位：API 全正常，前端看着也渲染了，但所有 onclick 都失效。最终通过 Electron 远程调试 `typeof navigate` 发现 undefined。

**【坑】Electron 不支持浏览器原生 `prompt()` 弹窗**
→ 根因：Electron 没有 blocking dialog API
→ 正确做法：自定义模态弹窗（`showEditModal`）

**【坑】macOS Dock 点击导致 app 多次启动，互相打架**
→ 根因：`app.on('activate', ...)` 在 `app.whenReady()` 回调**外部**注册，无防重入锁
→ 正确做法：activate 事件注册移入 whenReady 回调内，加 `creatingWindow` 锁

---

## 前端

**【坑】搜索框输入一个字符后焦点丢失**
→ 根因：`loadCustomers()` 每次 `oninput` 都用 `el.innerHTML = ...` 重建整个 DOM，搜索框被销毁重建
→ 正确做法：搜索框持久化 DOM（`id="cust-search-input"`），`loadCustomers()` 只更新表格 body

---

## 数据

**【坑】电话号码末尾带 `+`、被不可见 Unicode 包裹、甚至存的是人名**
→ 根因：WhatsApp 原始数据未清理直接入库
→ 正确做法：(1) SQL `TRIM(phone, '+')` (2) Unicode 清理正则 (3) 前端红色删除线标记无效号码，可手动编辑

---

## PyInstaller 打包

**【坑】本地跑得好好的，打包后 ModuleNotFoundError → 500**
→ 根因：PyInstaller 的自动依赖分析检测不到某些 `from xxx import`（特别是新增模块或间接依赖的第三方库）
→ 正确做法：(1) spec 的 `hiddenimports` 显式列出所有源模块 (2) 打包后立即 curl 测试关键接口 (3) 如需热修复：cp 文件到 `_internal/` + `zip base_library.zip`
> ⚡ 重复踩坑：PDF 上传（PyPDF2 漏打包）和批量推送（country_utils 漏打包）是同一类问题。

**【坑】`base_library.zip` 更新后不生效**
→ 根因：PyInstaller 优先级 — `_internal/` 目录下的独立 .py 文件 > `base_library.zip` 内的
→ 正确做法：同步文件时执行 `cp <file>.py _internal/ && cd _internal && zip base_library.zip <file>.py`，两步都要做
