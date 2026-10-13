#!/usr/bin/env bash
# 后端测试（仓库首选入口）：探测解释器 → 清出网变量 → 跑 pytest → 用 junit 判定成败并打印摘要。
#
# 为什么要有这个脚本（细节见 docs/development-windows.md）：
#   ① 六个 proxy 变量必须**整组清空**，否则 httpx 0.28.1 解析 NO_PROXY 里的 [::1] 会让真实网络用例炸 InvalidURL；
#   ② IDE 注入的 safe-delete shim 经 NODE_OPTIONS 传进来，会干扰 pytest 会话末的清理；
#   ③ Windows 下 pytest 会话末退出码不可信（shim 干扰：全量绿但退出码非 0）—— **只认 junit**。
#
# 用法：
#   bash scripts/test.sh                                    # 全量
#   bash scripts/test.sh tests/test_catalog.py -k 关键字    # 参数原样透传给 pytest
#
# 收尾时把打印出的 junit 路径交给 `python tests/period_close.py new --junit <路径>` 取基线数字。
set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$SCRIPT_DIR/_lib.sh"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"

PY="$(nf_resolve_python)" || exit 2
nf_clean_env

JUNIT="$("$PY" -c 'import os,tempfile;d=os.path.join(tempfile.gettempdir(),"nf-junit");os.makedirs(d,exist_ok=True);print(os.path.join(d,"junit.xml").replace(chr(92),"/"))')"
rm -f "$JUNIT"

echo "== pytest（解释器：$PY）=="
"$PY" -m pytest --junitxml="$JUNIT" "$@"

if [ ! -f "$JUNIT" ]; then
  echo "⚠️ 没有生成 junit（pytest 没跑到收集完就退了）—— 结论看上面的输出" >&2
  exit 1
fi

"$PY" -X utf8 - "$JUNIT" <<'PYEOF'
import sys
import xml.etree.ElementTree as ET

root = ET.parse(sys.argv[1]).getroot()
tests = fails = errors = skips = 0
secs = 0.0
for ts in root.iter("testsuite"):
    tests += int(ts.get("tests", 0) or 0)
    fails += int(ts.get("failures", 0) or 0)
    errors += int(ts.get("errors", 0) or 0)
    skips += int(ts.get("skipped", 0) or 0)
    secs += float(ts.get("time", 0) or 0)
print(
    f"== junit：{tests} 例（{tests - fails - errors - skips} passed / {fails} failed / "
    f"{errors} errors / {skips} skipped），耗时 {secs:.1f} s =="
)
print(f"junit 路径（period_close.py --junit 可用）：{sys.argv[1]}")
sys.exit(1 if (fails or errors) else 0)
PYEOF
