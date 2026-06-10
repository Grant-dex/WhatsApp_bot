# WhatsApp-Bot 项目状态

> 最后更新：2026-06-10

## 功能状态

| 模块 | 状态 | 备注 |
|------|------|------|
| Bridge（WhatsApp 连接） | ✅ | 认证正常，send 正常，正则已改用 `\uXXXX` 安全转义 |
| AI 自动回复（generate_reply） | ✅ | 语言检测已修复（Unicode 字符级） |
| AI 跟进消息（generate_followup） | ✅ | 语言检测 + [Your Name] + country_utils 重写（去 phonenumbers）均已修复 |
| Bridge 层跟进消息模板转换 | ✅ | 7 套多样化模板 + first name 提取 + 电话哈希分配，桥接层拦截硬编码模板 |
| 一键批量推送（send-now） | ✅ | 已根本性修复：重写 country_utils.py 移除 phonenumbers 第三方依赖，改用内置 ITU 区号映射表 |
| 手动发送（send-manual） | ✅ | 一直正常 |
| 定时跟进调度（APScheduler） | ✅ | 调度器运行中，前期积压的 10 条逾期跟进已消化 |
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
| 客户总数 | 646 | 2026-06-09 |
| 活跃跟进计划 | 247 | 2026-06-08 |
| 暂停跟进计划 | 11 | 2026-06-08 |
| 无效号码（姓名当号码） | 354 | 2026-06-09 |
| ├─ 可安全删除（无对话记录） | 343 | 2026-06-09 |
| ├─ 有对话记录 | 11 | 2026-06-09 |
| └─ 有活跃跟进计划 | 38 | 2026-06-09 |

## 下次打包/部署检查项

- [ ] 确认所有 spec 文件的 `hiddenimports` 包含 `'country_utils'`、`'PyPDF2'`、`'fitz'`、`'rapidocr'`、`'cv2'`、`'numpy'`、`'onnxruntime'`、`'docx'`、`'openpyxl'`、`'xlrd'`、`'python_multipart'`（已在 3 个 spec 中添加）
- [ ] 打包后立即测试 `curl -X POST .../admin/api/followups/{id}/send-now`，必须返回 `{"ok":true}`
- [ ] 打包后确认 `phonenumbers` 未被打包（`country_utils.py` 已不再依赖它）
- [ ] 打包后测试 PDF 上传：`curl -X POST .../admin/api/product-docs/upload -F "files=@test.pdf"`
- [ ] 验证 Bridge 语法：`node -c bridge/index.js`
- [ ] 确认 Bridge 正使用 `\uXXXX` 转义（`grep 'u200B' bridge/index.js` 应有输出）
- [ ] 确认 `lsof` 显示 3~4 个 WhatsApp 相关端口
- [ ] 同步最新 `ai_reply.py`、`country_utils.py`、`admin_api.py` 到 `base_library.zip`
- [ ] 确认 openpyxl numpy 兼容补丁已应用（`compat/numbers.py` 使用 `getattr` 模式）
