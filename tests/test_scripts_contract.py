"""`scripts/*.sh` 的静态契约（第 118 期）：变量花括号、语法可解析、行尾 LF。

**为什么要有这个文件**：`scripts/` 是本仓的「首选入口」，但它们是**shell 脚本** ——
pytest 跑不到、类型检查管不着、CI 以前也不跑（见下面第 3 条）。于是第 117 期落进去的
`scripts/test.sh` 在 macOS 上**一行都跑不了**，而本机（Windows）全绿、谁也看不见：

    scripts/test.sh: line 27: PY: unbound variable      # 退出码 1，看起来像「测试失败」

根因是 `echo "…$PY）…"` —— 变量名后面紧**全角右括号**。bash 在非 UTF-8 的 locale
（macOS 自带 bash 3.2 的默认 locale 就是）下会把那个多字节字符当成**变量名的一部分**，
于是找的是名为 `PY）` 的变量，`set -u` 直接报未定义。半角 `)` 不会触发。

这条断言把「变量后紧跟非 ASCII ⇒ 必须写 `${VAR}`」钉死：它挡的不是某个具体字符，
而是**这一类**（中文标点、全角括号、中文正文紧贴变量）—— 本仓的注释与提示语里
中文标点出现频率极高，靠眼睛看不住。
"""
import pathlib
import re
import shutil
import subprocess

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SCRIPTS = sorted((ROOT / "scripts").glob("*.sh"))

#: `$名` 后面紧**非 ASCII** 字符 —— 就是 bash 3.2 会吞进变量名的那些位置。
#: 变量名字符集在 bash 里是 `[A-Za-z0-9_]`，所以「合法名后接非 ASCII」才可疑；
#: `$1` / `$?` / `$@` 后接非 ASCII 不受影响（位置参数与特殊参数名是单字符），故排除。
_TRAP_RE = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*)(?=[^\x00-\x7F])")


def test_至少扫到一个脚本():
    """扫描面自检：`scripts/` 空了或改了后缀时，下面几条会静默通过 —— 这条不许静默。"""
    assert SCRIPTS, "scripts/*.sh 一个都没扫到（目录改名了？）"


@pytest.mark.parametrize("path", SCRIPTS, ids=lambda p: p.name)
def test_变量后紧跟非_ASCII_时必须写花括号(path):
    """`$PY）` 在 bash 3.2 里是变量 `PY）`；`${PY}）` 才是「变量 + 全角括号」。"""
    text = path.read_text(encoding="utf-8")
    bad = []
    for lineno, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith("#"):
            continue  # 注释不参与展开，不必管（含 shebang）
        for m in _TRAP_RE.finditer(line):
            bad.append(f"  {path.name}:{lineno}: ${m.group(1)} 后面紧跟非 ASCII ⇒ 写成 ${{{m.group(1)}}}")
    assert not bad, "变量名会被 bash 3.2 吞掉（macOS 上直接 unbound variable）：\n" + "\n".join(bad)


@pytest.mark.parametrize("path", SCRIPTS, ids=lambda p: p.name)
def test_脚本语法可解析(path):
    """`bash -n`：只解析不执行。挡的是括号/引号不配对这类「跑起来才发现」的错。"""
    bash = shutil.which("bash")
    if not bash:
        pytest.skip("本机没有 bash")
    res = subprocess.run([bash, "-n", str(path)], capture_output=True, text=True)
    assert res.returncode == 0, f"{path.name} 语法错：\n{res.stderr}"


@pytest.mark.parametrize("path", SCRIPTS, ids=lambda p: p.name)
def test_脚本行尾是_LF(path):
    """`AGENTS.md` §6：`*.sh` 必须 LF（CRLF 会让容器里的 `sh app/start.sh` 报 set 选项错）。"""
    assert b"\r\n" not in path.read_bytes(), f"{path.name} 含 CRLF"
