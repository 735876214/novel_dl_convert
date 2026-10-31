"""EPUB 书内全文搜索（第 189 期）。"""
from __future__ import annotations

import pathlib

from novelforge import config
from novelforge.core import epub_builder


def _setup(client, auth_headers, make_library):
    root = pathlib.Path(config.LIBRARY_SOURCE_ROOTS[0]["path"]) / "booksearch"
    make_library("lib-search", "搜索库", "ebook", root)
    ep = root / "搜索书.epub"
    epub_builder.build_epub(
        {"title": "搜索书", "author": "某人", "language": "zh"},
        [
            {"title": "第一章", "body": "<p>深海里的一条鱼</p><p>潮汐</p>"},
            {"title": "第二章", "body": "<p>另一段文字</p><p>潮汐又来了</p>"},
        ],
        str(ep), nav=False,
    )
    cards = client.get("/api/books", headers=auth_headers).json()["items"]
    return next(b["id"] for b in cards if b["name"] == ep.name)


def test_书内搜索命中章节与上下文(client, auth_headers, make_library):
    bid = _setup(client, auth_headers, make_library)
    r = client.get(f"/api/books/{bid}/search", params={"q": "深海"}, headers=auth_headers)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["total"] == 1 and data["truncated"] is False
    hit = data["items"][0]
    assert hit["chapter_index"] == 0 and hit["title"] == "第一章"
    assert "深海" in hit["snippet"] and hit["offset"] >= 0

    # 大小写不敏感 + 第二章
    r = client.get(f"/api/books/{bid}/search", params={"q": "潮汐"}, headers=auth_headers)
    items = r.json()["items"]
    assert [x["chapter_index"] for x in items] == [0, 1]
    assert items[1]["title"] == "第二章"

    # limit 截断如实标注
    r = client.get(f"/api/books/{bid}/search", params={"q": "潮汐", "limit": 1},
                   headers=auth_headers)
    assert r.json()["total"] == 1 and r.json()["truncated"] is True

    # 无命中
    r = client.get(f"/api/books/{bid}/search", params={"q": "不存在的词"}, headers=auth_headers)
    assert r.json()["items"] == [] and r.json()["total"] == 0


def test_书内搜索入参校验(client, auth_headers, make_library):
    bid = _setup(client, auth_headers, make_library)
    assert client.get(f"/api/books/{bid}/search", params={"q": ""},
                      headers=auth_headers).status_code == 400
    assert client.get("/api/books/nope/search", params={"q": "x"},
                      headers=auth_headers).status_code == 404
