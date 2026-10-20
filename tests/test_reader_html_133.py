"""第 133 期：书里的 HTML 不许在阅读器里执行。

**问题**：阅读器把整章 HTML `v-html` 进页面（同源），而这段 HTML 的来源是**书**：
EPUB 的章节体本来就原样照发，TXT / MOBI 的兜底路径还把章节标题裸拼进 `<h2>`。
于是「下载来的一本书」里的 `<script>` / `onerror=` / `javascript:` 就成了应用自己的脚本 ——
能读登录 token、能以用户身份调接口。

四条口径：
1. `novelforge.core.htmlsafe.sanitize` 是**唯一**判据：删能执行的节点与属性，保留正文结构；
2. 章节接口发出去的 html 里不许出现 `<script` / `on…=` / `javascript:`；
3. 正文一个字符都不许丢（`<p>a<script>x</script>b</p>` 里的 `a` `b` 都要在）；
4. 标题（来自书里的行）必须转义 —— 我们拼 `<h2>` 时不能把书名 / 章名当代码写进页面。
"""
from __future__ import annotations

import pathlib

import pytest

from novelforge.core import htmlsafe, library, txtcache


def _craft_epub(dst: pathlib.Path, *, body: str, title: str = "脚本注入书") -> pathlib.Path:
    """造一本「章节体里带危险 HTML」的 EPUB（不经 epub_builder —— 它会净化，那就测不到了）。"""
    from ebooklib import epub

    book = epub.EpubBook()
    book.set_identifier("xss-epub")
    book.set_title(title)
    book.set_language("zh")
    ch = epub.EpubHtml(title="第一章", file_name="c1.xhtml", lang="zh")
    ch.content = f"<html><body>{body}</body></html>"
    book.add_item(ch)
    book.toc = (ch,)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = ["nav", ch]
    dst.parent.mkdir(parents=True, exist_ok=True)     # ebooklib 不建父目录（找不到就吞掉 OSError）
    epub.write_epub(str(dst), book)
    return dst


def _bid(name: str) -> str:
    library.invalidate()
    all_books = library.books(force=True)
    books = [b for b in all_books if b["name"] == name]
    assert books, f"扫描没找到 {name}；现有：{[b['name'] for b in all_books]}"
    return books[0]["id"]


# ---------------------------------------------------------------- 判据单元

def test_sanitize_删掉能执行的节点与属性():
    src = (
        "<p onmouseover=\"alert(1)\">正文</p>"
        "<script>alert(2)</script>"
        "<iframe src=\"https://evil\"></iframe>"
        "<object data=\"x\"></object>"
        "<embed src=\"x\">"
        "<p><a href=\"javascript:alert(3)\">链接</a></p>"
        "<p><img src=\"/api/books/x/asset?p=y\" onerror=\"alert(4)\"/></p>"
        "<base href=\"https://evil/\">"
    )
    out = htmlsafe.sanitize(src)
    low = out.lower()
    for bad in ("<script", "<iframe", "<object", "<embed", "<base", "onmouseover", "onerror",
                "javascript:"):
        assert bad not in low, f"{bad} 还在：{out}"
    # 结构和正文都在
    assert "正文" in out
    assert "链接" in out
    assert 'src="/api/books/x/asset?p=y"' in out


def test_sanitize_正文一个字都不丢():
    out = htmlsafe.sanitize("<p>a<script>zz</script>b<iframe src=x></iframe>c</p>")
    assert out == "<p>abc</p>", out


def test_sanitize_保留正常排版与自闭合():
    src = ('<h2>第一章</h2><p class="subtitle">小标题</p><p>甲 &amp; 乙 <em>斜体</em></p>'
           '<br/><p><img src="/api/x?p=1"/></p>')
    out = htmlsafe.sanitize(src)
    assert '<h2>第一章</h2>' in out
    assert 'class="subtitle"' in out
    assert "&amp;" in out and "<em>斜体</em>" in out
    assert "<br/>" in out and '<img src="/api/x?p=1"/>' in out


def test_sanitize_纯文本与坏HTML都不放行标签():
    assert htmlsafe.sanitize("没有标签") == "没有标签"
    assert htmlsafe.sanitize("") == ""
    # 畸形输入：解析器会把 `<span<script>` 复原成一个**名字怪异的标签**，黑名单按名字查会漏
    # ⇒ 允许清单下它降级成 `<span>`，脚本内容变成普通文字（不执行，也不丢）
    out = htmlsafe.sanitize("<p>未闭合 <div><span<script>alert(1)</script>")
    assert "<script" not in out.lower(), out
    assert "alert(1)" in out, out


