# WhatsApp-bot 多租户服务端
# 需要 Python（后端）+ Node（每个租户一个 WhatsApp bridge 进程）
FROM node:22-bookworm-slim AS node

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# 运行 bridge 需要 node
COPY --from=node /usr/local/bin/node /usr/local/bin/node

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN npm --prefix bridge install --omit=dev --no-audit --no-fund \
    && npm cache clean --force 2>/dev/null || true

RUN useradd -m -u 10001 app \
    && mkdir -p /data \
    && chown -R app:app /app /data

USER app

EXPOSE 8000
VOLUME ["/data"]

HEALTHCHECK --interval=30s --timeout=3s --start-period=20s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2).status == 200 else 1)"

# 数据（accounts.db、各租户目录、bridge 会话）全部落在 /data
CMD ["python", "src/web_main.py", "--host", "0.0.0.0", "--port", "8000", "--data-dir", "/data", "--no-browser"]
