#!/bin/sh
# NovelForge 容器启动脚本
#
# 镜像内已内置源码与全部依赖（多阶段构建时烤入 /opt/venv），
# 因此这里不再执行 apt-get / pip install —— 启动即秒级，也不依赖容器内的网络。
# 仅做一次依赖自检（缺失时给出明确提示，而不是抛出晦涩的 ImportError），随后 exec uvicorn。

set -e

echo "[start] NovelForge 启动中（依赖已内置，跳过安装）"

# 依赖自检：正常路径下约 0.5s，异常时给出可操作的报错
if ! python -c "import fastapi, uvicorn, ebooklib" 2>/dev/null; then
  echo "[start] [FATAL] Python 依赖缺失，/opt/venv 可能未正确写入镜像。"
  echo "[start] [FATAL] 请重新构建镜像：docker build -t novelforge ."
  exit 1
fi

echo "[start] 启动 uvicorn :${PORT:-8000}"
exec uvicorn novelforge.server:app --host 0.0.0.0 --port "${PORT:-8000}"
