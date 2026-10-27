"""书库直传上传（第 157 期）：浏览器文件直接落该库的内容来源目录。

钉住四条边界（都是「坏了会静默」的那类）：

- 落点 = 库的**第一个来源目录**，文件名按 `fileops.sanitize_stem` 清洗（`../` 不许逃逸）；
- 扩展名必须被该库收录（否则文件在盘上、书目里却看不见）；
- **绝不覆盖**同名文件（冲突走 `x (2).epub`）；
- 空文件拒收、不存在的库 404、逐文件回执带原因。
"""
from __future__ import annotations

import pathlib


def _epub_bytes(make_epub, tmp_path: pathlib.Path) -> bytes:
    src_root = tmp_path / "seed"
    src_root.mkdir()
    p = make_epub(src_root, "种子.epub")
    return pathlib.Path(p).read_bytes()


def test_上传落库_冲突退让_扫描后可见(client, auth_headers, make_library, make_epub, tmp_path):
    root = tmp_path / "up-lib"
    make_library("up-lib", "直传库", "ebook", root)
    data = _epub_bytes(make_epub, tmp_path)

    r = client.post("/api/libraries/up-lib/upload", headers=auth_headers,
                    files={"files": ("上传书.epub", data, "application/epub+zip")})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["saved"] == 1 and body["items"][0]["status"] == "ok"
    assert (root / "上传书.epub").read_bytes() == data

    # 同名再传一次：绝不覆盖，退让成 `上传书 (2).epub`
    r2 = client.post("/api/libraries/up-lib/upload", headers=auth_headers,
                     files={"files": ("上传书.epub", data, "application/epub+zip")})
    assert r2.status_code == 200, r2.text
    assert r2.json()["items"][0]["saved_as"] == "上传书 (2).epub"
    assert (root / "上传书 (2).epub").exists()

    # 上传**不**自己扫描（扫描只有一条流水）；调用既有扫描端点后书才进书目
    scan = client.post("/api/libraries/up-lib/scan", headers=auth_headers)
    assert scan.status_code == 200, scan.text
    names = {b["name"] for b in client.get("/api/books", headers=auth_headers).json()["items"]}
    assert "上传书.epub" in names


def test_拒收与清理(client, auth_headers, make_library, tmp_path):
    root = tmp_path / "bad-lib"
    make_library("bad-lib", "拒收库", "ebook", root)

    r = client.post("/api/libraries/bad-lib/upload", headers=auth_headers,
                    files=[("files", ("木马.exe", b"MZ", "application/octet-stream")),
                           ("files", ("空.epub", b"", "application/epub+zip"))])
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["saved"] == 0
    reasons = {it["name"]: it["reason"] for it in body["items"]}
    assert "不收录" in reasons["木马.exe"]
    assert "空文件" in reasons["空.epub"]
    assert not list(root.iterdir()), "被拒的文件一个字节都不许落盘"

    # 路径成分只留 basename：`../` 不会逃出库根
    r2 = client.post("/api/libraries/bad-lib/upload", headers=auth_headers,
                     files={"files": ("../../逃逸.epub", b"x", "application/epub+zip")})
    assert r2.status_code == 200, r2.text
    assert r2.json()["items"][0]["saved_as"] == "逃逸.epub"
    assert (root / "逃逸.epub").exists()
    assert not (tmp_path / "逃逸.epub").exists()

    assert client.post("/api/libraries/不存在/upload", headers=auth_headers,
                       files={"files": ("a.epub", b"x", "application/epub+zip")}).status_code == 404
