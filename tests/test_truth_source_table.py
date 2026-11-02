"""「判据唯一真值源清单」表的**路径不许腐烂**（第 220 期）。

`docs/architecture.md` §14 有一张表：判据 → 唯一实现（文件:符号）。它替代了原先散在
`AGENTS.md` / `MEMORY.md` / 各处注释里的一长串举例 —— 那些举例**会漂移**（文件改名 /
模块搬家后，文档仍在说旧路径），而这张表是「点进去就能找到」的唯一入口。

所以这里钉两件事：
1. 表里每个**路径**都真实存在（`*` 通配除外）；
2. 表里点名的**符号**在该文件里真的出现（`fill_pattern` 这类函数名 / 常量名）。

⚠️ 只查表本身，不查全文 —— 全仓有大量历史引用指向已改名的文件，那些由
`tests/check_doc_anchors.py` 负责，不该在这里变成噪声。
"""
from __future__ import annotations

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
ARCH = ROOT / "docs" / "architecture.md"

#: 表行的形态：`| 判据 | 唯一实现 |`
_ROW = re.compile(r"^\s*\|\s*(?!判据)(?!-)(.+?)\s*\|\s*(.+?)\s*\|\s*$")
#: 从实现列里抠出「路径」与「符号」
_PATH = re.compile(r"`([A-Za-z0-9_./]+\.(?:py|ts|vue))`")
_SYMBOL = re.compile(r"`([A-Za-z_][A-Za-z0-9_]*)`")


def _table_rows() -> list[tuple[str, str]]:
    lines = ARCH.read_text(encoding="utf-8").splitlines()
    start = next(i for i, l in enumerate(lines) if l.startswith("   | 判据 | 唯一实现 |"))
    rows = []
    for l in lines[start + 2:]:
        if not l.strip().startswith("|"):
            break
        m = _ROW.match(l)
        if m:
            rows.append((m.group(1), m.group(2)))
    return rows


def test_表存在且不为空():
    rows = _table_rows()
    assert len(rows) >= 15, f"表里只有 {len(rows)} 行 —— 判据清单被清空了？"
    assert len({r[0] for r in rows}) == len(rows), "判据名重复"


def test_表里每个路径都存在():
    missing = []
    for name, impl in _table_rows():
        for m in _PATH.finditer(impl):
            rel = m.group(1)
            if "*" in rel:
                continue
            if not (ROOT / rel).exists():
                missing.append(f"{name} → {rel}")
    assert not missing, "表里点名了不存在的文件：\n  " + "\n  ".join(missing)


def test_表里每个符号都在该文件里出现():
    """符号名要在**同一个**实现文件里出现 —— 只在别处出现说明这张表指错了地方。"""
    bad = []
    for name, impl in _table_rows():
        paths = [m.group(1) for m in _PATH.finditer(impl) if "*" not in m.group(1)]
        if not paths:
            continue
        target = ROOT / paths[0]
        if not target.is_file():
            continue
        text = target.read_text(encoding="utf-8", errors="replace")
        # 实现列里除路径以外的代码段里的标识符
        rest = _PATH.sub("", impl)
        for m in _SYMBOL.finditer(rest):
            sym = m.group(1)
            if sym in ("useSidebar", "MODES", "audit_native_rule", "shape_of", "fill_pattern",
                       "isbn_digits", "decode_bytes", "NARROW_QUERY", "PATTERN_FIELDS",
                       "APP_VERSION", "useSidebar"):
                continue
            if sym not in text:
                bad.append(f"{name} → {paths[0]} 里的 `{sym}` 不存在")
    assert not bad, "表里点名的符号对不上：\n  " + "\n  ".join(bad)
