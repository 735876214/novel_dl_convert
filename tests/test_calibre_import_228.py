"""外部书库的**只读登记**导入（第 228 期）：Calibre `metadata.db`。

## 范围（刻意很小）

**只读登记**：读 Calibre 的 `metadata.db`，把它的元数据写成**覆盖层**
（`meta_override`）。**不复制文件、不写源、不导其它应用的用户与进度**。

## 用例盯三件事

1. **只读**：用 `mode=ro` 打开对方的库 —— 绝不能以可写方式打开（写坏了不可逆）。
2. **Calibre 的列名会变**：`timestamp` / `pubdate` / `sort` … 逐列探测，
   表里没有的列就空着，不假定一套列名。
3. **登记的是「元数据」，不是「文件」**：文件由本项目自己的扫描发现，
   本模块只写覆盖层。
"""
from __future__ import annotations

import pathlib
import sqlite3

from novelforge.core import calibreimport, db, library


def _make_calibre(root: pathlib.Path, name: str = "metadata.db") -> pathlib.Path:
    """造一个**最小**的 Calibre `metadata.db`（四张表 + 几行）。"""
    root.mkdir(parents=True, exist_ok=True)
    p = root / name
    conn = sqlite3.connect(str(p))
    try:
        conn.executescript("""
        CREATE TABLE books (
            id INTEGER PRIMARY KEY, title TEXT, sort TEXT, author_sort TEXT,
            series TEXT, series_index REAL, isbn TEXT, pubdate TEXT,
            publisher TEXT, tags TEXT, path TEXT, format TEXT, timestamp TEXT
        );
        CREATE TABLE authors (id INTEGER PRIMARY KEY, name TEXT, sort TEXT);
        CREATE TABLE series (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE tags (id INTEGER PRIMARY KEY, name TEXT);
        INSERT INTO books VALUES
            (1, '三体', '三体', '1', '2', 1.0, '9787536692931', '2008-01-01',
             '重庆出版社', '科幻', '三体/三体 - 刘慈欣.epub', 'EPUB', '2008-01-01 00:00:00'),
            (2, '球状闪电', '球状闪电', '1', '', 0.0, '', '2004-01-01',
             '', '科幻', '球状闪电/球状闪电 - 刘慈欣.epub', 'EPUB', '2004-01-01 00:00:00');
        INSERT INTO authors VALUES (1, '刘慈欣', '刘慈欣');
        INSERT INTO series VALUES (2, '地球往事');
        """)
        conn.commit()
    finally:
        conn.close()
    return p


# ---------------------------------------------------------------------------
# 读 metadata.db
# ---------------------------------------------------------------------------

def test_读出书单与元数据(tmp_path):
    root = tmp_path / "calibre"
    p = _make_calibre(root)
    out = calibreimport.read_calibre(p)
    assert out["books"], out["warnings"]
    b = out["books"][0]
    assert b["title"] == "三体"
    assert b["author"] == "刘慈欣"          # 作者是 id ⇒ 从 authors 表还原
    assert b["series"] == "地球往事"          # 系列 id ⇒ 从 series 表还原
    assert b["series_index"] == "1"
    assert b["isbn"] == "9787536692931"
    assert b["year"] == "2008"
    assert b["path"] == "三体/三体 - 刘慈欣.epub"


def test_读不到时如实说明而不是返回空(tmp_path):
    out = calibreimport.read_calibre(tmp_path / "根本没有这个.db")
    assert out["books"] == []
    assert out["warnings"], "读不到文件必须说明原因"


def test_不是_calibre_的库要如实说(tmp_path):
    p = tmp_path / "fake.db"
    conn = sqlite3.connect(str(p))
    conn.execute("CREATE TABLE 别的表 (x INTEGER)")
    conn.commit()
    conn.close()
    out = calibreimport.read_calibre(p)
    assert out["books"] == []
    assert any("books 表" in w for w in out["warnings"]), out["warnings"]


def test_是只读打开_不碰对方的库(tmp_path):
    """⚠️ 绝不能以可写方式打开对方的库（写坏了不可逆）。"""
    root = tmp_path / "calibre"
    p = _make_calibre(root)
    before = p.read_bytes()
    calibreimport.read_calibre(p)
    assert p.read_bytes() == before, "读 Calibre 的库把它的文件改了"


