"""OPDS 只读客户端凭据（第 160 期）。

钉住五条：

- 只读凭据能用 HTTP Basic 读 `/opds`，但**看不到范围外**的库（全局 feed 过滤、单库 404）；
- 管理员账号照旧能看全部（默认零变化）；
- 停用 / 删除立即生效；改 PIN 后旧 PIN 失效；
- 响应里**永不**出现 PIN 或哈希；
- 与管理员同名 / 短 PIN / 不存在的库一律 400。
"""
from __future__ import annotations

import base64
import pathlib
import xml.etree.ElementTree as ET

from novelforge import config

NS = "{http://www.w3.org/2005/Atom}"


def _basic(user: str, pin: str) -> dict:
    return {"Authorization": "Basic " + base64.b64encode(f"{user}:{pin}".encode()).decode()}


def _titles(xml_text: str) -> list:
    return [str(e.findtext(f"{NS}title") or "")
            for e in ET.fromstring(xml_text).findall(f"{NS}entry")]


def _lib_with_book(client, auth_headers, make_library, root: pathlib.Path,
                   lid: str, name: str, book: str) -> str:
    root.mkdir(parents=True, exist_ok=True)
    (root / book).write_bytes(b"EPUB")
    make_library(lid, name, "ebook", root)
    assert client.post(f"/api/libraries/{lid}/scan", headers=auth_headers).status_code == 200
    items = client.get("/api/books", headers=auth_headers).json()["items"]
    return next(b["id"] for b in items if b["name"] == book)


def _with_opds(fn):
    config.save_overrides({"opds": {"enabled": True}})
    try:
        fn()
    finally:
        config.save_overrides({})


def test_只读凭据限定书库(client, auth_headers, make_library, tmp_path):
    def run():
        a = _lib_with_book(client, auth_headers, make_library, tmp_path / "A",
                           "lib-a", "A 库", "甲.epub")
        b = _lib_with_book(client, auth_headers, make_library, tmp_path / "B",
                           "lib-b", "B 库", "乙.epub")

        r = client.post("/api/opds/credentials", headers=auth_headers, json={
            "username": "reader", "pin": "1234", "label": "手机",
            "library_ids": ["lib-a"],
        })
        assert r.status_code == 200, r.text
        cred = r.json()["credential"]
        assert "pin_hash" not in cred and "pin" not in cred and cred["enabled"] is True

        h = _basic("reader", "1234")
        root = client.get("/opds", headers=h)
        assert root.status_code == 200, root.text
        # 全局书目 feed 只含 A 库那本；B 库的书不可见
        all_feed = client.get("/opds/all", headers=h)
        assert all_feed.status_code == 200, all_feed.text
        assert _titles(all_feed.text) == ["甲"]
        assert client.get("/opds/lib/lib-a", headers=h).status_code == 200
        assert client.get("/opds/lib/lib-b", headers=h).status_code == 404
        assert client.get(f"/opds/book/{b}", headers=h).status_code == 404
        assert client.get(f"/opds/cover/{b}", headers=h).status_code == 404
        assert client.get(f"/opds/download/{b}", headers=h).status_code == 404
        assert client.get(f"/opds/book/{a}", headers=h).status_code == 200
        # 只读账号进不了管理 API（/api 只认 Bearer）
        assert client.get("/api/books", headers=h).status_code == 401

        # 管理员照旧看全部
        admin = _basic("admin", "test1234")
        assert set(_titles(client.get("/opds/all", headers=admin).text)) == {"甲", "乙"}

        # 列表不含哈希
        items = client.get("/api/opds/credentials", headers=auth_headers).json()["items"]
        assert [c["username"] for c in items] == ["reader"]
        assert "pin_hash" not in items[0]

    _with_opds(run)


def test_停用_改PIN_删除_与入参校验(client, auth_headers, make_library, tmp_path):
    def run():
        _lib_with_book(client, auth_headers, make_library, tmp_path / "A",
                       "lib-a", "A 库", "甲.epub")
        r = client.post("/api/opds/credentials", headers=auth_headers, json={
            "username": "reader2", "pin": "1234", "library_ids": [],
        })
        cid = r.json()["credential"]["id"]
        # 空范围 = 全部可见库
        assert client.get("/opds", headers=_basic("reader2", "1234")).status_code == 200

        assert client.patch(f"/api/opds/credentials/{cid}", headers=auth_headers,
                            json={"enabled": False}).status_code == 200
        assert client.get("/opds", headers=_basic("reader2", "1234")).status_code == 401

        client.patch(f"/api/opds/credentials/{cid}", headers=auth_headers,
                     json={"enabled": True, "pin": "5678"})
        assert client.get("/opds", headers=_basic("reader2", "1234")).status_code == 401
        assert client.get("/opds", headers=_basic("reader2", "5678")).status_code == 200

        assert client.delete(f"/api/opds/credentials/{cid}", headers=auth_headers).status_code == 200
        assert client.get("/opds", headers=_basic("reader2", "5678")).status_code == 401

        bad = [
            {"username": "admin", "pin": "1234"},                 # 与管理员同名
            {"username": "x", "pin": "1234"},                     # 用户名太短
            {"username": "reader3", "pin": "12"},                 # PIN 太短
            {"username": "reader3", "pin": "1234", "library_ids": ["nope"]},
        ]
        for payload in bad:
            assert client.post("/api/opds/credentials", headers=auth_headers,
                               json=payload).status_code == 400, payload

    _with_opds(run)
