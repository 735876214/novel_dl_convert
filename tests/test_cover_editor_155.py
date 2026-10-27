"""封面编辑器（第 155 期）：上传 / URL / 移除。

只落服务端 DB —— 上传成功后 GET 必须回同一份字节；删掉后必须回退（而不是 500）。
"""
from __future__ import annotations

import io
import pathlib


def _png() -> bytes:
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (8, 8), (200, 30, 30)).save(buf, "PNG")
    return buf.getvalue()


def _bid(client, auth_headers, make_library, make_epub, tmp_path: pathlib.Path) -> str:
    root = tmp_path / "cover-lib"
    make_library("cover-lib", "封面库", "ebook", root)
    make_epub(root, "封面书.epub")
    items = client.get("/api/books", headers=auth_headers).json()["items"]
    return next(b["id"] for b in items if b["name"] == "封面书.epub")


def test_上传封面后读到同一份字节_移除后回退(client, auth_headers, make_library,
                                              make_epub, tmp_path):
    bid = _bid(client, auth_headers, make_library, make_epub, tmp_path)
    data = _png()
    r = client.post(f"/api/books/{bid}/cover", headers=auth_headers,
                    files={"file": ("c.png", data, "image/png")})
    assert r.status_code == 200, r.text
    assert r.json()["media_type"] == "image/png"

    g = client.get(f"/api/books/{bid}/cover", headers=auth_headers)
    assert g.status_code == 200
    assert g.content == data

    d = client.delete(f"/api/books/{bid}/cover", headers=auth_headers)
    assert d.status_code == 200, d.text
    assert d.json()["removed"] is True
    # 回退到内嵌封面（make_epub 带 pic.png）；不再等于上传的那份
    g2 = client.get(f"/api/books/{bid}/cover", headers=auth_headers)
    assert g2.status_code in (200, 404)
    if g2.status_code == 200:
        assert g2.content != data


def test_非法上传与非法_URL(client, auth_headers, make_library, make_epub, tmp_path):
    bid = _bid(client, auth_headers, make_library, make_epub, tmp_path)
    r = client.post(f"/api/books/{bid}/cover", headers=auth_headers,
                    files={"file": ("x.jpg", b"not-an-image", "image/jpeg")})
    assert r.status_code == 400, r.text

    for url in ("file:///etc/passwd", "http://127.0.0.1:1/a.png", "ftp://x/a.png"):
        r = client.post(f"/api/books/{bid}/cover/url", headers=auth_headers,
                        json={"url": url})
        assert r.status_code == 400, (url, r.text)

    assert client.post("/api/books/不存在/cover", headers=auth_headers,
                       files={"file": ("c.png", _png(), "image/png")}).status_code == 404
