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

# 第 62 期：选了 PostgreSQL 就得有驱动。不在镜像里做「有就装」的兜底 —— 启动时
# 悄悄 pip install 会让「镜像里到底有什么」变得不可知；缺了就直接说清楚怎么补。
case "$(echo "${NOVELFORGE_DB:-sqlite}" | tr 'A-Z' 'a-z')" in
  pg|postgres|postgresql)
    if ! python -c "import psycopg" 2>/dev/null; then
      echo "[start] [FATAL] 选了 PostgreSQL（NOVELFORGE_DB=${NOVELFORGE_DB}）但没装驱动。"
      echo "[start] [FATAL] 镜像应包含 psycopg[binary]；请确认 requirements.txt 已生效并重建镜像。"
      exit 1
    fi
    echo "[start] 数据库后端：PostgreSQL（${NOVELFORGE_PG_SCHEMA:-public} schema）"
    ;;
  *)
    echo "[start] 数据库后端：SQLite（内置，默认）"
    ;;
esac

# 第 62 期 C：缓存层是**可选**的，所以驱动缺失这里**只提示、不拦** ——
# 没装 redis 包时整层缓存自动变空操作（每次直读 PG），业务照常。
# 与 PG 那条的区别是有意的：PG 是数据后端，缺驱动 = 数据没地方去，必须失败；
# 缓存缺驱动 = 只是慢一点，不该让服务起不来。
if [ -n "${NOVELFORGE_REDIS_URL:-}" ]; then
  if python -c "import redis" 2>/dev/null; then
    echo "[start] 缓存层：Redis（${NOVELFORGE_REDIS_URL}）"
  else
    echo "[start] [WARN] 配了 NOVELFORGE_REDIS_URL 但没装 redis 包 —— 本次启动缓存整层关闭。"
    echo "[start] [WARN] 镜像应包含 redis；若自行裁剪过依赖，请把 requirements.txt 里的 redis 装回来。"
  fi
else
  echo "[start] 缓存层：关闭（未设 NOVELFORGE_REDIS_URL）"
fi

# 第 149 期：以非 root 运行（compose 的 `user:`）时，挂载目录的属主必须匹配 —— 否则
# uvicorn 起得来、写配置 / 存进度时才炸，用户看到的是一串 PermissionError 堆栈。
# 这里启动前先自检，写不进去就直接说清楚「哪个目录」和「该 chown 什么」，然后失败退出。
if [ "$(id -u)" != "0" ]; then
  bad=""
  for d in "${INPUT_DIR:-/app/input}" "${OUTPUT_DIR:-/app/output}" \
           "${CONFIG_DIR:-/app/config}" "${COOKIE_DIR:-/app/config/cookies}" \
           "${CACHE_DIR:-/app/config/cache}" "${DATA_DIR:-/app/data}"; do
    [ -d "$d" ] || continue
    if ( : > "$d/.novelforge-write-check" ) 2>/dev/null; then
      rm -f "$d/.novelforge-write-check"
    else
      bad="$bad $d"
    fi
  done
  if [ -n "$bad" ]; then
    echo "[start] [FATAL] 以 uid=$(id -u):$(id -g) 运行，但这些挂载目录写不进去:$bad"
    echo "[start] [FATAL] 在宿主机上把属主改成该 uid/gid 后重启，例如（cd 到部署目录再执行）："
    echo "[start] [FATAL]   sudo chown -R $(id -u):$(id -g) ./input ./output ./config ./cookies ./cache ./data"
    echo "[start] [FATAL] 或者把 compose 里的 user: 去掉（回落到镜像默认的 root）。"
    exit 1
  fi
  echo "[start] 非 root 运行（uid=$(id -u):$(id -g)），挂载目录均可写"
fi

echo "[start] 启动 uvicorn :${PORT:-8000}"
exec uvicorn novelforge.server:app --host 0.0.0.0 --port "${PORT:-8000}"
