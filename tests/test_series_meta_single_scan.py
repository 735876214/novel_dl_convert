"""**系列端点不许把全库扫描做多遍**（第 226 期）。

第 152 期已把「系列详情页」的 4 遍全库扫描收成 1 遍并**传参复用**（`series_meta.effective(name, books)`
/ `state(name, books)` 都收 `books`）。但**兄弟端点**没跟着改：

- `GET  /api/series/{name}/meta`：自己 `series_books(name)` 一次 + `effective` 内部一次
  + `state` 内部一次 ⇒ **一个请求扫 3 遍**；
- `POST /api/series/{name}/meta` / `POST /api/series/{name}/fetch`：同样各自再扫；
- `GET  /api/v1/series/{id}`（Komga）：`items` 已经在手上了，却仍调 `effective(name)`
  让它**再扫一遍**。

这里钉：**每个端点里 `library.series_books(...)` / `series_meta.effective(...)` 的调用次数**，
且**凡已有成员书的地方必须传进去**。
"""
from __future__ import annotations

import ast
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
SERVER = ROOT / "novelforge" / "server.py"

#: 要盯的端点 → (允许的 series_books 调用次数, 函数名)
TARGETS = {
    "api_series_meta": 1,
    "api_set_series_meta": 1,
    "api_fetch_series_meta": 1,
    "ko_series_one": 0,          # Komga：成员书已在 items 里，不该再扫
}


def _body(src: str, name: str) -> str:
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            lines = src.splitlines()
            return "\n".join(lines[node.lineno - 1: node.end_lineno])
    raise AssertionError(f"找不到函数 {name}")


def test_系列端点的全库扫描次数():
    src = SERVER.read_text(encoding="utf-8")
    for fn, limit in TARGETS.items():
        body = _body(src, fn)
        n = len(re.findall(r"library\.series_books\(", body))
        assert n <= limit, f"{fn} 调了 {n} 次 series_books（上限 {limit}）—— 全库扫描做多了"


def test_已有成员书的地方必须传进_effective():
    """`effective(name, books)` 里的 `books` 缺省 = **它自己再扫一遍成员书目**。
    凡是成员书已经在手上（`rows` / `items`）的地方，必须传进去。"""
    src = SERVER.read_text(encoding="utf-8")
    for fn in ("api_series_meta", "api_set_series_meta", "api_fetch_series_meta", "ko_series_one"):
        body = _body(src, fn)
        for m in re.finditer(r"series_meta\.effective\(name\)", body):
            raise AssertionError(f"{fn} 里 `effective(name)` 没传成员书 —— 它会再扫一遍")
        if "series_meta.effective(" in body:
            assert re.search(r"series_meta\.effective\(name,\s*\w+\)", body), \
                f"{fn} 的 effective 调用没有传 books"


def test_第152期的传参能力仍在_series_meta():
    """`effective` / `state` 仍要收 `books` 参数 —— 哪天把它删了，这里会红。"""
    from novelforge.core import series_meta

    import inspect
    for fn in (series_meta.effective, series_meta.state):
        sig = inspect.signature(fn)
        assert "books" in sig.parameters, f"{fn.__name__} 少了 books 参数"
        assert sig.parameters["books"].default is None, \
            f"{fn.__name__} 的 books 应当可省（缺省 = 自己扫）"
