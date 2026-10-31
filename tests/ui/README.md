# 隔离浏览器验证

这些脚本只针对本机 8080 的隔离 UI 测试服务，不能用于生产站点。

1. 使用 `./run_web.sh --no-scheduler --no-browser --data-dir ./data-ui-test --port 8080` 启动服务；不加 `--with-bridge`。
2. 空数据库运行 `python tests/ui/seed_fixture.py`。该脚本只写项目下 `data-ui-test/data/customers.db`，要求客户表为空，不覆盖已有客户。测试数据包含虚构号码和 `example.invalid` 邮箱。
3. 安装可选的浏览器验证工具：`python -m pip install playwright`，再 `python -m playwright install chromium`。Linux 若已有 `/usr/bin/chromium`，脚本会优先使用它；其他系统使用 Playwright 自带浏览器。
4. `python tests/ui/functional.py`：真实本地客户/文档/订单 CRUD、暂停切换与还原、失败状态；所有发送请求被 stub 为 unknown，不发生真实发送。
5. `python tests/ui/capture.py`：八页 × 四种 CSS 视口，deviceScaleFactor=1，无页面缩放；截图与检查结果写入 `artifacts/`。对话页选择第一位测试客户。

没有配置 API Key 也可查看管理页；右上角“配置 AI”保留实际设置入口。测试不能代替真实 WhatsApp 登录、送达验证或 OCR 模型验证。
