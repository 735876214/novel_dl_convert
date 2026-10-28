"""有声书「已听」轨标记（第 168 期）：由 `reading_sessions.file_rel` 派生。

钉住四条：
- 只有 `source='audio'` 的会话算数（文本阅读器同样写 `file_rel`，不能混进来）；
- 同一轨多次会话只出现一次；空 `file_rel`（单文件书）不产生条目；
- 非有声书 400、不存在的书 404；
- 没有手动标记接口 —— 数据只来自真实会话。
"""
from __future__ import annotations

import pathlib


def _audio_book(client, auth_headers, make_library, root: pathlib.Path) -> str:
    d = root / "星际旅行"
    d.mkdir(parents=True, exist_ok=True)
    (d / "01 第一章.mp3").write_bytes(b"ID3" + b"\x00" * 16)
    (d / "02 第二章.mp3").write_bytes(b"ID3" + b"\x01" * 16)
    make_library("audio", "有声书库", "audiobook", root)
    assert client.post("/api/libraries/audio/scan", headers=auth_headers).status_code == 200
    items = client.get("/api/books", headers=auth_headers).json()["items"]
    return next(b["id"] for b in items if b.get("format") == "AUDIO")


def _session(client, auth_headers, bid: str, *, file_rel: str, source: str = "audio") -> None:
    r = client.post(f"/api/books/{bid}/session", headers=auth_headers, json={
        "seconds": 30, "source": source, "file_rel": file_rel,
        "start_percent": 10, "end_percent": 20,
    })
    assert r.status_code == 200, r.text


def test_已听轨由音频会话派生(client, auth_headers, make_library, tmp_path):
    bid = _audio_book(client, auth_headers, make_library, tmp_path / "audio-root")
    assert client.get(f"/api/books/{bid}/audio/heard", headers=auth_headers).json()["items"] == []

    _session(client, auth_headers, bid, file_rel="02 第二章.mp3")
    _session(client, auth_headers, bid, file_rel="02 第二章.mp3")   # 同一轨两次 ⇒ 仍一条
    # 同一本书的**文本来源**会话（file_rel 为库内相对路径）不得混进「已听轨」
    _session(client, auth_headers, bid, file_rel="星际旅行/01 第一章.mp3", source="web")
    # 空 file_rel（单文件书语义）也不产生条目
    _session(client, auth_headers, bid, file_rel="")

    body = client.get(f"/api/books/{bid}/audio/heard", headers=auth_headers).json()
    assert body["items"] == ["02 第二章.mp3"]
    assert body["total"] == 1


def test_非有声书与坏_id(client, auth_headers, make_library, make_epub, tmp_path):
    root = tmp_path / "ebook-root"
    make_library("ebook", "电子书库", "ebook", root)
    make_epub(root, "普通书.epub")
    assert client.post("/api/libraries/ebook/scan", headers=auth_headers).status_code == 200
    bid = next(b["id"] for b in client.get("/api/books", headers=auth_headers).json()["items"]
               if b["name"] == "普通书.epub")
    assert client.get(f"/api/books/{bid}/audio/heard", headers=auth_headers).status_code == 400
    assert client.get("/api/books/不存在/audio/heard", headers=auth_headers).status_code == 404
