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

## 5.5 用 Access 直接登录（免密码）

应用支持"过了 Cloudflare Access 就直接进"，用户完全看不到应用自己的登录页。

1. 按第 5 节把 Access 应用建好（域名 `bot.example.com`）
2. 在 Zero Trust 控制台右上角复制你的 **team domain**，形如 `https://yourteam.cloudflareaccess.com`
3. 启动服务时带上环境变量：

```yaml
# docker-compose.yml
environment:
  CF_ACCESS_TEAM_DOMAIN: "https://yourteam.cloudflareaccess.com"
  CF_ACCESS_AUTO_LOGIN: "1"     # 设为 0 可关闭
```

打开 `https://bot.example.com` 的流程就变成：

```
Cloudflare Access 验证邮箱（一次性验证码）
        ↓
应用自动创建/匹配账号 → 种 session cookie → 直接进控制台
```

首次出现的邮箱会自动开通一个独立租户（随机密码，反正走 SSO 用不到），
之后的访问直接复用。不想让人自助开通，就关闭 `WA_ALLOW_SIGNUP` 并只放行指定邮箱。

> 安全说明：服务端拿浏览器里的 `CF_Authorization` cookie 去 Cloudflare 的
> `/cdn-cgi/access/get-identity` 换取身份，验证发生在 Cloudflare 侧，
> 伪造请求头或 cookie 都不会被放行。

## 6.5 出站代理

WhatsApp 对机房 IP 不算友好，很多时候必须挂代理。优先级从高到低：

1. **租户自己的** `config.yaml → bridge.proxy`（控制台里保存的就是这一项）
2. 进程环境变量 `HTTPS_PROXY` / `http_proxy`

`bridge_manager` 启动子进程时会把解析结果显式写进 `HTTPS_PROXY`，并在 `data/logs/bridge.log` 里打印一行 `Using proxy: ...`。

自检接口：

```bash
curl -s -b cookies.txt https://bot.example.com/admin/api/netcheck | jq
```

```json
{
  "proxy": "http://127.0.0.1:7897",
  "direct":   {"ok": true, "ip": "1.2.3.4", "country": "JP"},
  "via_proxy":{"ok": true, "ip": "5.6.7.8", "country": "US"},
  "bridge":   {"online": true, "port": 3101}
}
```

怎么读：

| 现象 | 含义 |
|---|---|
| 两边 IP 相同 | 代理没生效（或本机是 TUN 全局模式，直连也走了代理，属正常） |
| 只有 `via_proxy` 失败 | 代理挂了 / 端口写错 |
| 两边都失败 | 本机出网有问题，先查 DNS 和防火墙 |

注意两点：

- 进程内固定 `NO_PROXY=127.0.0.1,localhost`，bridge 回调自己不会绕代理。
- **AI 调用走的是进程环境变量**，不受租户 `bridge.proxy` 影响；要给 AI 也走代理，就配全局 `HTTPS_PROXY`。

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
