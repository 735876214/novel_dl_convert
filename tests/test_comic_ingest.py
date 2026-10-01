"""第 86 期：漫画「从书源下载 → 打成 CBZ」（零网络，客户端全用桩）。

盯住四件事：

1. **写出来的 CBZ 自己能读回**（`comics.pages` / `page_bytes` 是本项目读归档的唯一入口，
   写读闭环才算真的可用）；
2. **页序 = 站点给的顺序**，且**不压缩**（JPG/PNG 已压缩，deflate 只赔 CPU）；
3. **原子写**：不留 `.part`，中途失败不会留下半个打不开的归档；
4. **没有页清单就报错**，绝不产出一个 0 页的假漫画。
"""
import asyncio
import pathlib
import zipfile

import pytest

from novelforge.core import comics
from novelforge.sources import store
from novelforge.sources.manager import DownloadManager

#: 1×1 PNG（真字节，不是占位符：写进归档后要能被 `comics.page_bytes` 读回来）
PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000a49444154789c63000100000500010d0a2db40000000049454e44ae426082")


class _StubClient:
    """桩客户端：`get_text` 回书页 HTML，`get_bytes` 回图片字节并记录取过哪些地址。"""

    def __init__(self, html: str = "", blobs: dict = None):
        self.html = html
        self.blobs = blobs or {}
        self.got: list = []

    async def get_text(self, url: str) -> str:
        return self.html

    async def get_bytes(self, url: str) -> bytes:
        self.got.append(url)
        return self.blobs[url]

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


def _comic_rule(name: str = "comic-demo", domain: str = "comic-demo.com") -> dict:
    return {
        "name": name, "display_name": name, "domains": [domain], "public": False,
        "search": {"url": f"https://{domain}/s?q={{title}}", "mode": "css", "container": ".i",
                   "fields": {"title": ".t", "url": "a::attr(href)"}},
        "book": {"mode": "comic", "comic": {"mode": "css", "container": "#chap img"}},
    }


# ---------------- 写归档 ----------------

def test_写出的cbz自己能读回(tmp_path):
    dest = tmp_path / "书.cbz"
    out = comics.write_cbz(dest, [("0001.png", PNG), ("0002.png", PNG), ("0003.png", PNG)])
    assert out == dest and dest.is_file()
    assert not list(tmp_path.glob("*.part")), "原子写不该留下临时文件"

    assert comics.pages(dest)["total"] == 3, "写读闭环：本项目自己的读入口要认得这本 CBZ"
    with zipfile.ZipFile(dest) as z:
        assert [pathlib.PurePath(n).name for n in z.namelist()] == \
            ["0001.png", "0002.png", "0003.png"]
        assert z.read("0001.png") == PNG, "读回来的字节要和写进去的一致"
        assert all(z.getinfo(n).compress_type == zipfile.ZIP_STORED for n in z.namelist()), \
            "图片已压缩，再 deflate 只赔时间"


# ---------------- 页清单三通道 ----------------

def test_页清单支持三通道与懒加载():
    html = ('<div id="chap"><img src="1.jpg"><img data-src="/2.jpg">'
            '<img src="/3.jpg" data-original="/skip.jpg"></div>')
    css = rules_extract(html, {"mode": "css", "container": "#chap img"}, "https://c.com/b")
    assert css == ["https://c.com/1.jpg", "https://c.com/2.jpg", "https://c.com/3.jpg"], \
        "站点给 `data-src` 时要用它（懒加载占位图不是真页）"

    assert rules_extract('{"d": {"imgs": ["a.jpg", "b.jpg"]}}',
                        {"mode": "json", "path": "$.d.imgs"}, "https://c.com/") == \
        ["https://c.com/a.jpg", "https://c.com/b.jpg"]
    assert rules_extract('p1:<img src="x/1.jpg">p2:<img src="x/2.jpg">',
                        {"mode": "regex", "pattern": r'<img src="([^"]+)"'}, "https://c.com/") == \
        ["https://c.com/x/1.jpg", "https://c.com/x/2.jpg"]


def rules_extract(raw: str, spec: dict, base: str) -> list:
    from novelforge.sources.rules import _extract_pages
    return _extract_pages(raw, spec, base)


# ---------------- 从书源下载 ----------------

def _download(tmp_path, isolated, monkeypatch, *, html, blobs, item=None):
    store.add_rule(_comic_rule())
    monkeypatch.setattr(DownloadManager, "_client",
                        lambda self, src: _StubClient(html, blobs))
    mgr = DownloadManager({"download": {"enabled": True, "public_only": False}})
    it = item or {"title": "示例漫画", "url": "https://comic-demo.com/book/1",
                  "source": "comic-demo", "_source": "comic-demo"}
    return asyncio.run(mgr.download_comic(it, tmp_path)), mgr


def test_下载漫画落成cbz并按站点顺序(tmp_path, isolated, monkeypatch):        # noqa: ARG001
    html = ('<div id="chap"><img src="/p1.jpg"><img src="/p2.png">'
            '<img src="/img?id=3"></div>')
    blobs = {"https://comic-demo.com/p1.jpg": PNG,
             "https://comic-demo.com/p2.png": PNG,
             "https://comic-demo.com/img?id=3": PNG}
    dest, _ = _download(tmp_path, isolated, monkeypatch, html=html, blobs=blobs)
    assert dest.is_file() and dest.suffix == ".cbz"
    with zipfile.ZipFile(dest) as z:
        names = [pathlib.PurePath(n).name for n in z.namelist()]
        assert z.read(names[0]) == PNG
    assert names == ["0001.jpg", "0002.png", "0003.jpg"], \
        "页序按站点给的顺序；没有扩展名的地址兜底成 .jpg"


def test_没有图片地址就如实报错(tmp_path, isolated, monkeypatch):              # noqa: ARG001
    with pytest.raises(ValueError, match="没有给出任何图片地址"):
        _download(tmp_path, isolated, monkeypatch, html="<p>页面变了</p>", blobs={})
    assert not list(tmp_path.glob("*.cbz")), "报错时不许留下一个 0 页的假漫画"
