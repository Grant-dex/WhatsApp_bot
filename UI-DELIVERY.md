# WhatsApp Bot Web 八页改造交付

本轮在用户提供的 `WhatsApp_bot-web.zip` 上实施，基线为该压缩包（未包含 `.git`、AGENTS.md）。没有修改云端旧 Electron 项目，也没有覆盖用户 Mac 上的文件。交付包需要解压到本地新目录核对后使用。

## 已完成与修改文件

- `design-reference/`：核对八张图内容，去掉目录冒号、乱码文件名和重复扩展名；确认稿规范为 `dashboard-preview.html`。图片本身未改动。
- `src/static/admin.html`：保留 Web SPA 容器与离线 QR 库；引用拆分后的资源；侧栏使用确认稿的 SVG 图标；修复原有暂停图标模板文字外露。
- `src/static/assets/base.css`：保留原有表单、抽屉、批次等完整基础样式。
- `workspace.css`：复用确认稿颜色、字体、尺寸、边框、卡片、表格和响应式规则；去掉彩色图标底座和重阴影。
- `common.js`：公共导航、API、弹窗、客户导入、日期与状态组件。修复编辑回调被清空的问题、导入失败提示及未知 Bridge 状态；增强字符串转义。
- `dashboard.js`：真实指标、活跃客户、跟进日期和发送异常；客户链接打开原有完整详情抽屉；移除演示导航、硬编码日期和样例记录。
- `customers.js`、`conversations.js`、`customers-chat.css`：客户表格与对话双栏，保留搜索、筛选、导入、分页、详情编辑、状态切换、删除、改名和人工发送；处理异步竞争及读取失败。去掉延迟选中客户的定时器，避免覆盖用户刚选中的对话。
- `followups.js`、`followups.css`：自动跟进条、批量控制区、排程表及两栏历史；保留间隔、勾选、确认、覆盖限制、暂停、发送与 unknown 状态；部分模块失败明确提示。
- `orders.js`、`products.js`、`orders-products.css`：订单工具栏与密集表格、完整订单表单、资料上传与编辑删除；失败不显示成功，提交期间阻止重复点击，保留合法零金额。
- `bridge.js`、`bridge-page.js`、`activity.js`：进程、认证与账号分开显示；保留代理保存、二维码及事件读取；二维码消失不再声称认证成功；读取代理配置失败时禁止空白覆盖。
- `setup.js`、`init.js`：保留真实 AI 设置；未配置 Key 时仍可浏览业务管理页，由页头进入配置，不使用伪造 Key。
- `src/api_server.py`：仅新增 `/assets` 静态资源路由；没有公开设计目录、配置或数据库。
- `src/admin_api.py`：异常记录增加 `customer_id` 供详情链接使用；Bridge HTTP/数据格式异常不再误报进程正常。未改变发送配额、去重和调度规则。
- `tests/test_admin_assets.py`、`tests/js/admin-html-syntax.test.js`：适配拆分资源并保持原回归断言，增加资源可访问和设计资料不可访问验证。
- `tests/ui/`：可重复的隔离测试数据、实际浏览器功能检查与截图脚本。
- `run_web.sh`：恢复压缩包丢失的可执行权限，脚本内容不变。
- `README.md`：补充资源结构、测试入口与启动说明。

所有原有具名业务函数均保留；没有新增框架、Electron、PyInstaller、多租户或公网部署流程。

## 实际运行截图

截图为 Chromium 实际打开 FastAPI 后生成，浏览器缩放 100%、deviceScaleFactor=1。使用独立 `data-ui-test` SQLite 测试记录，没有真实客户。Bridge 与调度器均关闭，因此连接状态如实显示离线，不伪造已连接。

| 页面 | 1440×900 实际截图 |
| --- | --- |
| 工作台 | [截图](artifacts/screenshots/dashboard-1440x900.png) |
| 客户管理 | [截图](artifacts/screenshots/customers-1440x900.png) |
| 对话记录 | [截图](artifacts/screenshots/conversations-1440x900.png) |
| 跟进管理 | [截图](artifacts/screenshots/followups-1440x900.png) |
| 订单管理 | [截图](artifacts/screenshots/orders-1440x900.png) |
| 产品资料 | [截图](artifacts/screenshots/product-docs-1440x900.png) |
| 桥接状态 | [截图](artifacts/screenshots/bridge-1440x900.png) |
| 运行日志 | [截图](artifacts/screenshots/activity-1440x900.png) |

同目录还包含每页 1024×768、1280×800、1920×1080 截图，共 32 张。见 [八页总览](artifacts/contact-sheet.jpg) 和 [视口检查结果](artifacts/viewport-results.json)。长页面通过内容区纵向滚动，窄窗口表格可在容器内横向滚动；没有整体缩放网页或隐藏业务操作。

