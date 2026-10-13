#!/usr/bin/env bash
# 起一个**隔离**的本地实例：每次建全新临时目录、独立端口，不碰别人的实例与数据。
# 用法：bash scripts/dev-instance.sh [端口]     # 默认 8412
#
# ⚠️ 端口别抢：8993 常被测试用 compose 占、8992 是生产（NAS）；**不认识的 python 进程一律不 kill**
#    （本机常有并行会话的实例）。
# ⚠️ 改了后端代码**必须重启本进程**才生效。
set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$SCRIPT_DIR/_lib.sh"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"

PORT="${1:-8412}"
PY="$(nf_resolve_python)" || exit 2
nf_clean_env

# 端口占用先提示（**别 kill 占用者** —— 本机常有并行会话/生产容器的实例）
if curl -s -o /dev/null --max-time 2 "http://127.0.0.1:$PORT/health"; then
  echo "⚠️ 端口 $PORT 上已经有实例在响应（可能不是你的）—— 换一个端口：bash scripts/dev-instance.sh <端口>" >&2
  exit 2
fi

# ⚠️ 临时根要问解释器要**原生路径**：Git Bash 的 /tmp 与原生 Windows 解释器眼里的 /tmp 不是同一处
TMP_ROOT="$(nf_tmp_root "$PY")"
T="$TMP_ROOT/nf-dev-$(date +%s)-$$"
mkdir -p "$T/input" "$T/output" "$T/config" "$T/cache" "$T/data" "$T/libraries"

echo "隔离目录：$T"
echo "健康检查：curl -s http://127.0.0.1:$PORT/health   # 唯一给版本号的端点"
echo "登录：POST /api/auth/login，体 {\"user\":\"admin\",\"pin\":\"changeme\"}（仅本地默认，部署必须改 AUTH_USER / AUTH_PIN）"

# ⚠️ 别用 `env A=1 cmd` 启动：本机的 /usr/bin/env 是个会吞输出的 shim（命令不跑、退出码还是 0）。
INPUT_DIR="$T/input" OUTPUT_DIR="$T/output" CONFIG_DIR="$T/config" CACHE_DIR="$T/cache" \
DATA_DIR="$T/data" LIBRARY_SOURCE_DIR="$T/libraries" AUTO_WATCH=false \
  "$PY" -m uvicorn novelforge.server:app --port "$PORT"
