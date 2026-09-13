FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app \
    TZ=Asia/Shanghai \
    INPUT_DIR=/app/input \
    OUTPUT_DIR=/app/output \
    CONFIG_DIR=/app/config

WORKDIR /app

# 先装依赖，利用 Docker 层缓存
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 复制源码（novelforge 为 Python 包）
COPY . .

# 预创建目录，保证配置文件以单文件方式挂载时挂载点存在
RUN mkdir -p /app/input /app/output /app/config

EXPOSE 8000

CMD ["uvicorn", "novelforge.server:app", "--host", "0.0.0.0", "--port", "8000"]
