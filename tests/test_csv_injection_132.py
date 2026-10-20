"""第 132 期：CSV 导出的公式注入防护。

**问题**：CSV 里的字不归我们控制 —— 书名 / 作者 / 系列 / 题材来自书目元数据（一本从外面
拖进来的 EPUB 就能自带 ``=HYPERLINK(...)`` / ``=cmd|'/c calc'!A0``），批注的 ``quote`` /
``note`` 是从书里复制出来的原文。而被 Excel / LibreOffice / Sheets 打开时，
**以 ``=`` ``+`` ``-`` ``@`` ``\\t`` ``\\r`` 开头的格子会被当公式求值**。

四条口径：
1. 危险起始字符的**文本**格子必须以 ``'`` 开头（表格软件显示时隐藏它，值不变）；
2. **数字列不许被动**（评分 / 序号 / 进度 / 批注数 / 章节号）—— 前缀会让 Excel 失去数值语义；
3. 普通文本原样输出（不额外加引号，别把导出的可读性搞坏）；
4. 判据只有一处（``novelforge.core.csvsafe``），两个导出端点都走它。
"""
from __future__ import annotations

import csv
import io

from novelforge.core import csvsafe, library


def _bid(root, make_book, name: str) -> str:
    make_book(root, name)
    library.invalidate()
    # 与 tests/test_annotation_export.py 同理：写完要立刻读就得强制同步重扫，别赌时序。
    books = [b for b in library.books(force=True) if b["name"].endswith(name)]
    assert books, f"扫描没找到 {name}"
    return books[0]["id"]


def _rows(text: str) -> list:
    return list(csv.reader(io.StringIO(text.lstrip("\ufeff"))))


def test_判据_危险起始字符加引号_其余不动():
    for raw in ("=1+1", "+1", "-1+1", "@SUM(A1)", "\t=1+1", "\r=1+1"):
        assert csvsafe.cell(raw) == "'" + raw, raw

    # 危险字符出现在中间 / 结尾 ⇒ 表格软件不会求值，别加引号
    for raw in ("a=b", "1+1", "书名-下", "", "普通文本", "  =1+1"):
        assert csvsafe.cell(raw) == raw, raw

    # 数字列：原样交给 csv.writer（前缀会让 Excel 当文本）
    assert csvsafe.cell(4) == 4
    assert csvsafe.cell(-1) == -1
    assert csvsafe.cell(12.5) == 12.5
    assert csvsafe.cell(0) == 0
    assert csvsafe.cell(None) is None


def test_书目导出_恶意书名被当文本(client, auth_headers, isolated, default_root, make_book):  # noqa: ARG001
    make_book(default_root, "=1+1.csv注入书.txt")
    make_book(default_root, "正常书.txt")
    library.invalidate()
    library.books(force=True)

    r = client.get("/api/books/export", headers=auth_headers)

    assert r.status_code == 200, r.text
    rows = _rows(r.text)
    titles = [row[0] for row in rows[1:]]
    assert "'=1+1.csv注入书" in titles, titles
    assert "正常书" in titles, titles
    # 表头是我们自己的字，不受影响
    assert rows[0][0] == "书名"


def test_书目导出_数字列保持数值(client, auth_headers, isolated, default_root, make_book):  # noqa: ARG001
    bid = _bid(default_root, make_book, "三体.epub")
    client.put(f"/api/books/{bid}/rating", headers=auth_headers, json={"stars": 4})
    client.put(
        f"/api/books/{bid}/progress",
        headers=auth_headers,
        json={"locator": 3, "percent": 12.5},
    )

    rows = _rows(client.get("/api/books/export", headers=auth_headers).text)
    head = rows[0]
    row = next(r for r in rows[1:] if r[head.index("书名")] == "三体")

    # 评分 / 进度是 float/int 列 ⇒ 不带单引号前缀，Excle 里仍是数值
    assert row[head.index("评分")] == "4"
    assert row[head.index("阅读进度%")] == "12.5"
    assert not row[head.index("评分")].startswith("'")
    assert not row[head.index("阅读进度%")].startswith("'")


def test_批注导出_摘录与笔记被当文本(client, auth_headers, isolated, default_root, make_book):  # noqa: ARG001
    bid = _bid(default_root, make_book, "三体.epub")
    for quote, note in (
        ("=cmd|'/c calc'!A0", "@SUM(1+1)"),
        ("+86 是区号", "-不是减号"),
        ("正常摘录", ""),
    ):
        r = client.post(
            f"/api/books/{bid}/annotations",
            headers=auth_headers,
            json={"chapter": 1, "quote": quote, "note": note, "color": "yellow"},
        )
        assert r.status_code == 200, r.text

    rows = _rows(client.get("/api/annotations/export?format=csv", headers=auth_headers).text)
    head = rows[0]
    quotes = [r[head.index("quote")] for r in rows[1:]]
    notes = [r[head.index("note")] for r in rows[1:]]

    assert "'=cmd|'/c calc'!A0" in quotes, quotes
    assert "'+86 是区号" in quotes, quotes
    assert "正常摘录" in quotes, quotes
    assert "'@SUM(1+1)" in notes, notes
    assert "'-不是减号" in notes, notes
    # 章节号是数字列
    assert rows[1][head.index("chapter")] == "1"


def test_批注导出_json与markdown不受影响(client, auth_headers, isolated, default_root, make_book):  # noqa: ARG001
    bid = _bid(default_root, make_book, "三体.epub")
    client.post(
        f"/api/books/{bid}/annotations",
        headers=auth_headers,
        json={"chapter": 1, "quote": "=1+1", "note": ""},
    )

    j = client.get("/api/annotations/export?format=json", headers=auth_headers).json()
    assert j["items"][0]["quote"] == "=1+1"          # JSON 不是可执行格式，别动值

    md = client.get("/api/annotations/export?format=markdown", headers=auth_headers).text
    assert "=1+1" in md and "'=1+1" not in md
