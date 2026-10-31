"""PDF 大纲 / 文内搜索（第 195 期）。"""
from __future__ import annotations

import pathlib
from types import SimpleNamespace

from novelforge import config
from novelforge.core import pdfsearch


class _Dest:
    def __init__(self, i):
        self.i = i

    def get_index(self):
        return self.i


class _BM:
    def __init__(self, title, page, level=0):
        self.title = title
        self.page = page
        self.level = level

    def get_title(self):
        return self.title

    def get_dest(self):
        return _Dest(self.page)


class _Text:
    def __init__(self, text):
        self.text = text

    def get_text_range(self):
        return self.text

    def close(self):
        pass


class _Page:
    def __init__(self, text):
        self.text = text

    def get_textpage(self):
        return _Text(self.text)

    def close(self):
        pass


class _Doc:
    def __init__(self, pages, toc):
        self.pages = pages
        self.toc = toc

    def __len__(self):
        return len(self.pages)

    def __getitem__(self, i):
        return _Page(self.pages[i])

    def get_page(self, i):
        return _Page(self.pages[i])

    def get_toc(self):
        return self.toc

    def close(self):
        pass


def _fake(pages, toc):
    doc = _Doc(pages, toc)

    class _Mod:
        PdfDocument = staticmethod(lambda path: doc)

    return SimpleNamespace(pdfium=_Mod)


def test_pdf大纲与搜索(monkeypatch):
    mod = _fake(
        ["第一页 深海里的鱼", "第二页 潮汐", "第三页 没有关键词"],
        [_BM("第一章", 0), _BM("第一节", 1, level=1)],
    )
    monkeypatch.setattr(pdfsearch, "_pdfium", lambda: mod.pdfium)
    assert pdfsearch.outline("x.pdf") == [
        {"title": "第一章", "page": 1, "level": 0},
        {"title": "第一节", "page": 2, "level": 1},
    ]
    r = pdfsearch.search("x.pdf", "潮汐")
    assert r["total"] == 1 and r["scanned"] == 3
    assert r["items"][0]["page"] == 2 and "潮汐" in r["items"][0]["snippet"]
    assert pdfsearch.search("x.pdf", "不存在")["items"] == []


def test_pdf搜索入参与依赖缺失(monkeypatch):
    mod = _fake(["a"], [])
    monkeypatch.setattr(pdfsearch, "_pdfium", lambda: mod.pdfium)
    try:
        pdfsearch.search("x.pdf", "")
    except ValueError as e:
        assert "不能为空" in str(e)
    else:
        raise AssertionError("空搜索词应当 400")

    def _missing():
        raise ValueError("服务器缺少 PDF 解析能力（需 pypdfium2）")

    monkeypatch.setattr(pdfsearch, "_pdfium", _missing)
    try:
        pdfsearch.outline("x.pdf")
    except ValueError as e:
        assert "pypdfium2" in str(e)
    else:
        raise AssertionError("缺依赖时应当如实报错")


def test_pdf端点(client, auth_headers, make_library, monkeypatch):
    root = pathlib.Path(config.LIBRARY_SOURCE_ROOTS[0]["path"]) / "pdfsearch"
    make_library("lib-pdf", "PDF 库", "ebook", root)
    (root / "文档.pdf").write_bytes(b"%PDF-1.4 fake")
    cards = client.get("/api/books", headers=auth_headers).json()["items"]
    bid = next(b["id"] for b in cards if b["name"] == "文档.pdf")

    monkeypatch.setattr("novelforge.server.pdfsearch.outline",
                        lambda p: [{"title": "第一章", "page": 1, "level": 0}])
    monkeypatch.setattr("novelforge.server.pdfsearch.search",
                        lambda p, q, limit: {"items": [{"page": 1, "snippet": q,
                                                        "offset": 0, "match": q}],
                                             "total": 1, "truncated": False,
                                             "scanned": 1, "query": q})
    assert client.get(f"/api/books/{bid}/pdf/outline",
                      headers=auth_headers).json()["items"][0]["title"] == "第一章"
    r = client.get(f"/api/books/{bid}/pdf/search", params={"q": "潮汐"}, headers=auth_headers)
    assert r.json()["items"][0]["match"] == "潮汐"
    assert client.get("/api/books/nope/pdf/outline", headers=auth_headers).status_code == 404
