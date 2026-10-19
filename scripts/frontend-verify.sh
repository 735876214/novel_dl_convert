#!/usr/bin/env bash
# 前端四连（仓库首选入口）：type-check → test:unit → build → deploy，缺一即退非 0。
#
# ⚠️ build 只落 frontend/dist，**deploy 才同步到 novelforge/static/v2** —— 漏 deploy 则服务端仍发旧 bundle
#    （改动看起来「没生效」；见 AGENTS.md §4）。
# ⚠️ 先清 NODE_OPTIONS：IDE 注入的 safe-delete shim 会拦 Vite 清 outDir 与 deploy.mjs 的删除。
# ⚠️ vitest **不校验模块导出完整性** —— 只有 build 才报模块断链，所以四步一步都不能省。
# ⚠️ **别把本脚本接进管道**（`bash scripts/frontend-verify.sh | tail`）：退出码会变成 `tail` 的。
#    要截取输出用重定向（`> out.log 2>&1; echo $?`）。
set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$SCRIPT_DIR/_lib.sh"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT/frontend"

nf_clean_env
command -v npm >/dev/null 2>&1 || { echo "找不到 npm（Node 走 nvm，先 nvm use 24.x）" >&2; exit 2; }

for step in type-check test:unit build deploy; do
  echo "== npm run $step =="
  npm run "$step" || { echo "❌ 四连在第 '$step' 步失败（后续步骤未跑）" >&2; exit 1; }
done

echo "✅ 前端四连完成：产物已同步到 novelforge/static/v2"
