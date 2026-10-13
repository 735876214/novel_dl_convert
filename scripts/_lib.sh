#!/usr/bin/env bash
# 三个入口脚本（test.sh / frontend-verify.sh / dev-instance.sh）共用的两件事。
# 这里放的是**判据**（解释器探测顺序、要清哪些出网变量、临时根怎么取），只许有一份实现
# —— 各脚本不要各写一遍（第 115/116 期的教训：同一判据两份实现 ⇒ 只改一处没用）。
# 用法：在入口脚本里 `. "$SCRIPT_DIR/_lib.sh"`，不要直接执行本文件。

# 解释器探测：优先仓库 .venv（Linux/macOS 的 bin、Windows 的 Scripts），退回 PATH 上的 python3。
nf_resolve_python() {
  local cand
  for cand in ".venv/bin/python" ".venv/Scripts/python.exe"; do
    if [ -x "$cand" ]; then echo "$cand"; return 0; fi
  done
  if command -v python3 >/dev/null 2>&1; then echo python3; return 0; fi
  if command -v python >/dev/null 2>&1; then echo python; return 0; fi
  echo "找不到解释器：在仓库根建 .venv，或确保 PATH 上有 python3" >&2
  return 1
}

# 临时根目录的**原生路径**（正斜杠）。⚠️ Git Bash 的 /tmp 与原生 Windows 解释器眼里的
# /tmp 不是同一处 —— 直接把 "/tmp/..." 交给原生 python 会落到 C:\tmp\...（见 docs/development-windows.md §2）。
nf_tmp_root() {
  local py="$1"
  "$py" -c 'import tempfile;print(tempfile.gettempdir().replace(chr(92),"/"))'
}

# 清掉会干扰本仓运行的环境变量（Linux/容器上清空无副作用）：
#   · 六个 proxy 变量：httpx 0.28.1 解析 NO_PROXY 里的方括号 IPv6（[::1]）会生成畸变 mount
#     ⇒ 任何真实 BrowserClient 用例炸 InvalidURL: Invalid port ':1]'。**只去方括号不够，必须整组清空**。
#   · NODE_OPTIONS：本机 IDE 注入的 safe-delete shim 会拦 Vite 清 outDir 与 deploy.mjs 的删除，
#     也会干扰 pytest 会话末的清理。
# 详见 docs/development-windows.md §1/§3。
nf_clean_env() {
  unset HTTP_PROXY HTTPS_PROXY http_proxy https_proxy NO_PROXY no_proxy NODE_OPTIONS
}
