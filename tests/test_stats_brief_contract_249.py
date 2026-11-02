"""`stats.brief`（仪表盘）与 `stats.overview`（统计页）的**契约**（第 249 期补测）。

## 为什么补这个

`core/stats.py` 的 `brief()` 是**仪表盘** 13 个部件的数据源（`/api/stats` 走它），
`overview()` 是**统计页**的数据源 —— 两者是**两份独立实现**（第 162 期为了让仪表盘
只付 3.6% 的字节与计算而拆出来的）。

而 `brief()` 此前**零测试** ⇒ 「键同名同形」只是注释里的承诺，没有网：
两份实现一旦漂移（某个键少算 / 算得不一样），**没有任何用例会红**。

## 这里钉两件事

1. **前端用到的每个键，`brief` 都得有**（缺一个 ⇒ 部件显示 undefined）；
2. **同名键在两份实现里值一致**（仪表盘与统计页对同一本书给出不同数字 = 用户困惑）。

⚠️ 实测有一处**故意**不同：`brief.reading` 没有 `unread` / `reading` 两个键，
`brief.authors.top` 是空的（前端只用 `authors.total`）⇒ 所以本用例钉的是
「**前端用到的键**」，不是「全部键」。
"""
from __future__ import annotations

import pytest

from novelforge.core import library, stats

#: 仪表盘 13 个部件实际读到的键（从 `components/dashboard/widgets/*.vue` 逐个收集）。
#: ⚠️ 这份清单**就是**契约 —— 组件若开始读新键，这里要同步加。
FRONTEND_KEYS = [
    "added_28d",
    "authors.total",
    "books.by_format",
    "books.languages",
    "books.size",
    "books.total",
    "hours",
    "reading.days",
    "reading.finished",
    "reading.sessions",
    "reading.streak",
    "series.total",
]


def _make_library(tmp_path, make_library, make_book, n: int = 3):
    root = tmp_path / "lib"
    make_library("lib$brief", "契约库", "ebook", root)
    for i in range(n):
        make_book(root, "书%d.epub" % i)
    library.invalidate()
    return "lib$brief"


def _dig(obj, path: str):
    cur = obj
    for part in path.split("."):
        assert isinstance(cur, dict), f"{path} 的 {part!r} 之前不是字典：{cur!r}"
        assert part in cur, f"brief/overview 里没有 {path!r}（键：{sorted(cur)}）"
        cur = cur[part]
    return cur


def test_brief_有前端用到的每个键(client, auth_headers, isolated, tmp_path,
                                  make_library, make_book):
    lid = _make_library(tmp_path, make_library, make_book)
    b = stats.brief(28, lid)
    for key in FRONTEND_KEYS:
        _dig(b, key)


def test_同名键在两份实现里一致(client, auth_headers, isolated, tmp_path,
                              make_library, make_book):
    """仪表盘与统计页对同一本书给出的数字必须一样。"""
    lid = _make_library(tmp_path, make_library, make_book)
    b = stats.brief(28, lid)
    o = stats.overview(28, 8, lid)
    for key in FRONTEND_KEYS:
        assert _dig(b, key) == _dig(o, key), f"{key}：仪表盘 {b} 与统计页 {o} 不一致"


def test_brief_的键是_overview_的子集(client, auth_headers, isolated, tmp_path,
                                     make_library, make_book):
    """brief 只给「部件要的那几个」⇒ 它的顶层键必须是 overview 的子集。"""
    lid = _make_library(tmp_path, make_library, make_book)
    b = stats.brief(28, lid)
    o = stats.overview(28, 8, lid)
    extra = sorted(set(b) - set(o))
    assert not extra, f"brief 里有 overview 没有的键：{extra}"
