"""第 135 期：媒体出口的安全头**只在一处组装**（F4 在第 134 期留下的九处残留）。

第 134 期只给 `/api/books/{bid}/asset` 与封面两处加了
`X-Content-Type-Options: nosniff` + `Content-Security-Policy: sandbox`，其余出口
（合集封面 / 原始书籍文件 / 漫画页 / 音频轨 / 序号单元 / 作者头像 / 账号头像 /
字体 / Komga 页面流）都没带 —— 这些出口的媒体类型同样由**后缀或书里的声明**推出，
一份书内 SVG 被顶层导航打开就能读走 `localStorage.nf_token`。

判据分两层：
1. **静态**：三个头只许出现在 `_MEDIA_UNTRUSTED_HEADERS` 里，出口一律走 helper；
2. **运行时**：每一族出口（内存字节 / 磁盘文件）都真的带上了这三个头。
"""
import pathlib
import re

from novelforge import config, server
from novelforge.core import comics

REPO = pathlib.Path(__file__).resolve().parents[1]
SERVER_SRC = (REPO / "novelforge" / "server.py").read_text(encoding="utf-8")

#: 1×1 PNG（真字节：要能当漫画页 / 头像被读回来）
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082")


def _h(r) -> dict:
    return {k.lower(): v for k, v in r.headers.items()}


def _assert_untrusted_media(r, *, cache: str = "public, max-age=86400") -> None:
    h = _h(r)
    assert h.get("content-security-policy") == "sandbox", h
    assert h.get("x-content-type-options") == "nosniff", h
    assert h.get("cache-control") == cache, h


def _first_book(client, auth_headers, fmt: str) -> str:
    rows = client.get("/api/books", headers=auth_headers).json()
    rows = rows["items"] if isinstance(rows, dict) else rows
    return next(b["id"] for b in rows if b.get("format") == fmt)


# ---------------------------------------------------------------------------
# 静态：单一真值源
# ---------------------------------------------------------------------------

def test_安全头只有一处组装点():
    """三个头只许写在 `_MEDIA_UNTRUSTED_HEADERS` 里，出口一律走 helper。

    这一条就是 F4 的防回归判据：第 134 期的错不是「忘了加」，而是「同一判据写在
    两处、于是第三处一定漏」。
    """
    assert SERVER_SRC.count('"Content-Security-Policy": "sandbox"') == 1
    assert SERVER_SRC.count('"X-Content-Type-Options": "nosniff"') == 1
    # 定义 + helper 里 `dict(...)` 复制一次，就这两处
    assert SERVER_SRC.count("_MEDIA_UNTRUSTED_HEADERS") == 2


def test_媒体出口不自己拼缓存头():
    bad = re.findall(r'headers=\{"Cache-Control": "(?:public|private)[^}]*\}', SERVER_SRC)
    assert bad == [], f"这些出口绕开了 _media_headers：{bad}"


def test_媒体头helper可覆盖缓存口径():
    h = server._media_headers("private, max-age=3600")
    assert h["Cache-Control"] == "private, max-age=3600"
    # 覆盖的是**副本**：模块常量不能被调用方改脏
    assert server._MEDIA_UNTRUSTED_HEADERS["Cache-Control"] == "public, max-age=86400"
    assert server._MEDIA_UNTRUSTED_HEADERS["Content-Security-Policy"] == "sandbox"


# ---------------------------------------------------------------------------
# 运行时：内存字节出口
# ---------------------------------------------------------------------------

def test_漫画封面与漫画页都带安全头(client, auth_headers, default_root):
    """漫画封面 / 漫画页的媒体类型来自**书里的页**，是 F4 的原始风险面。"""
    comics.write_cbz(default_root / "测试漫画.cbz", [("0001.png", PNG)])
    bid = _first_book(client, auth_headers, "CBZ")

    r = client.get(f"/api/books/{bid}/cover", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert _h(r).get("content-type", "").startswith("image/")
    _assert_untrusted_media(r)

    r = client.get(f"/api/books/{bid}/comic/0", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert _h(r).get("content-type", "").startswith("image/")
    _assert_untrusted_media(r)


def test_书内资源仍带安全头(client, auth_headers, make_library, make_epub):
    """第 134 期已修的那一处，跟着收敛到 helper 之后不能回退。"""
    root = pathlib.Path(config.LIBRARY_SOURCE_ROOTS[0]["path"]) / "media-headers"
    make_library("lib-media-headers", "素材库", "ebook", root)
    make_epub(root, "插图.epub")
    bid = next(b["id"] for b in client.get("/api/books", headers=auth_headers).json()["items"]
               if b["name"] == "插图.epub")
    tok = auth_headers["Authorization"][7:]

    r = client.get(f"/api/books/{bid}/asset?p=OEBPS/Images/pic.png&token={tok}")
    assert r.status_code == 200, r.text
    assert _h(r).get("content-type") == "image/png"
    _assert_untrusted_media(r)


# ---------------------------------------------------------------------------
# 运行时：磁盘文件出口
# ---------------------------------------------------------------------------

def test_原始书籍文件带安全头且仍是私有缓存(client, auth_headers, default_root, make_book):
    """`/file` 是整本书的字节流（pdf.js 用 fetch 读，不受 CSP 影响）。

    缓存口径**故意**与其它出口不同：书是「有权限才该被缓存」的，走 private。
    """
    make_book(default_root, "原始文件.txt", "正文".encode())
    bid = _first_book(client, auth_headers, "TXT")

    r = client.get(f"/api/books/{bid}/file", headers=auth_headers)
    assert r.status_code == 200, r.text
    _assert_untrusted_media(r, cache="private, max-age=3600")


def test_字体与账号头像带安全头(client, auth_headers):
    """两处都是 `FileResponse`：媒体的字节来自**上传件**，类型只由后缀决定。"""
    data = b"\x00\x01\x00\x00" + b"\x00" * 64          # 只要后缀是 .ttf 就能存
    r = client.post("/api/fonts", headers=auth_headers,
                    files={"file": ("测试字体.ttf", data, "font/ttf")})
    assert r.status_code == 200, r.text
    fid = r.json()["id"]

    r = client.get(f"/api/fonts/{fid}/file", headers=auth_headers)
    assert r.status_code == 200, r.text
    _assert_untrusted_media(r)

    r = client.post("/api/account/avatar", headers=auth_headers,
                    files={"file": ("a.png", PNG, "image/png")})
    assert r.status_code == 200, r.text

    r = client.get("/api/account/avatar", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert _h(r).get("content-type") == "image/png"
    _assert_untrusted_media(r)
