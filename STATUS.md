# WhatsApp-Bot 项目状态

> 最后更新：2026-06-08

## 功能状态

| 模块 | 状态 | 备注 |
|------|------|------|
| Bridge（WhatsApp 连接） | ✅ | 认证正常，send 正常 |
| AI 自动回复（generate_reply） | ✅ | 语言检测已修复（Unicode 字符级） |
| AI 跟进消息（generate_followup） | ✅ | 语言检测 + [Your Name] 修复已生效 |
| 一键批量推送（send-now） | ✅ | 已修复 500 错误（country_utils 漏打包） |
| 手动发送（send-manual） | ✅ | 一直正常 |
| 定时跟进调度（APScheduler） | ⚠️ | 调度器运行中，但上次因 send-now 500 可能积压 |
| 客户管理 / 跟进管理页面 | ✅ | 电话可编辑、名称修改均已修复 |
| PDF 上传 | ⚠️ | PyPDF2 加入 base_library.zip，未重新验证 |
| 客户删除（级联清理） | ✅ | 新增 DELETE /customers/{id}，支持前端一键删除 |
| 前端 JS（导航、搜索等） | ✅ | ${old5} 过滤器已注入 |

## 已知待修复

| 问题 | 来源 | 状态 |
|------|------|------|
| 短消息不回复（debounce 禁用） | 问题 8 | 桌面版待确认是否已修复 |
| 英文消息收到中文回复 | 问题 9 | ✅ 2026-06-08 已根本性修复 |
| AI 回复出现 [Your Name] | 问题 7 | ✅ 2026-06-08 已修复 |
| 399 条姓名当号码 | 问题 23 | 需手动编辑，已导出 Excel |
| 291 个已归档客户无 WhatsApp 号码 | 问题 24 | 等待客户主动发消息时自动捕获 |

## GitHub 信息

| 项目 | 值 |
|------|-----|
| 仓库 | `https://github.com/Grant-dex/WhatsApp_bot` |
| 最新 commit | `d0edffa` — feat: add delete customer functionality with cascade cleanup |
| 分支 | `main` |
| 最近 commits | `d0edffa` / `774b471` / `ac4f33c` / `e86014e` / `32e7de3`（2026-06-08 批量推送修复 + 语言检测 + 文档体系 + 客户删除） |

## 数据状态

| 指标 | 数值 | 日期 |
|------|------|------|
| 客户总数 | 648 | 2026-06-08 |
| 活跃跟进计划 | 247 | 2026-06-08 |
| 暂停跟进计划 | 11 | 2026-06-08 |
| 无效号码（姓名当号码） | 397（369 active + 28 inactive） | 2026-06-08 |
| 无效号码中有跟进计划的 | 60（批量推送会失败） | 2026-06-08 |
| 无效号码中有对话记录的 | 1（其余 396 从未给 bot 发消息） | 2026-06-08 |

## 下次打包/部署检查项

- [ ] 确认所有 spec 文件的 `hiddenimports` 包含 `'country_utils'`（已在 4 个 spec 中添加）
- [ ] 打包后立即测试 `curl -X POST .../admin/api/followups/{id}/send-now`，必须返回 `{"ok":true}`
- [ ] 验证 Bridge 语法：`node -c bridge/index.js`
- [ ] 确认 `lsof` 显示 4 个 WhatsApp 端口
- [ ] 不要忘记同步最新的 `ai_reply.py` 和 `country_utils.py` 到 `base_library.zip`