## 验证结果

- 项目自有 `.venv` 依赖安装及 `pip check` 通过。
- `PYTHONPATH=src .venv/bin/python -m unittest discover -s tests -v`：30 项通过，0 失败。
- `node --check bridge/index.js`：通过。
- `node --test bridge/test/*.test.js tests/js/*.test.js`：9 项通过，0 失败。
- 根页面与拆分 CSS/JS 返回正常，无资源 404；设计目录访问 404。
- 八页在四个指定 CSS 视口切换及渲染通过，无页面未处理异常、无文档级横向溢出。
- 实际本地 API 验证：异常记录打开完整客户详情、客户搜索空状态及编辑持久化、浏览器 CSV 导入与清理、文档 CRUD、订单 CRUD 和零金额、暂停状态保存与还原。
- 注入失败验证：仪表盘接口失败不显示正常零值，代理读取失败明确呈现并禁用保存，暂停更新失败恢复原状态。
- 人工发送由浏览器 stub 返回 unknown，验证单次调用和“不自动重试”；现有 Python/Node 可靠性测试覆盖配额、去重、并发、暂停、failed/unknown 与回执。
- 客户/对话/订单/资料恶意文本与四种视口另作 mock 浏览器检查，未执行 HTML 或弹出脚本对话框。

日志见 `artifacts/check-*.log`；功能检查结果见 [functional-results.json](artifacts/functional-results.json)。测试只访问本轮服务和临时测试数据库，不触发真实发送，不读取真实登录态。

## 与原图的主要差异及验证边界

1. 真实数据量、日期、客户和离线状态自然不同于原图。截图数据只在隔离数据库中，生产脚本不包含演示记录、B 标记或演示页脚。
2. 后端没有跟进优先级字段，工作台优先级显示 `—`；不根据客户数量臆造业务优先级。
3. 跟进 API 的待跟进已经是到期记录，所以不伪造原图“待跟进/已逾期”互斥标签；提供真实“待跟进/已暂停”切换并标出逾期情况。
4. 对话接口没有未读数及消息预览字段，显示消息总数，不伪装未读。没有加入后端不支持的附件发送按钮。
5. 资料列表 API 不提供原文件类型，使用统一线性文档图标，不伪造 PDF/XLSX 标签。
6. 为保留既有功能，批量设置、客户操作和订单完整字段继续在抽屉或展开区；页头保留真实配置/刷新入口。窄窗口侧栏折叠并允许区域堆叠。
7. 未验证真实 WhatsApp 扫码、送达、AI 推理及 OCR 模型。这些需要真实凭据/登录态，按本轮约束未启动；二维码与相关交互只作隔离 mock 检查。
8. 本轮浏览器验证使用 Linux Chromium；未在用户 Mac 的 Safari/Chrome 上实测，系统字体可能产生小幅差异。

## 本地启动

解压交付包到新目录，不要直接覆盖现有业务数据。macOS 终端进入该目录：

```bash
chmod +x run_web.sh
./run_web.sh --setup
./run_web.sh --no-scheduler --no-browser --data-dir ./data-ui-test --port 8080
```

浏览器手动打开终端显示的本地地址。初次启动测试目录为空；需要隔离样例时按 `tests/ui/README.md` 运行种子脚本，不能将种子脚本用于业务数据目录。不加 `--with-bridge`。

完整界面不依赖 Node 进程；Node 只用于现有测试或可选 WhatsApp Bridge。交付包不包含本轮 `.venv`、node_modules、测试数据库、凭据或登录态。

## 回退

最安全的方式是在新目录解压本次交付包验证，保留原项目目录不动；需要回退时停止新目录的 Web 服务，重新启动原目录版本即可。若已手动复制修改，请先保存复制后新增的工作，再用最初提供的 `WhatsApp_bot-web.zip` 恢复代码。不要覆盖/删除业务 `data/`、`.env` 或 WhatsApp 登录态。

压缩包没有 Git 历史，无法给出可信的原项目提交 SHA；不能用 `git reset --hard` 代替对已有修改的保护。[变更清单](artifacts/changed-files.json) 可用于逐文件核对。

## 距离公网网址访问还需哪些工作

需要另行配置部署主机和域名、HTTPS、身份认证与访问授权（包括管理 API/文件上传）、网络边界与 Webhook 保护、凭据存储、数据库备份恢复、进程托管和日志监控，再验证持久化、升级和真实 Bridge 连接。当前仅为本地 Web 控制台，本轮没有授权或执行公网部署。
