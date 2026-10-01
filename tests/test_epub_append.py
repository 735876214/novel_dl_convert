"""第 86 期第 6 步：`append_chapters` —— 追更的落点（零网络，真 EPUB 夹具）。

这是「只追加」这条硬约束的**实现处**，所以验收标准是：
① 既有章节的**编号、顺序、内容**一字不动（阅读数据 index 不漂移）；
② 新章在**三处**都登记到了（否则读者翻不到）；
③ 原地更新是**原子**的（失败不留半个文件）。
"""
import pathlib
import xml.etree.ElementTree as ET
import zipfile

from novelforge.core import epub_builder, epub_update


def _build(tmp_path: pathlib.Path, n: int = 2) -> pathlib.Path:
    p = tmp_path / "书.epub"
    epub_builder.build_epub(
        {"title": "追更测试", "author": "某人", "language": "zh"},
        [{"title": f"第 {i} 章", "body_html": f"<p>正文 {i}</p>"} for i in range(1, n + 1)],
        str(p))
    return p


def test_追加两章且既有章节一字不动(tmp_path):
    src = _build(tmp_path)
    import shutil
    before = tmp_path / "before.epub"
    shutil.copyfile(src, before)

    out = epub_update.append_chapters(src, [
        {"title": "第 3 章", "body_html": "<p>新正文 3</p>"},
        {"title": "第 4 章", "body_html": "<p>新正文 4</p>"},
    ])
    assert out["start_index"] == 2 and out["added"] == ["EPUB/c0002.xhtml", "EPUB/c0003.xhtml"]
    assert out["path"] == src, "追更是**原地更新**那本书"

    problems = epub_update.verify_unchanged(
        before, src, added=set(out["added"]),
        replaced={"EPUB/content.opf", "EPUB/nav.xhtml", "EPUB/toc.ncx"})
    assert problems == [], f"既有条目必须一字不动，实际：{problems}"


def test_新章在三处都登记到了(tmp_path):
    src = _build(tmp_path)
    epub_update.append_chapters(src, [{"title": "第 3 章", "body_html": "<p>x</p>"}])
    with zipfile.ZipFile(src) as z:
        opf = z.read("EPUB/content.opf").decode("utf-8")
        nav = z.read("EPUB/nav.xhtml").decode("utf-8")
        ncx = z.read("EPUB/toc.ncx").decode("utf-8")
        chapter = z.read("EPUB/c0002.xhtml").decode("utf-8")
        names = z.namelist()
    # ① OPF：manifest 登记 + spine 追加在既有章节之后
    assert '<item href="c0002.xhtml" id="chapter_2"' in opf
    assert '<itemref idref="chapter_2"/>' in opf
    assert opf.index('idref="chapter_1"') < opf.index('idref="chapter_2"')
    # ② 两个目录（EPUB3 的 nav 与 EPUB2 的 NCX）都要有，否则一半阅读器看不到
    assert '<a href="c0002.xhtml">第 3 章</a>' in nav
    assert '<content src="c0002.xhtml"/>' in ncx
    # ③ 文件本体
    assert names[-1] == "EPUB/c0002.xhtml"
    assert "第 3 章" in chapter and "<p>x</p>" in chapter
    for text in (opf, nav, ncx, chapter):
        ET.fromstring(text), "插完必须仍是合法 XML"


def test_连追两次编号接着走(tmp_path):
    src = _build(tmp_path)
    epub_update.append_chapters(src, [{"title": "第 3 章", "body_html": "<p>3</p>"}])
    out = epub_update.append_chapters(src, [{"title": "第 4 章", "body_html": "<p>4</p>"}])
    assert out["start_index"] == 3 and out["added"] == ["EPUB/c0003.xhtml"], \
        "第二次追更要接着既有最大章号往下编，不能从 0 重来（会覆盖旧章）"
    with zipfile.ZipFile(src) as z:
        assert "EPUB/c0003.xhtml" in z.namelist()


def test_没有新章就原样返回(tmp_path):
    src = _build(tmp_path)
    before = src.read_bytes()
    out = epub_update.append_chapters(src, [])
    assert out["added"] == [] and src.read_bytes() == before, "没有新章不该碰文件"


def test_不是标准结构就拒绝改(tmp_path):
    import pytest
    bad = tmp_path / "bad.epub"
    with zipfile.ZipFile(bad, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("EPUB/c0000.xhtml", "<html/>")
    with pytest.raises(ValueError, match="找不到 OPF"):
        epub_update.append_chapters(bad, [{"title": "x", "body_html": "<p>y</p>"}])
    assert bad.read_bytes()[:2] == b"PK", "拒绝改的时候不许动源文件"


def test_新章模板与既有章一致(tmp_path):
    """同书两种模板会被某些阅读器区别对待，所以新章要照既有章的样式生成。"""
    src = _build(tmp_path)
    with zipfile.ZipFile(src) as z:
        old = z.read("EPUB/c0000.xhtml").decode("utf-8")
    epub_update.append_chapters(src, [{"title": "第 3 章", "body_html": "<p>x</p>"}])
    with zipfile.ZipFile(src) as z:
        new = z.read("EPUB/c0002.xhtml").decode("utf-8")
    head = "<?xml version='1.0' encoding='utf-8'?>"
    tag = '<html xmlns="http://www.w3.org/1999/xhtml"'
    assert old.startswith(head) and new.startswith(head)
    assert tag in old and tag in new
    assert old.count("<h2>") == new.count("<h2>"), "标题层级要一致"
