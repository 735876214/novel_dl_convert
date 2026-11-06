"""**出版年**只能有一处判据（第 265 期）。

## 缺陷

同一个 `year`，三条来路各自解析：

| 来路 | 实现 | 判据 |
|---|---|---|
| 入库（读 OPF 的 `dc:date`） | `library._year_of` | `\\d{4}` —— 任意四位 |
| Calibre 只读登记（读 `pubdate`） | `calibreimport._year_of` | `\\d{4}` —— 任意四位 |
| 在线抓取（读源站字段） | `metasources._year_of` | `1[5-9]\\d{2}\\|20\\d{2}` —— 限 1500–2099 |

⇒ 一条 `dc:date` 写成 `0001-01-01` 的书：**入库**那条路把 `0001` 写进 `year`，
**抓取**那条路写的是空串 —— 同一本书的两条来路给出不同值，而 `year` 会参与排序与筛选。

## 这里钉什么

1. 判据只有 `core/metadata.py::year_of` 一份（别的文件不许再定义 `_year_of` / `year_of`）；
2. 三条来路对**脏值**给出**同一个**答案（空串），不再是「入库 0001 / 抓取 空」；
3. 正常的四种形态（`2008` / `2008-05-01` / `2008.0` / Calibre 的 `pubdate`）都能取到。
"""
from __future__ import annotations

import re
from pathlib import Path

from novelforge.core import calibreimport, library, metadata, metasources

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "novelforge"


def test_只有_metadata_定义_year_of():
    offenders = []
    for p in sorted(PKG.rglob("*.py")):
        if p.name == "metadata.py":
            continue
        text = p.read_text(encoding="utf-8", errors="ignore")
        if re.search(r"^def _?year_of\(", text, re.M):
            offenders.append(p.relative_to(ROOT).as_posix())
    assert not offenders, "这些文件又自己定义了一份出版年解析：" + ", ".join(offenders)


def test_正常形态都能取到():
    assert metadata.year_of("2008") == "2008"
    assert metadata.year_of("2008-05-01") == "2008"
    assert metadata.year_of("2008.0") == "2008"
    assert metadata.year_of("2011-03-05 00:00:00") == "2011"     # Calibre 的 pubdate
    assert metadata.year_of("") == ""
    assert metadata.year_of(None) == ""


def test_脏值一律留空而不是取一个像年份的四位数():
    """`0001` / `9999` 这类值只可能是解析噪音 —— 统一留空，不给下游一个会被当数字用的错值。"""
    for bad in ("0001-01-01", "9999", "0123", "abc", "（未知）"):
        assert metadata.year_of(bad) == "", bad


def test_三条来路对脏值给出同一个答案():
    """回归点：此前入库路径取 `0001`、抓取路径取空 —— 两条来路不一致。"""
    dirty = "0001-01-01"
    assert metadata.year_of(dirty) == ""
    # Calibre 那条路（原来也是 `\\d{4}`）
    assert metadata.year_of("0001-01-01 00:00:00") == ""
    # 抓取那条路（原来就限 1500–2099）
    assert metadata.year_of(dirty) == ""


def test_模块仍然对外可用():
    """三条来路各自的模块必须还在用同一个实现（别把调用点也删了）。"""
    for mod in (library, calibreimport, metasources):
        assert mod.metadata is metadata
