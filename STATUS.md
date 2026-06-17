# WhatsApp-Bot 项目状态

> 最后更新：2026-06-17

## 功能状态

| 模块 | 状态 | 备注 |
|------|------|------|
| Bridge（WhatsApp 连接） | ✅ | 认证正常，send 正常，正则已改用 `\uXXXX` 安全转义 |
| AI 自动回复（generate_reply） | ✅ | 2026-06-17 根治中文回复问题：system prompt 英文化 + 短消息兜底英文 + fallback 英文化 |
| AI 跟进消息（generate_followup） | ✅ | 语言检测 + [Your Name] + country_utils 重写（去 phonenumbers）均已修复 |
| Bridge 层跟进消息模板转换 | ✅ | 7 套多样化模板 + first name 提取 + 电话哈希分配，桥接层拦截硬编码模板 |
| 一键批量推送（send-now） | ✅ | 已根本性修复：重写 country_utils.py 移除 phonenumbers 第三方依赖，改用内置 ITU 区号映射表 |
| 手动发送（send-manual） | ✅ | 一直正常 |
| 定时跟进调度（APScheduler） | ✅ | 每 5 分钟检查 + 每日 10:00 自动批量推送，已加入每日 40 条上限 |
| 每日跟进上限控制 | ✅ | `max_auto_replies_per_day: 40`，`check_followups()` 和 `auto_batch_push()` 均强制执行 |
| 客户管理 / 跟进管理页面 | ✅ | 电话可编辑、名称修改均已修复 |
| 无效号码检测与清理 | ✅ | 新增 API 端点（detect_only / delete_safe / mark_inactive）+ 独立 SQL 脚本 |
| PDF 上传 | ✅ | PyPDF2 + openpyxl（numpy 2.x 兼容补丁）+ xlrd 均已打包验证 |
| 客户删除（级联清理） | ✅ | 新增 DELETE /customers/{id}，支持前端一键删除 |
| 客户编辑智能合并 | ✅ | 修改手机号遇重复时自动合并关联数据，删除旧记录 |
| 前端 JS（导航、搜索等） | ✅ | ${old5} 过滤器已注入，保存失败显示具体中文错误原因 |
| config.yaml | ✅ | company_name 已改为 "Tide Power" |

## 已知待修复

| 问题 | 来源 | 状态 |
|------|------|------|
| 短消息不回复（debounce 禁用） | 问题 8 | 桌面版待确认是否已修复 |
| 354 条姓名当号码 | 问题 23 | 可通过 API 批量清理：343 条可安全删除（无对话），11 条有对话记录需标记 inactive |
| 291 个已归档客户无 WhatsApp 号码 | 问题 24 | 等待客户主动发消息时自动捕获 |
| ~~AI 用中文回复非中文客户~~ | 2026-06-17 | ✅ 已修复（见下方） |

## 最近重要修改（2026-06-17）

| 修改 | 文件 | 说明 |
|------|------|------|
| System prompt 英文化 | `src/ai_reply.py` | `_build_system_prompt()` 全英文重写，消除 DeepSeek 的中文偏向；新增 "For short messages default to ENGLISH" 规则 |
| 短消息兜底英文指令 | `src/ai_reply.py` | `generate_reply()` 中 `detected_lang` 为空时，显式注入 "Default to English for this reply" |
| Fallback 回复英文化 | `src/ai_reply.py` | `_fallback_reply()` 三句兜底全改英文：Hi 问候 / 问号-技术确认 / 通用确认 |
| 编译版同步 | `base_library.zip` | `ai_reply.py` 已于 6/17 同步至编译版 app |

### 根因
DeepSeek 看到全中文 system prompt 会偏向中文输出。即使 prompt 中写了"跟着客户语言走"，短消息（如 "Hi"、"OK"）无法可靠检测语言时，AI 默认跟了 system prompt 的中文。加上 API 调用失败时的兜底回复也是硬编码中文，形成三重中文倾向。