def test_heading_必须转义():
    out = htmlsafe.heading('<img src=x onerror="alert(1)">')
    assert out.startswith("<h2>&lt;img src=x")
    assert "onerror" in out and "<img" not in out.replace("&lt;img", "")
    assert htmlsafe.heading(None) == "<h2></h2>"
    assert htmlsafe.heading("第一章") == "<h2>第一章</h2>"


# ---------------------------------------------------------------- 真路径

def test_EPUB章节接口不再照发script(client, auth_headers, isolated, default_root):  # noqa: ARG001
    body = ('<h1>第一章</h1>'
            '<script>alert(document.domain)</script>'
            '<p onmouseover="alert(1)">正文一</p>'
            '<p><img src="x" onerror="alert(2)"/></p>'
            '<p><a href="javascript:alert(3)">链接</a></p>')
    _craft_epub(pathlib.Path(default_root) / "脚本注入书.epub", body=body)
    bid = _bid("脚本注入书.epub")

    r = client.get(f"/api/books/{bid}/chapter/1", headers=auth_headers)

    assert r.status_code == 200, r.text
    html = r.json()["html"]
    low = html.lower()
    for bad in ("<script", "onmouseover", "onerror", "javascript:"):
        assert bad not in low, f"{bad} 还在：{html}"
    # 正文与链接文字仍在（净化不是「整章丢了」）
    assert "正文一" in html
    assert "链接" in html


def test_正常EPUB正文不受影响(client, auth_headers, isolated, default_root):  # noqa: ARG001
    body = ('<h2>第一章</h2><p>甲 &amp; 乙</p><p class="x"><em>斜体</em> <strong>粗体</strong></p>'
            '<blockquote><p>引语</p></blockquote>')
    _craft_epub(pathlib.Path(default_root) / "正常书.epub", body=body)
    bid = _bid("正常书.epub")

    html = client.get(f"/api/books/{bid}/chapter/1", headers=auth_headers).json()["html"]

    assert "<h2>第一章</h2>" in html
    assert "甲 &amp; 乙" in html
    assert "<em>斜体</em>" in html and "<strong>粗体</strong>" in html
    assert "<blockquote>" in html


def test_TXT兜底路径的章标题被转义(isolated, default_root, make_book):  # noqa: ARG001
    # 缩进分章：顶格行 = 章标题（原样取自书里那一行）
    make_book(default_root, "标题注入.txt",
              '<img src=x onerror="alert(1)">\n　　正文A\n'.encode())
    bid = _bid("标题注入.txt")
    book = library.by_id(bid)
    path = pathlib.Path(default_root) / "标题注入.txt"

    out = txtcache.native_chapter_html(book, 0, path=path, root=default_root)

    assert out["html"].startswith("<h2>&lt;img src=x")
    assert "onerror" in out["html"]          # 作为文本被转义，不是属性
    assert "<img" not in out["html"]
    assert "正文A" in out["html"]


def test_MOBI兜底路径的章标题被转义():
    mobicache = pytest.importorskip("novelforge.core.mobicache")
    src = pathlib.Path(mobicache.__file__).read_text(encoding="utf-8")
    # 判据只有一处：这条路径也必须走 htmlsafe.heading（别在第二处手拼 <h2>）
    assert "htmlsafe.heading(title)" in src
    assert 'f"<h2>{title}</h2>"' not in src


def test_章节缓存的键带上净化版本(isolated, default_root, make_book, monkeypatch):  # noqa: ARG001
    """源文件没动、净化判据变了 ⇒ 旧缓存不许继续下发。

    章节 HTML 进 Redis（键 = 书 + 章 + 源文件指纹），而指纹只看源文件。所以判据版本
    必须并进键 —— 否则「修了净化但读的人还是旧 HTML」能持续一整个 TTL（24 h）。
    """
    from novelforge import server

    make_book(default_root, "缓存键.txt", "第一行\n　　正文\n".encode())
    bid = _bid("缓存键.txt")
    path = pathlib.Path(default_root) / "缓存键.txt"

    seen: list[str] = []
    monkeypatch.setattr(server.cache, "chapter_key",
                        lambda b, i, fp, kind="epub": seen.append(fp) or f"k:{fp}")
    monkeypatch.setattr(server.cache, "get_json", lambda key: None)
    monkeypatch.setattr(server.cache, "set_json", lambda key, val, ttl: None)

    server._chapter_cached(bid, 0, path, "native", lambda: {"html": "<p>x</p>"})

    assert seen, "没走到缓存键"
    assert seen[0].endswith(f":h{htmlsafe.CHAPTER_HTML_VERSION}")
