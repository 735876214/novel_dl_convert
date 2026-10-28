"""M4B 内嵌章节（第 171 期）：`moov/udta/chpl` 解析与接口。

钉住：
- 起始时间是 **100 纳秒**单位，出口统一成毫秒；
- 只读 `moov`（按 box 头 seek），不整文件读；
- 没有 `chpl` / 不是 M4B ⇒ 空列表（不按大小硬切），接口对非有声书 400、不存在 404。
"""
from __future__ import annotations

import pathlib

from novelforge.core import m4b


def _box(typ: str, payload: bytes) -> bytes:
    return (len(payload) + 8).to_bytes(4, "big") + typ.encode("latin-1") + payload


def _chpl(entries: list, version: int = 0) -> bytes:
    payload = bytes([version]) + b"\x00\x00\x00"
    if version == 1:
        payload += b"\x00\x00\x00\x00"
    payload += bytes([len(entries)])
    for start_ms, title in entries:
        t = title.encode("utf-8")
        payload += (start_ms * 10000).to_bytes(8, "big") + bytes([len(t)]) + t
    return _box("chpl", payload)


def _m4b(path: pathlib.Path, entries: list, version: int = 0) -> pathlib.Path:
    moov = _box("moov", _box("udta", _chpl(entries, version)))
    data = _box("ftyp", b"M4B \x00\x00\x00\x00") + moov + _box("mdat", b"x" * 64)
    path.write_bytes(data)
    return path


def test_章节解析_100纳秒转毫秒(tmp_path):
    p = _m4b(tmp_path / "书.m4b", [(0, "第一章"), (65000, "第二章")])
    assert m4b.chapters(p) == [
        {"title": "第一章", "start_ms": 0},
        {"title": "第二章", "start_ms": 65000},
    ]
    # 第二次走缓存，结果一致
    assert m4b.chapters(p) == m4b.chapters(p)


def test_版本1与缺章节(tmp_path):
    p = _m4b(tmp_path / "v1.m4b", [(1500, "开场")], version=1)
    assert m4b.chapters(p) == [{"title": "开场", "start_ms": 1500}]

    # 没有 chpl ⇒ 空（不猜）
    plain = tmp_path / "plain.m4b"
    plain.write_bytes(_box("ftyp", b"M4B ") + _box("moov", _box("udta", b"")))
    assert m4b.chapters(plain) == []
    # 非 M4B 扩展名 / 目录 ⇒ 空
    other = tmp_path / "book.mp3"
    other.write_bytes(b"ID3")
    assert m4b.chapters(other) == []
    assert m4b.chapters(tmp_path) == []


def test_接口(client, auth_headers, make_library, make_epub, tmp_path):
    root = tmp_path / "audio"
    make_library("audio", "有声书库", "audiobook", root)
    _m4b(root / "单文件.m4b", [(0, "第一章"), (30000, "第二章")])
    assert client.post("/api/libraries/audio/scan", headers=auth_headers).status_code == 200
    items = client.get("/api/books", headers=auth_headers).json()["items"]
    bid = next(b["id"] for b in items if b["name"] == "单文件.m4b")
    r = client.get(f"/api/books/{bid}/audio/chapters", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.json()["supported"] is True
    assert [c["title"] for c in r.json()["items"]] == ["第一章", "第二章"]

    ebook_root = tmp_path / "ebook"
    make_library("ebook", "电子书库", "ebook", ebook_root)
    make_epub(ebook_root, "普通书.epub")
    assert client.post("/api/libraries/ebook/scan", headers=auth_headers).status_code == 200
    ebid = next(b["id"] for b in client.get("/api/books", headers=auth_headers).json()["items"]
                if b["name"] == "普通书.epub")
    assert client.get(f"/api/books/{ebid}/audio/chapters", headers=auth_headers).status_code == 400
    assert client.get("/api/books/不存在/audio/chapters", headers=auth_headers).status_code == 404
