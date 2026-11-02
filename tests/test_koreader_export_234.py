"""批注**导出成 KOReader 的批注文件**（第 234 期）—— 往返一致 + 不盖掉用户的文件。

## 三条纪律（各有用例）

1. **写出来的能被读回去**：`koreader_anno.parse()` 必须能读回本模块导出的内容 ——
   否则就是「导出了一堆本项目自己都读不回来的东西」。转义规则（Lua 的 `%q`，
   **不是 JSON 的**）两边必须一致。
2. **不覆盖用户的文件而不说**：导出前先读现有文件，把本项目的批注**并进去**
   —— 用户在设备上写的批注不能丢。
3. **默认只算不改**（`apply=False`）：界面上的「导出」按钮要先跑一次 dry-run
   让人看到「会写几个文件、几条批注」，再落盘。
"""
from __future__ import annotations

import pathlib

from novelforge.core import koreader_anno, koreader_export


def _rows(quotes=("第一段引文", "第二段引文"), note="我的笔记", style="highlight",
          color="yellow"):
    # ⚠️ `anchor` 是**位置**（可重排版书里就是 XPointer 串）—— KOReader 的解析端
    # 把没有位置的条目当书签丢掉（`no_position`），所以带位置的批注才导得回去。
    return [
        {"quote": q, "note": note if i == 0 else "", "style": style, "color": color,
         "chapter": 0, "created_at": 1700000000.0, "start_off": 0, "end_off": 10,
         "anchor": "/body/DocFragment[3]/body/p[1]/text().0"}
        for i, q in enumerate(quotes)
    ]


def test_导出的文件能被_koreader_的解析器读回(tmp_path):
    """往返一致 —— 转义规则两边必须一样。"""
    book = tmp_path / "书.epub"
    book.write_bytes(b"EPUB")
    plan = koreader_export.plan_export(book, _rows())
    path = tmp_path / "out.annotations.lua"
    path.write_text(plan["preview"], encoding="utf-8")

    parsed = koreader_anno.parse(path.read_text(encoding='utf-8'))
    items, skipped, stats = koreader_anno.to_items(parsed)
    assert len(items) == 2, (items, skipped, stats)
    assert {i["quote"] for i in items} == {"第一段引文", "第二段引文"}
    # 第一条带笔记，第二条不带
    notes = [i for i in items if i.get("note")]
    assert len(notes) == 1 and "我的笔记" in notes[0]["note"]


def test_引文里有换行与引号也能往返(tmp_path):
    """Lua 的 `%q` 与 JSON 的转义**不同**（换行是「反斜杠 + 真换行」）——
    两边不一致就会往返失败。"""
    book = tmp_path / "书.epub"
    book.write_bytes(b"EPUB")
    tricky = '他说："你好"\n第二行\\反斜杠'
    plan = koreader_export.plan_export(book, _rows(quotes=(tricky,)))
    path = tmp_path / "out.annotations.lua"
    path.write_text(plan["preview"], encoding="utf-8")

    parsed = koreader_anno.parse(path.read_text(encoding='utf-8'))
    items, _sk, _st = koreader_anno.to_items(parsed)
    assert len(items) == 1, items
    assert items[0]["quote"] == tricky, repr(items[0]["quote"])


def test_不覆盖用户已有的批注(tmp_path):
    """设备上写过的批注必须在导出后**还在**。"""
    book = tmp_path / "书.epub"
    book.write_bytes(b"EPUB")
    existing = tmp_path / ("书.epub" + koreader_anno.SUFFIX)
    existing.write_text(
        koreader_export.build_lua(
            # ⚠️ `page` 要有值（XPointer 串）—— 没位置的条目会被解析端当书签丢掉
            # （`to_items` 的 `no_position`），那样就测不到「合并」了。
            [{"datetime": "2024-01-01 00:00:00", "text": "设备上写的", "note": "",
              "drawer": "lighten", "color": "yellow", "chapter": "",
              "page": "/body/DocFragment[9]/body/p[2]/text().0",
              "pos0": "", "pos1": ""}],
            device_id="kobo", path=str(existing)),
        encoding="utf-8")

    plan = koreader_export.plan_export(book, _rows())
    assert plan["existing"] == 1
    assert plan["add"] == 2
    assert plan["total"] == 3

    res = koreader_export.apply_export(book, _rows())
    assert res["ok"] is True
    parsed = koreader_anno.parse(pathlib.Path(res["path"]).read_text(encoding='utf-8'))
    items, _sk, _st = koreader_anno.to_items(parsed)
    assert len(items) == 3
    assert "设备上写的" in {i["quote"] for i in items}


def test_没有引文的批注不导出(tmp_path):
    """纯笔记（无引文）在 KOReader 里没有对应形态 ⇒ 不导（并如实计数）。"""
    book = tmp_path / "书.epub"
    book.write_bytes(b"EPUB")
    rows = [{"quote": "", "note": "只有笔记", "style": "note", "color": "yellow",
             "chapter": 0, "created_at": 0, "start_off": -1, "end_off": -1}]
    plan = koreader_export.plan_export(book, rows)
    assert plan["add"] == 0
    assert plan["skipped"] == 1
    assert plan["total"] == 0


def test_颜色与样式映射到_koreader_的叫法(tmp_path):
    book = tmp_path / "书.epub"
    book.write_bytes(b"EPUB")
    plan = koreader_export.plan_export(
        book, _rows(quotes=("甲",), style="underline", color="blue"))
    assert '["drawer"] = "underscore"' in plan["preview"]
    assert '["color"] = "blue"' in plan["preview"]


def test_写出来的文件第一行是路径注释_第二行是_return(tmp_path):
    """上游 `util.writeToFile(..., lua_dofile_ready=true)` 就是这个形状 ——
    `LuaSettings:open` 用 `pcall(dofile, file)` 读它。"""
    book = tmp_path / "书.epub"
    book.write_bytes(b"EPUB")
    plan = koreader_export.plan_export(book, _rows())
    lines = plan["preview"].splitlines()
    assert lines[0].startswith("-- ")
    assert lines[1].startswith("return ")


# ---------------------------------------------------------------------------
# 接口：POST /api/annotations/export-koreader
# ---------------------------------------------------------------------------

def test_接口_默认只算不改(client, auth_headers, isolated, tmp_path,
                          make_library, make_book):
    """默认（`apply=0`）**只算不改** —— 不写用户设备上的文件。"""
    make_library("lib$1", "主书库", "ebook", tmp_path / "lib")
    make_book(tmp_path / "lib", "书.epub")
    from novelforge.core import library
    library.invalidate()
    bid = library.books("lib$1")[0]["id"]

    r = client.post("/api/annotations/export-koreader", headers=auth_headers,
                    json={"book_id": bid, "apply": 0})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["applied"] is False
    assert body["path"].endswith(".annotations.lua")
    # 文件**还没被写出来**
    import pathlib
    assert not pathlib.Path(body["path"]).exists(), "只算不改却把文件写了"


def test_接口_缺书号与不存在的书(client, auth_headers, isolated):
    assert client.post("/api/annotations/export-koreader", headers=auth_headers,
                       json={}).status_code == 400
    assert client.post("/api/annotations/export-koreader", headers=auth_headers,
                       json={"book_id": "根本没有这本书"}).status_code == 404