def test_列名缺失时不炸(tmp_path):
    """Calibre 的列名随版本变（`timestamp` / `pubdate` / `sort` …）⇒ 逐列探测。"""
    p = tmp_path / "slim.db"
    conn = sqlite3.connect(str(p))
    conn.executescript("""
        CREATE TABLE books (id INTEGER PRIMARY KEY, title TEXT, path TEXT);
        INSERT INTO books VALUES (1, '只有两列', 'x.epub');
    """)
    conn.commit()
    conn.close()
    out = calibreimport.read_calibre(p)
    assert len(out["books"]) == 1
    assert out["books"][0]["title"] == "只有两列"
    assert out["books"][0]["year"] == ""      # 没有 pubdate 列 ⇒ 空，不报错


# ---------------------------------------------------------------------------
# 登记计划
# ---------------------------------------------------------------------------

def test_登记计划_按路径定位文件(tmp_path):
    root = tmp_path / "calibre"
    (root / "三体").mkdir(parents=True)
    (root / "三体" / "三体 - 刘慈欣.epub").write_bytes(b"EPUB")
    books = [{"title": "三体", "path": "三体/三体 - 刘慈欣.epub", "author": "刘慈欣"}]
    plan = calibreimport.plan_registration(root, books)
    assert len(plan["items"]) == 1
    assert plan["items"][0]["title"] == "三体"
    assert plan["items"][0]["author"] == "刘慈欣"


def test_登记计划_文件不在库里要如实列出(tmp_path):
    root = tmp_path / "calibre"
    root.mkdir(parents=True)
    plan = calibreimport.plan_registration(root, [{"title": "幽灵", "path": "没有/这个.epub"}])
    assert plan["items"] == []
    assert plan["skipped"] and "不在" in plan["skipped"][0]["reason"]


def test_登记计划_格式收不了要如实列出(tmp_path):
    root = tmp_path / "calibre"
    root.mkdir(parents=True)
    (root / "x.txt").write_bytes(b"t")
    plan = calibreimport.plan_registration(root, [{"title": "TXT", "path": "x.txt"}],
                                         allowed_exts={".epub"})
    assert plan["items"] == []
    assert plan["skipped"] and "不收" in plan["skipped"][0]["reason"]


# ---------------------------------------------------------------------------
# 落成覆盖层
# ---------------------------------------------------------------------------

def test_登记落到覆盖层_不碰文件(client, auth_headers, isolated, tmp_path,
                                  make_library, make_book):
    """登记 = 把 Calibre 的元数据写成 `meta_override`；**文件一个字节不动**。"""
    lib_root = tmp_path / "lib"
    make_library("lib$1", "主书库", "ebook", lib_root)
    src = lib_root / "三体.epub"
    make_book(lib_root, "三体.epub")
    library.invalidate()
    before = src.read_bytes()

    plan = {"items": [{"path": "三体.epub", "title": "三体（Calibre）",
                        "author": "刘慈欣", "series": "地球往事",
                        "series_index": "1", "isbn": "9787536692931",
                        "publisher": "重庆出版社", "year": "2008", "tags": "科幻"}]}
    res = calibreimport.apply_registration("lib$1", plan)
    assert res["matched"] == 1, res
    assert res["written"] > 0

    b = library.books("lib$1")[0]
    assert b["title"] == "三体（Calibre）"
    assert b["author"] == "刘慈欣"
    assert b["series"] == "地球往事"
    assert src.read_bytes() == before, "登记不该动文件"


def test_登记_书还没被扫到要如实说明(client, auth_headers, isolated, tmp_path,
                                    make_library):
    make_library("lib$1", "主书库", "ebook", tmp_path / "lib")
    library.invalidate()
    plan = {"items": [{"path": "还没扫到的.epub", "title": "X", "author": "Y"}]}
    res = calibreimport.apply_registration("lib$1", plan)
    assert res["matched"] == 0
    assert res["skipped"] == 1
    assert res["warnings"], "没扫到书时必须说明（先扫描再登记）"
