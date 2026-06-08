# WhatsApp-Bot 项目速查卡片

外贸 WhatsApp 跟进机器人 — Electron 桌面壳 + Python FastAPI 后端（PyInstaller 编译）+ Node.js/Baileys 桥接 + DeepSeek AI + SQLite。

## 文件索引

| 遇到什么 | 读哪个文件 |
|----------|-----------|
| 一切正常，不知道从哪下手 | `CLAUDE.md`（本文件） |
| 出了 bug / 排查故障 | `桌面/文件整理/WhatsApp-Bot-完整问题手册.md` |
| 想了解当前状态 | `STATUS.md` |
| 快速避坑 / 被同一个坑绊倒两次 | `BUG-EXPERIENCE.md` |
| 查系统架构、端口、运维命令 | 完整问题手册 → 第一节（架构）、第八节（运维） |
| 修改 asar | 完整问题手册 → 8.3 应用更新流程 |
| 修改 Python 后端文件并同步到 app | 看下方 "编译版 vs 源码的同步方式" |

## 硬约束（违反必出事）

1. **JS/正则中绝不直接写不可见 Unicode 字符** — 必须用 `\uXXXX` 转义
2. **不要频繁重启 bridge** — 每次重启可能损坏 WhatsApp 加密 session，停止时用 Ctrl+C 不要 kill -9
3. **asar 热修补后务必清理调试代码再打包** — console.log、window.__xxx、临时计数变量一律删除
4. **修改 Python 源码后必须 cp + zip 同步进 app bundle** — 否则编译版运行的仍是旧代码
5. **`${...}` 只在模板字符串（反引号）内有效** — 裸露的 `${old5}` 类占位符会导致整个 script 块 JS 解析失败
6. **编译版 backend.log 不记录 uvicorn 500 错误** — 排查后端错误需 curl 直接测试或结合源码分析
7. **Bridge 崩溃第一件事跑 `node -c bridge/index.js`** — 不要假设进程会打印有用错误
8. **Electron 不支持浏览器原生 `prompt()`** — 使用自定义模态弹窗（`showEditModal`）
9. **PyInstaller 打包后务必验证 `hiddenimports` 覆盖所有 `from xxx import` 的模块** — 否则运行时 ModuleNotFoundError → 500
10. **`lsof` 端口数量判断组件健康** — 正常应有 4 个端口（filter proxy + port-forwarder + Python backend + Bridge）

## 编译版 vs 源码的同步方式

```
# Python 文件修改后，同步到 app bundle：
cp ~/Desktop/WhatsApp_bot/src/<file>.py \
   ~/Desktop/WhatsApp-机器人.app/Contents/Resources/backend/_internal/
cd ~/Desktop/WhatsApp-机器人.app/Contents/Resources/backend/_internal/
zip base_library.zip <file>.py
pkill -f "WhatsApp-机器人" 2>/dev/null
open ~/Desktop/WhatsApp-机器人.app
```

修改 Bridge：直接编辑 `.app/Contents/Resources/bridge/index.js`。
修改前端注入：解包 `app.asar` → 编辑 `main.js` → 重新打包（见问题手册 8.3）。