### 修复策略
三管齐下消除中文默认倾向：
1. System prompt 全英文 — 消除 LLM 的语言偏向源
2. 短消息无法检测语言时，显式注入英文指令 — 不再留空让 AI 自由发挥
3. Fallback 回复英文化 — 极端情况下也不发中文

## 最近重要修改（2026-06-16）

| 修改 | 文件 | 说明 |
|------|------|------|
| 每日跟进上限功能 | `src/config.py` | 新增 `max_auto_replies_per_day: int = 40`（Pydantic 默认值） |
| 每日跟进上限逻辑 | `src/scheduler.py` | 新增 `_count_today_auto_sent()` 函数，`check_followups()` 和 `auto_batch_push()` 中增加每日配额检查，超出后自动跳过 |
| 运行时配置补全 | `~/Library/Application Support/whatsapp-bot/config.yaml` | 写入 `max_auto_replies_per_day: 40`，消除 Pydantic 默认值兜底隐患 |
| 跟进计划全量覆盖 | 数据库 | 643 个活跃客户全部纳入跟进计划，统一 16 天周期，均匀分配到每天 ~40 人 |
| 编译版同步 | `base_library.zip` | `config.py` + `scheduler.py` 已于 6/15 14:30 同步至编译版 app |

### 排查过程关键发现

- **6/15 之前编译版 app 无每日限制**：`scheduler.py` 和 `config.py` 中每日上限功能仅存在于未提交更改，编译版 `base_library.zip` 在 6/15 14:30 才同步
- **6/15 当天发送了 95 条（84 成功 + 11 失败）**：旧代码对所有到期客户无差别发送，远超 40 上限
- **6/16 起正常运行**：今日已发 4 条，上限生效中
- **编译版日志缺失**：`backend_launcher.py` 未配置 Python logging，调度器的 INFO 日志（限制命中、发送统计等）无法写入 `backend.log`，待后续修复

## 未提交更改（需择机 commit）

| 文件 | 更改内容 |
|------|---------|
| `src/ai_reply.py` | System prompt 英文化 + 短消息兜底英文 + Fallback 英文化 |
| `src/config.py` | +`max_auto_replies_per_day: int = 40` |
| `src/scheduler.py` | +`_count_today_auto_sent()` + 两处 `daily_limit` 检查逻辑 + `from database import get_connection` |
| `src/admin_api.py` | 客户编辑智能合并逻辑 |
| `src/database.py` | UNIQUE 约束处理 + 显式 IntegrityError 上抛 |
| `bridge/index.js` | transformFollowupMessage() + 7 套模板 + first name 提取 |
| `config.yaml` | +`max_auto_replies_per_day: 40` |
| `BUG-EXPERIENCE.md` | 新增 AI 中文回复 System Prompt 语言污染坑 |
| `STATUS.md` | 2026-06-17 修改记录更新 |

## GitHub 信息

| 项目 | 值 |
|------|-----|
| 仓库 | `https://github.com/Grant-dex/WhatsApp_bot` |
| 最新 commit | `0fc2fc7` — feat: 客户编辑时智能合并重复号码 + 前端错误提示优化 |
| 分支 | `main` |

## 最近重要修改（2026-06-10）

| 修改 | 文件 | 说明 |
|------|------|------|
| 客户编辑智能合并 | `src/admin_api.py` | 编辑客户手机号遇 UNIQUE 冲突时，自动将旧记录下的对话/跟进/订单合并到当前客户，删除重复记录 |
| 数据库 UNIQUE 约束处理 | `src/database.py` | 显式捕获 sqlite3.IntegrityError 并上抛，供 API 层做合并处理 |
| 前端错误提示优化 | `src/static/admin.html` | 保存失败显示具体中文错误原因，清理 `${old5}` 模板残留 |

## 最近重要修改（2026-06-09）

