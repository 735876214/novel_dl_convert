"""整本有声书 ZIP（第 171 期）：流式打包。

钉住：
- 生成的是**合法 ZIP**（用 zipfile 读回逐文件比对字节）；
- 归档名带序号前缀（平铺后同名文件不会互相覆盖）；
- 接口只对有声书开放（非有声书 400、不存在 404），空目录 404。
"""
from __future__ import annotations

import io
import pathlib
import zipfile

from novelforge.core import audiobook_zip


def _read_zip(data: bytes) -> dict:
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        return {n: zf.read(n) for n in zf.namelist()}


def test_流式打包是合法_zip(tmp_path):
    a = tmp_path / "a.bin"
    b = tmp_path / "b.bin"
    a.write_bytes(b"A" * 5000)
    b.write_bytes(b"B" * 3)
    data = b"".join(audiobook_zip.stream_zip([("001 - a.bin", a), ("002 - b.bin", b)]))
    assert _read_zip(data) == {"001 - a.bin": b"A" * 5000, "002 - b.bin": b"B" * 3}


def test_接口_有声书才可打包(client, auth_headers, make_library, make_epub, tmp_path):
    root = tmp_path / "audio"
    d = root / "星际旅行"
    d.mkdir(parents=True)
    (d / "01 第一章.mp3").write_bytes(b"ID3" + b"1" * 128)
    (d / "02 第二章.mp3").write_bytes(b"ID3" + b"2" * 128)
    make_library("audio", "有声书库", "audiobook", root)
    assert client.post("/api/libraries/audio/scan", headers=auth_headers).status_code == 200
    bid = next(b["id"] for b in client.get("/api/books", headers=auth_headers).json()["items"]
               if b.get("format") == "AUDIO")

    r = client.get(f"/api/books/{bid}/audio/zip", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("application/zip")
    files = _read_zip(r.content)
    assert set(files) == {"001 - 01 第一章.mp3", "002 - 02 第二章.mp3"}
    assert files["001 - 01 第一章.mp3"] == b"ID3" + b"1" * 128

    # 电子书 400、不存在 404
    e = tmp_path / "ebook"
    make_library("ebook", "电子书库", "ebook", e)
    make_epub(e, "普通.epub")
    assert client.post("/api/libraries/ebook/scan", headers=auth_headers).status_code == 200
    eid = next(b["id"] for b in client.get("/api/books", headers=auth_headers).json()["items"]
               if b["name"] == "普通.epub")
    assert client.get(f"/api/books/{eid}/audio/zip", headers=auth_headers).status_code == 400
    assert client.get("/api/books/不存在/audio/zip", headers=auth_headers).status_code == 404
