# 部署指南（多租户版）

面向"一台海外 VPS + 一个域名"的最小可用部署。整套服务包含：

| 组件 | 说明 |
|---|---|
| Python 后端 | FastAPI + 每个租户一个 SQLite |
| Node bridge | 每个登录用户一个进程，各自扫码 |
| Cloudflare Tunnel | 公网入口，无需开放端口 |
| Cloudflare Access | 登录之外的又一层门（可选但强烈建议） |

---

## 1. 选机器

- **必须在海外**，且能访问 `web.whatsapp.com`（WhatsApp 对机房 IP 有风控，但比 Muse 那类宽松）。
- 起步配置：**2C4G**。每个 bridge 进程约占 150–250 MB，10 个活跃用户约 2–3 GB。
- 系统：Ubuntu 22.04/24.04。

```bash
# 基础环境
sudo apt update && sudo apt install -y docker.io docker-compose-v2 git
sudo usermod -aG docker $USER && newgrp docker
```

## 2. 拉代码并启动

```bash
git clone https://github.com/Grant-dex/WhatsApp_bot.git
cd WhatsApp_bot
docker compose up -d --build
docker compose logs -f
```

看到 `Admin console: http://127.0.0.1:8000` 即成功。

> 容器只把端口绑在 `127.0.0.1`，不直接对公网开放。

## 3. 创建管理员

```bash
# 在你自己电脑上开一条隧道先访问
ssh -L 8000:127.0.0.1:8000 user@your-vps
# 浏览器打开 http://127.0.0.1:8000
```

第一个账号是管理员，会接管 `data/` 目录；之后注册的用户各自拿到 `data/tenants/<id>/`。

## 4. 固定域名（Cloudflare 命名隧道）

快速隧道（`trycloudflare.com`）每次重启换地址，不能当正式入口。

```bash
# 一次性登录，会打开浏览器授权
docker run --rm -it -v ~/.cloudflared:/home/nonroot/.cloudflared \
  cloudflare/cloudflared:latest tunnel login

# 创建隧道（记下输出的 UUID）
docker run --rm -v ~/.cloudflared:/home/nonroot/.cloudflared \
  cloudflare/cloudflared:latest tunnel create whatsapp-bot

# 绑定域名
cloudflared tunnel route dns whatsapp-bot bot.example.com
```

`~/.cloudflared/config.yml`：

```yaml
tunnel: <UUID>
credentials-file: /home/nonroot/.cloudflared/<UUID>.json
ingress:
  - hostname: bot.example.com
    service: http://127.0.0.1:8000
  - service: http_status:404
```

加入 `docker-compose.yml`：

```yaml
  cloudflared:
    image: cloudflare/cloudflared:latest
    restart: unless-stopped
    network_mode: host
    command: tunnel --no-autoupdate --config /etc/cloudflared/config.yml run
    volumes:
      - ~/.cloudflared:/etc/cloudflared:ro
```

## 5. 再加一道 Access（推荐）

控制台虽然有登录，但多一层邮箱验证码几乎没有成本：

Cloudflare Zero Trust → Access → Applications → Add：

- Type: Self-hosted
- Domain: `bot.example.com`
- Policy: Allow，选择你的邮箱（或整个域名），需要 One-time PIN

之后访问会先过 Cloudflare 验证，再到应用登录页。

## 6. 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `WA_ALLOW_SIGNUP` | `1` | 设为 `0` 关闭自助注册，只允许管理员建号 |
| `LLM_API_KEY` | 空 | 平台级默认 Key；用户可在自己 `data/.env` 覆盖 |
| `API_HOST` / `API_PORT` | `127.0.0.1` / `8000` | 监听地址 |
| `BRIDGE_PORT` | `3001` | 单租户回退端口；多租户由 `bridge_manager` 分配 3101+ |

## 7. 数据与备份

```
/data
├── accounts.db          # 用户与会话（全局）
├── bridges.json         # 租户 → bridge 端口映射
├── data/                # 管理员的数据
└── tenants/<user_id>/   # 每个用户
    ├── config.yaml
    ├── .env             # 该用户自己的 LLM Key
    ├── logs/
    └── data/
        ├── customers.db
        └── .baileys-auth/   # WhatsApp 登录态
```

每日备份（SQLite 用 `.backup`，不要直接拷正在写的库）：

```bash
docker compose exec -T whatsapp-bot sh -c '
  mkdir -p /data/backups
  for db in /data/accounts.db /data/data/customers.db /data/tenants/*/data/customers.db; do
    [ -f "$db" ] || continue
    out="/data/backups/$(echo $db | tr "/" "_")_$(date +%F).db"
    sqlite3 "$db" ".backup $out" 2>/dev/null || cp "$db" "$out"
  done
'
```

## 8. 升级

```bash
git pull
docker compose up -d --build
```

数据在挂载卷里，重建容器不影响；正在扫码的 bridge 会重启，用户需要重新连一次（`data/.baileys-auth` 仍在，多数情况会自动恢复）。

## 9. 排障

| 现象 | 排查 |
|---|---|
| 打开是登录页但登录后 500 | `docker compose logs`，多半是 `data/` 权限（容器内 uid 10001） |
| 点"启动连接"报缺少依赖 | 镜像构建时 `npm --prefix bridge install` 失败，进容器手动装 |
| 二维码不显示 | 看 `data/tenants/<id>/logs/bridge.log`，常见是 WhatsApp 拒绝了机房 IP |
| 其他用户看不到自己的数据 | 确认 URL 没被缓存成固定租户；退出重登一次 |
