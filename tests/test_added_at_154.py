"""入库时间可编辑 / 可重算（第 154 期）。

契约：生效值 = `book_added` 覆盖 ?? 文件 mtime；写入只有 PUT/BATCH 两处，
所有读点（列表 / 详情 / 统计 / CSV）都认 `added_at`。
"""
from __future__ import annotations

import pathlib


def _book(client, auth_headers, make_library, make_epub, tmp_path: pathlib.Path,
          lid: str = "lib-added") -> dict:
    root = tmp_path / lid
    make_library(lid, "入库库", "ebook", root)
    make_epub(root, "日期书.epub")
    items = client.get("/api/books", headers=auth_headers).json()["items"]
    return next(b for b in items if b["name"] == "日期书.epub")


def _card(client, auth_headers, bid: str) -> dict:
    r = client.get(f"/api/books/{bid}", headers=auth_headers)
    assert r.status_code == 200, r.text
    return r.json()


def test_设置与清除入库时间(client, auth_headers, make_library, make_epub, tmp_path):
    book = _book(client, auth_headers, make_library, make_epub, tmp_path)
    bid = book["id"]
    mtime = float(book["mtime"])
    assert float(book["added_at"]) == mtime, "未覆盖时 added_at 必须等于文件 mtime"

    ts = 1_600_000_000.0
    r = client.put(f"/api/books/{bid}/added-at", headers=auth_headers,
                   json={"added_at": ts})
    assert r.status_code == 200, r.text
    assert float(_card(client, auth_headers, bid)["added_at"]) == ts

    # 列表接口同样认覆盖（缓存命中路径也要重算）
    items = client.get("/api/books", headers=auth_headers).json()["items"]
    assert float(next(b for b in items if b["id"] == bid)["added_at"]) == ts

    r = client.put(f"/api/books/{bid}/added-at", headers=auth_headers,
                   json={"added_at": None})
    assert r.status_code == 200, r.text
    assert float(_card(client, auth_headers, bid)["added_at"]) == mtime


def test_按文件时间重算会清掉整个库的覆盖(client, auth_headers, make_library,
                                          make_epub, tmp_path):
    book = _book(client, auth_headers, make_library, make_epub, tmp_path)
    bid, mtime = book["id"], float(book["mtime"])
    client.put(f"/api/books/{bid}/added-at", headers=auth_headers,
               json={"added_at": 1_600_000_000})
    r = client.post("/api/libraries/lib-added/recompute-added-at",
                    headers=auth_headers, json={"source": "mtime"})
    assert r.status_code == 200, r.text
    assert int(r.json()["cleared"]) >= 1
    assert float(_card(client, auth_headers, bid)["added_at"]) == mtime


def test_非法入参与未知对象(client, auth_headers, make_library, make_epub, tmp_path):
    book = _book(client, auth_headers, make_library, make_epub, tmp_path)
    bid = book["id"]
    for bad in (0, -1, "abc"):
        r = client.put(f"/api/books/{bid}/added-at", headers=auth_headers,
                       json={"added_at": bad})
        assert r.status_code == 400, (bad, r.text)
    assert client.put("/api/books/不存在/added-at", headers=auth_headers,
                      json={"added_at": 1}).status_code == 404
    assert client.post("/api/libraries/不存在/recompute-added-at",
                       headers=auth_headers, json={}).status_code == 404
    r = client.post("/api/libraries/lib-added/recompute-added-at",
                    headers=auth_headers, json={"source": "birthtime"})
    assert r.status_code == 400
