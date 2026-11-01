"""书目导出粒度（第 211 期）：库范围 / 列选择 / 个人数据剥离。"""
from __future__ import annotations

import pathlib

from novelforge import config


def _setup(make_library):
    base = pathlib.Path(config.LIBRARY_SOURCE_ROOTS[0]["path"])
    a = base / "exp-a"
    b = base / "exp-b"
    make_library("exp-a", "A 库", "ebook", a)
    make_library("exp-b", "B 库", "ebook", b)
    a.mkdir(parents=True, exist_ok=True)
    b.mkdir(parents=True, exist_ok=True)
    (a / "甲.epub").write_bytes(b"EPUB")
    (b / "乙.epub").write_bytes(b"EPUB")


def _csv(resp) -> list[str]:
    return [x for x in resp.content.decode("utf-8-sig").splitlines() if x.strip()]


def test_库范围与列选择(client, auth_headers, make_library):
    _setup(make_library)
    r = client.get("/api/books/export", params={"library_id": "exp-a", "columns": "title,author"},
                   headers=auth_headers)
    assert r.status_code == 200, r.text
    lines = _csv(r)
    assert lines[0] == "书名,作者"
    text = r.content.decode("utf-8-sig")
    assert len(lines) == 2 and "甲" in text and "乙" not in text

    # personal=0：即使列里带 percent 也去掉
    r = client.get("/api/books/export", params={"columns": "title,percent", "personal": 0},
                   headers=auth_headers)
    assert _csv(r)[0] == "书名"

    assert client.get("/api/books/export", params={"columns": "nope"},
                      headers=auth_headers).status_code == 400
    assert client.get("/api/books/export", params={"library_id": "nope"},
                      headers=auth_headers).status_code == 404
