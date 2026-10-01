"""第 86 期第 6 步：新章要在 OPF / nav / NCX 三处「登记」的落点（纯函数，零网络）。

为什么单独测这三处：少登记一处，表现是「新章抓下来了、文件也在包里，但读者翻不到它（或
目录里看不见）」—— 从现象几乎无法反推是哪一处漏了。所以先用真 EPUB 把**三处的锚点**验死：
① 锚点确实存在（拿真产物断言，不靠记忆）；② 插完仍是合法 XML；③ 既有内容一字不动。
"""
import pathlib
import xml.etree.ElementTree as ET
import zipfile

from novelforge.core import epub_builder, epub_update


def _build(tmp_path: pathlib.Path, n: int = 2) -> tuple:
    p = tmp_path / "书.epub"
    epub_builder.build_epub(
        {"title": "登记测试", "author": "某人", "language": "zh"},
        [{"title": f"第 {i} 章", "body_html": f"<p>{i}</p>"} for i in range(1, n + 1)],
        str(p))
    with zipfile.ZipFile(p) as z:
        return p, {name: z.read(name).decode("utf-8")
                   for name in ("EPUB/content.opf", "EPUB/nav.xhtml", "EPUB/toc.ncx")}


def test_三个锚点在真产物里都存在(tmp_path):
    """**先钉锚点**：锚点猜错的话，后面三个函数的测试全都会「过」，而实际什么都没插。"""
    _, files = _build(tmp_path)
    assert "</manifest>" in files["EPUB/content.opf"] and "</spine>" in files["EPUB/content.opf"]
    assert "</ol>" in files["EPUB/nav.xhtml"]
    assert "</navMap>" in files["EPUB/toc.ncx"]


def test_三处登记都插进去且仍是合法xml(tmp_path):
    _, files = _build(tmp_path)
    opf = epub_update.add_spine_itemref(
        epub_update.add_manifest_item(files["EPUB/content.opf"],
                                      href="c0002.xhtml", item_id="chapter_2"),
        item_id="chapter_2")
    nav = epub_update.add_nav_link(files["EPUB/nav.xhtml"], href="c0002.xhtml", title="第 3 章")
    ncx = epub_update.add_ncx_navpoint(files["EPUB/toc.ncx"], href="c0002.xhtml",
                                       title="第 3 章", play_order=3)
    # ① 真的写进去了
    assert '<item href="c0002.xhtml" id="chapter_2"' in opf
    assert '<itemref idref="chapter_2"/>' in opf
    assert '<li><a href="c0002.xhtml">第 3 章</a></li>' in nav
    assert '<content src="c0002.xhtml"/>' in ncx and 'playOrder="3"' in ncx
    # ② 插完仍是合法 XML（字符串手术最容易把标签搞乱）
    for text in (opf, nav, ncx):
        ET.fromstring(text)
    # ③ spine 里新章在**末尾**（既有章节顺序不变 ⇒ 阅读数据 index 不漂移）
    assert opf.index('idref="chapter_1"') < opf.index('idref="chapter_2"')


def test_锚点缺失时响亮报错(tmp_path):
    """**不许静默无动作**：条目照样追加、包照样生成、读者翻不到 —— 那是最坏的失败形态。"""
    import pytest
    for fn, kw in ((epub_update.add_manifest_item, {"href": "a.xhtml", "item_id": "x"}),
                   (epub_update.add_spine_itemref, {"item_id": "x"}),
                   (epub_update.add_nav_link, {"href": "a.xhtml", "title": "t"}),
                   (epub_update.add_ncx_navpoint, {"href": "a.xhtml", "title": "t",
                                                   "play_order": 1})):
        with pytest.raises(ValueError, match="结构不符合预期"):
            fn("<html>没有那个锚点</html>", **kw)


def test_登记后的三处能配合copy_with_extra一起用(tmp_path):
    """端到端的小闭环：三处重写 + 新章入包，其余条目一字不动。"""
    src, files = _build(tmp_path)
    dst = tmp_path / "out.epub"
    opf = epub_update.add_spine_itemref(
        epub_update.add_manifest_item(files["EPUB/content.opf"],
                                      href="c0002.xhtml", item_id="chapter_2"),
        item_id="chapter_2")
    epub_update.copy_with_extra(
        src, dst,
        extra=[("EPUB/c0002.xhtml", "<p>第 3 章</p>".encode())],
        replace={"EPUB/content.opf": opf.encode(),
                 "EPUB/nav.xhtml": epub_update.add_nav_link(
                     files["EPUB/nav.xhtml"], href="c0002.xhtml", title="第 3 章").encode(),
                 "EPUB/toc.ncx": epub_update.add_ncx_navpoint(
                     files["EPUB/toc.ncx"], href="c0002.xhtml", title="第 3 章",
                     play_order=3).encode()})
    assert epub_update.verify_unchanged(
        src, dst, added={"EPUB/c0002.xhtml"},
        replaced={"EPUB/content.opf", "EPUB/nav.xhtml", "EPUB/toc.ncx"}) == [], \
        "除三处登记 + 新章之外，其余条目必须一字不动"
    with zipfile.ZipFile(dst) as z:
        assert z.read("EPUB/c0002.xhtml") == "<p>第 3 章</p>".encode()
        ET.fromstring(z.read("EPUB/content.opf"))
