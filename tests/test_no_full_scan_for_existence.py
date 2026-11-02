"""**按 id 的存在性检查不许扫全库**（第 226 期）。

`library.books()` 会**全量物化**书目（SELECT + 覆盖层 2 查询 + 逐本拼 dict），
真机 2,309 本。而「这本还在吗」只需要一个是非题 —— `library.by_id` 是**带索引的一条 SELECT**
（第 62 期起，`catalog.find_by_id`）。

第 226 期审计在两处找到「为了一个整数 / 一个是非题扫全库」：
- `POST /api/reading-log`（手工补录阅读会话）：`any(b["id"] == bid for b in library.books())`；
- `GET /api/maintenance/overview` 与 `/api/maintenance/orphans`：`len(library.books())` 数书。

这里钉两件事：
1. 这三处**不许**再调 `library.books()`（源码层面查）；
2. 数书走 `catalog.totals(...)`（一次 COUNT）且**只统计当前登记的库** ——
   已移除库的残留索引行不算进来，否则数会比 `books()` 大（口径必须一致）。
"""
from __future__ import annotations

import ast
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
SERVER = ROOT / "novelforge" / "server.py"


def _function_body(src: str, name: str) -> str:
    """用 **AST** 取函数体（按缩进判定，不靠「下一个 def」—— 嵌套函数会骗过正则）。"""
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            lines = src.splitlines()
            return "\n".join(lines[node.lineno - 1: node.end_lineno])
    raise AssertionError(f"找不到函数 {name}")


def test_按id存在性检查不用全库扫描():
    src = SERVER.read_text(encoding="utf-8")
    body = _function_body(src, "api_add_session")
    assert "library.books()" not in body, \
        "手工补录阅读会话又用全库扫描做存在性检查了（改用 `library.by_id`）"
    assert "library.by_id(" in body, "应该用带索引的 `library.by_id`"


def test_维护页两处数书不用全库物化():
    src = SERVER.read_text(encoding="utf-8")
    for fn in ("api_maintenance", "_orphans"):
        body = _function_body(src, fn)
        assert "len(library.books())" not in body, \
            f"{fn} 还在用 `len(library.books())` 数书（改用 `catalog.totals`）"


def test_数书口径与_books_一致_只数登记在册的库():
    """`catalog.totals()` 默认数**全部索引行** —— 已移除库的残留索引会把数撑大。
    而 `library.books()` 只扫在册库 ⇒ 两处必须都传「当前登记的库 id」。"""
    src = SERVER.read_text(encoding="utf-8")
    for fn in ("api_maintenance", "_orphans"):
        body = _function_body(src, fn)
        assert "catalog.totals(" in body, f"{fn} 没用 catalog.totals"
        assert "library.libraries()" in body, \
            f"{fn} 的 totals 没过滤「当前登记的库」—— 口径会与 books() 不一致"
