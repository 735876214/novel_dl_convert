#!/usr/bin/env bash
# 三个入口脚本（test.sh / frontend-verify.sh / dev-instance.sh）共用的两件事。
# 这里放的是**判据**（解释器探测顺序、要清哪些出网变量、临时根怎么取），只许有一份实现
# —— 各脚本不要各写一遍（第 115/116 期的教训：同一判据两份实现 ⇒ 只改一处没用）。
# 用法：在入口脚本里 `. "$SCRIPT_DIR/_lib.sh"`，不要直接执行本文件。

# 解释器探测：优先仓库 .venv（Linux/macOS 的 bin、Windows 的 Scripts），退回 PATH 上的 python3。
#
# ⚠️ **`.venv` 的解释器必须"能用"才选它**（第 248 期收尾发现，本机 Windows 实测）：
# 它可能**建不出临时目录**（`%TEMP%` 下 `os.makedirs` 报 `PermissionError [WinError 5]`）⇒
# `tempfile.gettempdir()` **静默退回 cwd**（= 仓库根）⇒ pytest 的默认 basetemp 落进仓库，
# 收尾 `rmtree` 被 `tests/conftest.py` 的仓库根防删除守卫拦下 ⇒ **整片 `[REPO-ROOT GUARD]`**
# （看着像"测试全坏了"，其实是解释器选错了）。
# 所以探测里加一条**能力判据**：`mkdtemp()` 必须落在真正的临时目录（不是 cwd）。
# Linux/容器上 `.venv` 建得出来 ⇒ 行为与改造前**逐字相同**。
#
# 退回系统解释器时，把 `.venv` 的 site-packages 挂到 `PYTHONPATH`（依赖都装在那儿），
# 否则退回等于换了个空环境。**这里是 export 的唯一一处**，各入口脚本不必自己再设。
#
# ⚠️ **调用方式：先把结果接进 `NF_PYTHON`，别用 `$(...)`** ——
# 命令替换跑在**子 shell** 里，里面 `export PYTHONPATH` 传不回来（症状：退回系统解释器后
# 「No module named pytest」）。所以本函数**不 echo**，直接给调用者的 shell 变量赋值。
nf_python_usable() {
  local py="$1"
  "$py" - <<'PY' >/dev/null 2>&1
import os, tempfile
probe = os.path.abspath(tempfile.mkdtemp())
try:
    cwd = os.path.abspath(os.getcwd())
    # 落在 cwd（或其内部）⇒ gettempdir() 退回了 cwd、真正的临时目录不可用
    raise SystemExit(1 if (probe == cwd or probe.startswith(cwd + os.sep)) else 0)
finally:
    try:
        os.rmdir(probe)
    except OSError:
        pass
PY
}

nf_resolve_python() {
  local cand
  for cand in ".venv/bin/python" ".venv/Scripts/python.exe"; do
    if [ -x "$cand" ] && nf_python_usable "$cand"; then NF_PYTHON="$cand"; return 0; fi
  done
  # .venv 在、但用不了 ⇒ 退回系统解释器 + .venv 的 site-packages
  #
  # ⚠️ 路径必须是**原生**形式（`C:/…`），不能给 `pwd` 的 POSIX 形式（`/c/…`）——
  # 原生 Windows 解释器读不懂 `/c/…`，`PYTHONPATH` 会被静默忽略（表现为「没有 pytest」）。
  # `pwd -W` 是 Git Bash 专有的「Windows 形式」；Linux 上它失败 ⇒ 退回普通 `pwd` + `:` 分隔符。
  local venv_sp native sep
  for venv_sp in ".venv/Lib/site-packages" ".venv/lib/python3"*/"site-packages"; do
    [ -d "$venv_sp" ] || continue
    if native="$(cd "$venv_sp" && pwd -W 2>/dev/null)" && [ -n "$native" ]; then
      sep=";"                       # Windows：PYTHONPATH 用分号
    else
      native="$(cd "$venv_sp" && pwd)"
      sep=":"                       # POSIX 兜底
    fi
    PYTHONPATH="$native${PYTHONPATH:+$sep$PYTHONPATH}"
    export PYTHONPATH
    echo "⚠️ 仓库 .venv 的解释器用不了（建不出临时目录）⇒ 退回系统解释器 + .venv 的 site-packages" >&2
    break
  done
  # ⚠️ `command -v python3` 有命中**不等于**能跑：Windows 上它可能是应用商店的
  # `WindowsApps/python3` 占位符（执行零输出、直接失败）⇒ 两个候选都要过同一条能力探测。
  for cand in python3 python; do
    if command -v "$cand" >/dev/null 2>&1 && nf_python_usable "$cand"; then NF_PYTHON="$cand"; return 0; fi
  done
  echo "找不到可用的解释器：在仓库根建 .venv，或确保 PATH 上的 python3 / python 真能跑" >&2
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
