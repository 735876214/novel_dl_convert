"""批量元数据编辑（第 157 期）：服务端逐本走单书编辑的同一套校验。

钉住三条：
- 一份 `fields` 真的写进每一本（生效值可见）；
- 某本失败不影响其它本，且**逐本回执带原因**（不吞错）；
- 判据与单书同一处 —— 只给未知字段时，每本都按单书那条 400 拒绝。
"""
from __future__ import annotations

import pathlib


def _ids(client, auth_headers, make_library, make_epub, tmp_path: pathlib.Path) -> list[str]:
    root = tmp_path / "batch-lib"
    make_library("batch-lib", "批量库", "ebook", root)
    make_epub(root, "甲.epub")
    make_epub(root, "乙.epub")
    assert client.post("/api/libraries/batch-lib/scan", headers=auth_headers).status_code == 200
    items = client.get("/api/books", headers=auth_headers).json()["items"]
    return sorted(b["id"] for b in items if b["name"] in ("甲.epub", "乙.epub"))


def test_批量写入每本都生效(client, auth_headers, make_library, make_epub, tmp_path):
    ids = _ids(client, auth_headers, make_library, make_epub, tmp_path)
    assert len(ids) == 2
    r = client.post("/api/books/batch-metadata", headers=auth_headers,
                    json={"ids": ids, "fields": {"author": "批量作者", "language": "zh"}})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["saved"] == 2 and body["failed"] == 0, body
    for bid in ids:
        meta = client.get(f"/api/books/{bid}/metadata", headers=auth_headers).json()
        assert meta["fields"]["author"] == "批量作者"
        assert meta["fields"]["language"] == "zh"


def test_逐本回执_失败不连累其它本(client, auth_headers, make_library, make_epub, tmp_path):
    ids = _ids(client, auth_headers, make_library, make_epub, tmp_path)
    r = client.post("/api/books/batch-metadata", headers=auth_headers,
                    json={"ids": [*ids, "不存在的书"], "fields": {"publisher": "某社"}})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["saved"] == 2 and body["failed"] == 1
    bad = next(x for x in body["results"] if x["id"] == "不存在的书")
    assert bad["ok"] is False and "不存在" in bad["error"]

    # 只给未知字段 ⇒ 复用单书那条 400：每本都失败，且原因一致
    r2 = client.post("/api/books/batch-metadata", headers=auth_headers,
                     json={"ids": ids, "fields": {"not_a_field": "x"}})
    assert r2.status_code == 200, r2.text
    b2 = r2.json()
    assert b2["saved"] == 0 and b2["failed"] == 2
    assert all("没有可改写的字段" in x["error"] for x in b2["results"])

    assert client.post("/api/books/batch-metadata", headers=auth_headers,
                       json={"ids": [], "fields": {"author": "x"}}).status_code == 400