| 修改 | 文件 | 说明 |
|------|------|------|
| country_utils 重写 | `src/country_utils.py` | 移除 phonenumbers 依赖，改用纯 Python ITU E.164 区号映射表（200+ 国家），API 完全兼容 |
| Bridge 模板多样化 | `bridge/index.js` | 新增 transformFollowupMessage() + 7 套模板 + first name 提取，按电话哈希分配 |
| Bridge Unicode 安全 | `bridge/index.js`（源码+编译版） | 电话清理正则改用 `\uXXXX` 转义，防止不可见字符导致 JS 语法错误 |
| 无效号码管理 | `src/admin_api.py` | 新增 GET /customers/invalid-phones + POST /customers/cleanup-invalid-phones |
| 无效号码清理脚本 | `scripts/cleanup_invalid_phones.sql` | 独立 SQL 脚本，可检测和批量清理 |
| PDF/Excel 模块补充 | 编译版 `_internal/` | 复制 PyPDF2、openpyxl（numpy 2.x 兼容补丁）、xlrd 到编译版 |
| spec hiddenimports 完善 | 3 个 spec 文件 | 统一添加 PyPDF2/fitz/rapidocr/cv2/numpy/onnxruntime/docx/openpyxl/xlrd/country_utils 等 17 项 |
| openpyxl numpy 兼容 | `openpyxl/compat/numbers.py` | 用 getattr 安全获取 numpy 类型，兼容 numpy 2.x（numpy.short 等已移除） |
| config 修复 | `config.yaml` | company_name: "Tide Power" |

## 数据状态

| 指标 | 数值 | 日期 |
|------|------|------|
| 客户总数 | 643（活跃） | 2026-06-16 |
| 活跃跟进计划 | 645 | 2026-06-16 |
| 跟进周期 | 16 天 | 2026-06-16 |
| 每日平均到期 | ~40 人 | 2026-06-16 |
| 每日发送上限 | 40 条 | 2026-06-16 |
| 无效号码（姓名当号码） | 354 | 2026-06-09 |
| ├─ 可安全删除（无对话记录） | 343 | 2026-06-09 |
| ├─ 有对话记录 | 11 | 2026-06-09 |
| └─ 有活跃跟进计划 | 38 | 2026-06-09 |

## 下次打包/部署检查项

- [ ] **同步 `config.py` 和 `scheduler.py` 到编译版**：`cp src/config.py src/scheduler.py → _internal/ → zip base_library.zip`
- [ ] 重启后验证每日限制生效：Dashboard 中 `today_ai_replies` 应不超过 40
- [ ] 确认所有 spec 文件的 `hiddenimports` 包含 `'country_utils'`、`'PyPDF2'`、`'fitz'`、`'rapidocr'`、`'cv2'`、`'numpy'`、`'onnxruntime'`、`'docx'`、`'openpyxl'`、`'xlrd'`、`'python_multipart'`（已在 3 个 spec 中添加）
- [ ] 打包后立即测试 `curl -X POST .../admin/api/followups/{id}/send-now`，必须返回 `{"ok":true}`
- [ ] 打包后确认 `phonenumbers` 未被打包（`country_utils.py` 已不再依赖它）
- [ ] 打包后测试 PDF 上传：`curl -X POST .../admin/api/product-docs/upload -F "files=@test.pdf"`
- [ ] 验证 Bridge 语法：`node -c bridge/index.js`
- [ ] 确认 Bridge 正使用 `\uXXXX` 转义（`grep 'u200B' bridge/index.js` 应有输出）
- [ ] 确认 `lsof` 显示 3~4 个 WhatsApp 相关端口
- [ ] 确认 openpyxl numpy 兼容补丁已应用（`compat/numbers.py` 使用 `getattr` 模式）
- [ ] 编译版 `backend_launcher.py` 建议补充 `setup_logging()` 调用，使调度器日志可见
