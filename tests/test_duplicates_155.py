"""重复书三类判据 + 「不是重复」持久判定（第 155 期）。

- 文件内容相同（同尺寸 sha256）
- ISBN 相同
- 同作者 + 书名相似度 ≥ 阈值
三类都并进同一棵并查集；同一物理文件被两条登记引用时不算重复。
"""
from __future__ import annotations

import pathlib

from novelforge.core import library


def _book(bid, name, *, title="", author="", isbn="", size=0, path=""):
    return {"id": bid, "name": name, "title": title, "author": author, "isbn": isbn,
            "size": size, "mtime": 1.0, "format": "EPUB", "path": path,
            "library_id": "lib"}


def test_文件哈希与_ISBN_都并进同一棵并查集(monkeypatch, tmp_path):
    p1 = tmp_path / "a.epub"
    p2 = tmp_path / "b.epub"
    p1.write_bytes(b"same-bytes")
    p2.write_bytes(b"same-bytes")
    books = [
        _book("1", "甲", title="完全不同的甲", author="作者甲", size=10, path=str(p1)),
        _book("2", "乙", title="完全不同的乙", author="作者乙", size=10, path=str(p2)),
        _book("3", "丙", title="ISBN 丙", author="作者丙", isbn="978-7-111-11111-1"),
        _book("4", "丁", title="ISBN 丁", author="作者丁", isbn="9787111111111"),
        _book("5", "戊", title="测试相似度的很长书名甲", author="刘慈欣"),
        _book("6", "己", title="测试相似度的很长书名乙", author="刘慈欣"),
    ]
    monkeypatch.setattr(library, "books", lambda lid=None: books)
    out = library.duplicate_groups(85)
    reasons = {g["reason"] for g in out["groups"]}
    assert "文件内容完全相同" in reasons
    assert "ISBN 相同" in reasons
    assert any("书名相似度" in r for r in reasons)
    # 同一物理文件的两条登记不并组
    books.append(_book("7", "a.epub", title="完全不同的甲", author="作者甲", size=10,
                       path=str(p1)))
    out2 = library.duplicate_groups(85)
    assert all(len(g["items"]) < 2 or "7" not in [i["id"] for i in g["items"]]
               for g in out2["groups"])


def test_不是重复持久化与恢复(client, auth_headers, make_library, make_epub, tmp_path):
    root = tmp_path / "dup"
    make_library("dup-lib", "重复库", "ebook", root)
    make_epub(root, "一.epub")
    make_epub(root, "二.epub")
    r = client.get("/api/duplicates", headers=auth_headers)
    assert r.status_code == 200, r.text
    groups = r.json()["groups"]
    assert groups, "两本内容相同的 EPUB 应该被分到一组"
    ids = [it["id"] for it in groups[0]["items"]]
    assert len(ids) >= 2

    r = client.post("/api/duplicates/dismiss", headers=auth_headers, json={"ids": ids})
    assert r.status_code == 200, r.text
    assert r.json()["added"] >= 1
    assert client.get("/api/duplicates", headers=auth_headers).json()["groups"] == []

    r = client.delete("/api/duplicates/dismissals", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["removed"] >= 1
    assert client.get("/api/duplicates", headers=auth_headers).json()["groups"]
