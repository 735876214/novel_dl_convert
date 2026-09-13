#!/bin/sh
# NovelForge 容器启动脚本（幂等，免 build 部署用）
#
# 设计目标：缩短 NAS 上 docker compose 重启 / 重建的等待时间。
#   - 依赖（node + python 包）已存在于容器文件系统时，跳过 apt-get / pip install，
#     直接进入 uvicorn，启动从「分钟级」降到「秒级」。
#   - 仅当 node 缺失或关键 python 包未安装（首次启动 / 容器重建）时才走完整安装。
#
# 说明：python:3.12-slim 默认不带 node；pip 安装的包落在容器自身文件系统
# （/usr/local/lib/python3.12/site-packages），不写入挂载的源码目录，
# 因此「同一容器重启」时依赖保留、可跳过；「容器重建」时依赖丢失、会自动重装。

set -e

# 目录完整性自检：挂载到 /app 的源码目录必须含 requirements.txt 与 novelforge 包。
# 否则 pip / 启动都会失败，这里提前给出醒目提示，避免晦涩报错难以定位。
for f in /app/requirements.txt /app/novelforge; do
  if [ ! -e "$f" ]; then
    echo "[start] [FATAL] 缺失 $f —— 挂载到 /app 的目录不是完整的项目目录。"
    echo "[start] [FATAL] 请确认 docker-compose.yml 所在的 novel_dl_convert/ 目录已完整同步到本机（含 requirements.txt、start.sh、novelforge/、config.yaml 等），再重建容器。"
    echo "[start] [FATAL] 修复步骤：cd novel_dl_convert && git pull && docker compose up -d"
    exit 1
  fi
done

NEED_INSTALL=0
if ! command -v node >/dev/null 2>&1; then
  NEED_INSTALL=1
  echo "[start] 未检测到 node，需要安装系统依赖"
elif ! python -c "import ebooklib, fastapi, uvicorn" 2>/dev/null; then
  NEED_INSTALL=1
  echo "[start] 关键 Python 依赖缺失，需要重装"
fi

if [ "$NEED_INSTALL" -eq 1 ]; then
  echo "[start] === 首次/缺失依赖，开始安装（约 1~2 分钟）==="
  apt-get update
  apt-get install -y --no-install-recommends nodejs
  rm -rf /var/lib/apt/lists/*
  pip install --no-cache-dir -r /app/requirements.txt
  echo "[start] === 依赖安装完成 ==="
else
  echo "[start] 依赖已就绪，跳过安装，直接启动"
fi

echo "[start] 启动 uvicorn :8000"
exec uvicorn novelforge.server:app --host 0.0.0.0 --port 8000
