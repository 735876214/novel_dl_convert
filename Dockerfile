FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    TZ=Asia/Shanghai \
    INPUT_DIR=/app/input \
    OUTPUT_DIR=/app/output \
    CONFIG_DIR=/app/config \
    COOKIE_DIR=/app/config/cookies \
    CACHE_DIR=/app/config/cache \
    NODE_BIN=/usr/bin/node

WORKDIR /app

# 系统依赖：nodejs 用于「原生 JS eval」解密字体加密 / 内容混淆的站点
RUN apt-get update \
    && apt-get install -y --no-install-recommends nodejs curl \
    && rm -rf /var/lib/apt/lists/*

# 先装依赖，利用 Docker 层缓存
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制源码（novelforge 为 Python 包）
COPY . .

# 预创建目录，保证配置文件以单文件方式挂载时挂载点存在
RUN mkdir -p /app/input /app/output /app/config /app/config/cookies /app/config/cache

EXPOSE 8000

CMD ["uvicorn", "novelforge.server:app", "--host", "0.0.0.0", "--port", "8000"]
