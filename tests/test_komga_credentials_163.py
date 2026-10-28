"""Komga 兼容层的只读客户端凭据（第 163 期）：与第 160 期 OPDS 同一张表、同一套范围判据。

钉住五条：

- 只读凭据能用 HTTP Basic 读 `/api/v1`（Komga 客户端），但**看不到范围外**的库
  （库列表 / 系列列表 / 书列表过滤、单书 404）；
- 管理员账号 / API Key / 会话令牌不受范围限制（默认零变化）；
- 停用立即生效；范围外的书按 id 直连也 404（不是藏起来）；
- `verify()` 旧签名不变（返回 str），带范围的是 `verify_scoped()`；
- 只读账号进不了 `/api/*`（该前缀只认 Bearer）—— 上一期已钉，这里只验 Komga 侧。
"""
from __future__ import annotations

import base64
import pathlib

from novelforge import config


def _basic(user: str, pin: str) -> tuple:
    token = base64.b64encode(f"{user}:{pin}".encode()).decode()
    return ("Authorization", f"Basic {token}")


def _lib_with_book(client, auth_headers, make_library, root: pathlib.Path,
                   lid: str, name: str, book: str) -> str:
    root.mkdir(parents=True, exist_ok=True)
    (root / book).write_bytes(b"EPUB")
    make_library(lid, name, "ebook", root)
    assert client.post(f"/api/libraries/{lid}/scan", headers=auth_headers).status_code == 200
    items = client.get("/api/books", headers=auth_headers).json()["items"]
    return next(b["id"] for b in items if b["name"] == book)


def _with_komga(fn):
    config.save_overrides({"komga": {"enabled": True, "username": "admin", "api_key": ""}})
    try:
        fn()
    finally:
        config.save_overrides({})


def test_只读凭据限定书库_管理员不受影响(client, auth_headers, make_library, tmp_path):
    def run():
        a = _lib_with_book(client, auth_headers, make_library, tmp_path / "A",
                           "klib-a", "A 库", "甲.epub")
        b = _lib_with_book(client, auth_headers, make_library, tmp_path / "B",
                           "klib-b", "B 库", "乙.epub")

        r = client.post("/api/opds/credentials", headers=auth_headers, json={
            "username": "komga-reader", "pin": "1234", "library_ids": ["klib-a"],
        })
        assert r.status_code == 200, r.text

        headers = dict([_basic("komga-reader", "1234")])
        # 库列表只含 A；B 对客户端不存在
        libs = client.get("/api/v1/libraries", headers=headers)
        assert libs.status_code == 200, libs.text
        ids = {l["id"] for l in libs.json()}
        assert "klib-a" in ids and "klib-b" not in ids
        # 书列表只含 A 库那本；B 库的书按 id 直连也 404
        books = client.get("/api/v1/books", headers=headers)
        assert books.status_code == 200, books.text
        assert {bk["name"] for bk in books.json()["content"]} == {"甲.epub"}
        assert client.get(f"/api/v1/books/{b}/file", headers=headers).status_code == 404
        assert client.get(f"/api/v1/books/{a}/file", headers=headers).status_code == 200

        # 管理员不受影响
        admin = dict([_basic("admin", "test1234")])
        admin_libs = client.get("/api/v1/libraries", headers=admin).json()
        # `default` 是单库时代的兜底常量，多书库下仍会出现在列表尾（见 library_dto）
        assert {"klib-a", "klib-b"} <= {l["id"] for l in admin_libs}

    _with_komga(run)


def test_停用立即生效_会话与APIKey不受范围限制(client, auth_headers, make_library, tmp_path):
    def run():
        _lib_with_book(client, auth_headers, make_library, tmp_path / "A",
                       "klib-a", "A 库", "甲.epub")
        r = client.post("/api/opds/credentials", headers=auth_headers, json={
            "username": "k-reader", "pin": "1234", "library_ids": [],
        })
        cid = r.json()["credential"]["id"]
        headers = dict([_basic("k-reader", "1234")])
        assert client.get("/api/v1/libraries", headers=headers).status_code == 200

        assert client.patch(f"/api/opds/credentials/{cid}", headers=auth_headers,
                            json={"enabled": False}).status_code == 200
        assert client.get("/api/v1/libraries", headers=headers).status_code == 401

        # API Key 不受范围限制（它本来就是管理员侧凭据）
        config.save_overrides({"komga": {"enabled": True, "username": "admin", "api_key": "k-123"}})
        try:
            h = {"X-API-Key": "k-123"}
            assert client.get("/api/v1/libraries", headers=h).status_code == 200
        finally:
            config.save_overrides({"komga": {"enabled": True, "username": "admin", "api_key": ""}})

    _with_komga(run)
