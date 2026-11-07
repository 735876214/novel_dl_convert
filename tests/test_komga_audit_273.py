"""Komga 持续审计第 1 轮（第 273 期）：格式面 + 一条自相矛盾的人话。

这一轮扫了三个角度，两个零发现（**别重查**）：

- **大库性能**（1200 本）：`/api/v1/books?size=20` 45 ms、`size=500` 87 ms、
  `/series?size=20` 43 ms —— 与应用自己的 `/api/books?limit=20`（42 ms）同量级，
  第 266 期收口之后**没有剩下的 O(全书库)**。
- **三出口「读完」一致性**：Komga `completed` / 应用 `percent` / KOReader `percentage`
  三者互通（Komga 标完成、应用读到 100%、KOReader 推到 100%，任一路径后另两处立刻正确）。

两条发现：

1. **PDF 在客户端里没有封面**。`api_book_cover` 对 PDF 落到最后那句「该格式没有内嵌封面」
   ⇒ 404，而 Komga 对**任何按页渲染的格式**都拿第 1 页当封面（PDF 正是这一类）⇒
   客户端里 PDF 只有一块占位色。
2. **`EntryTooLarge` 的人话自相矛盾**：`read_capped` 读到 `limit + 1` 就停，
   于是 128 MiB 上限下文案是「这个条目解压后有 128.0 MB，**超过上限 128.0 MB**」——
   同一句话里两个相同的数字。走 Komga 的 `/resource` 与应用 `/asset` 都能看到。
"""
import io
import zipfile

import pytest

from novelforge import config
from novelforge.core import comics, epub_builder, library


@pytest.fixture
def komga_on():
    config.save_overrides({"komga": {"enabled": True, "username": "admin",
                                     "api_key": "test-key"}})
    try:
        yield {"X-API-Key": "test-key"}
    finally:
        config.save_overrides({})


def _pdf(path, pages: int = 3):
    from PIL import Image
    path.parent.mkdir(parents=True, exist_ok=True)
    imgs = [Image.new("RGB", (60, 80), (i * 30, 0, 0)) for i in range(pages)]
    imgs[0].save(path, save_all=True, append_images=imgs[1:])
    return path


# ---------------------------------------------------------------- 1. PDF 封面

def test_PDF_有封面且与页流同一条渲染路(client, auth_headers, make_library,
                                  tmp_path, komga_on):
    root = tmp_path / "P"
    root.mkdir(parents=True, exist_ok=True)
    make_library("P", "PDF 库", "ebook", root)
    _pdf(root / "书.pdf")
    client.post("/api/scan", headers=auth_headers)
    library.invalidate()

    b = client.get("/api/v1/books?size=5", headers=komga_on).json()["content"][0]
    assert b["media"]["mediaProfile"] == "PDF"
    cover = client.get("/api/v1/books/" + b["id"] + "/thumbnail", headers=komga_on)
    assert cover.status_code == 200, f"PDF 没有封面：{cover.status_code} {cover.text[:80]}"
    assert cover.headers["content-type"].startswith("image/")
    assert len(cover.content) > 0

    # 同一张首面：`/pages/1` 走的是同一条 `pdfrender.render_page(path, 0, bid)`
    page = client.get("/api/v1/books/" + b["id"] + "/pages/1", headers=komga_on)
    assert page.status_code == 200
    assert page.content == cover.content, "封面与首面不是同一张（两条渲染路会漂）"


def test_PDF_封面也走应用自己的封面接口(client, auth_headers, make_library, tmp_path):
    """封面判据只有一处：Komga 与前端拿到的必须是同一张。"""
    root = tmp_path / "P2"
    root.mkdir(parents=True, exist_ok=True)
    make_library("P2", "PDF 库", "ebook", root)
    _pdf(root / "书2.pdf")
    client.post("/api/scan", headers=auth_headers)
    library.invalidate()
    rows = client.get("/api/books", headers=auth_headers).json()["items"]
    bid = next(b["id"] for b in rows if b.get("format") == "PDF")
    r = client.get("/api/books/" + bid + "/cover", headers=auth_headers)
    assert r.status_code == 200 and r.headers["content-type"].startswith("image/")


# ---------------------------------------------------------------- 2. 人话不自相矛盾

def test_超限文案不报一个自己也不知道的体积():
    e = comics.EntryTooLarge("big.bin", comics.MAX_ENTRY_BYTES + 1, comics.MAX_ENTRY_BYTES)
    msg = str(e)
    assert "超过上限" in msg, msg                      # 既有用例靠这个子串
    assert "解压后有" not in msg, f"还是在报一个没读出来的体积：{msg}"
    # 具体体积仍然可以**给程序用**，只是不进人话
    assert e.size == comics.MAX_ENTRY_BYTES + 1 and e.limit == comics.MAX_ENTRY_BYTES


def test_解压炸弹在两条出口都被挡住(client, auth_headers, make_library, tmp_path, komga_on):
    """同一个闸门：Komga 的 `/resource` 与应用自己的 `/asset` 都是 413。"""
    root = tmp_path / "B"
    root.mkdir(parents=True, exist_ok=True)
    make_library("B", "库", "ebook", root)
    p = root / "书.epub"
    p.parent.mkdir(parents=True, exist_ok=True)
    epub_builder.build_epub({"title": "书", "author": "a", "language": "zh"},
                            [{"title": "第一章", "body_html": "<p>x</p>"}], str(p))
    with zipfile.ZipFile(p, "a", zipfile.ZIP_DEFLATED) as z:
        with z.open("big.bin", "w") as fp:
            chunk = b"\x00" * (1 << 20)
            for _ in range(200):            # 解压后 200 MB，压缩后很小
                fp.write(chunk)
    client.post("/api/scan", headers=auth_headers)
    library.invalidate()
    b = client.get("/api/v1/books?size=5", headers=komga_on).json()["content"][0]

    komga = client.get("/api/v1/books/" + b["id"] + "/resource/big.bin", headers=komga_on)
    assert komga.status_code == 413, komga.status_code
    assert "超过上限" in komga.text

    app = client.get("/api/books/" + b["id"] + "/asset?p=big.bin", headers=auth_headers)
    assert app.status_code == 413, app.status_code
    assert "超过上限" in app.text
