"""nav.xhtml 的插入位置（第 87 期收尾加固）。

一个 `nav.xhtml` 里可以有**多个** `<ol>`：`landmarks` / `page-list` 若排在
`epub:type="toc"` 之前，按「第一个 `</ol>`」插入会把新章链接放进「地标」列表 ——
阅读器的目录里根本看不到，而「nav 里含这条链接」的断言**照样会过**：
典型的静默插错位置。所以必须先定位目录那个 `<nav>`。

零网络。
"""
from xml.etree import ElementTree as ET

from novelforge.core import epub_update

NAV_TWO_LISTS = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:epub="http://www.idpf.org/2007/ops">
  <body>
    <nav epub:type="landmarks" id="landmarks">
      <ol><li><a href="c0000.xhtml">正文</a></li></ol>
    </nav>
    <nav epub:type="toc" id="toc">
      <ol><li><a href="c0000.xhtml">第一章</a></li></ol>
    </nav>
  </body>
</html>
"""


def test_地标列表在前时新章仍插进目录列表():
    out = epub_update.add_nav_link(NAV_TWO_LISTS, href="c0001.xhtml", title="第二章")
    toc_at = out.find('epub:type="toc"')
    new_at = out.find('href="c0001.xhtml"')
    assert toc_at != -1 and new_at > toc_at, "新章要落在目录那个 <nav> 之后"
    landmarks = out[out.find('epub:type="landmarks"'):toc_at]
    assert "c0001.xhtml" not in landmarks, "不许插进 landmarks（阅读器目录里看不到）"
    ET.fromstring(out)                       # 仍是合法 XML


def test_认不出目录块时退回旧口径且仍可用():
    """没有 `epub:type="toc"` 的老结构：退回「第一个 `</ol>`」，至少有得用、不报错。"""
    nav = ('<html xmlns:epub="http://www.idpf.org/2007/ops"><body>'
           "<nav><ol><li><a href='c0000.xhtml'>一</a></li></ol></nav></body></html>")
    out = epub_update.add_nav_link(nav, href="c0001.xhtml", title="二")
    assert 'href="c0001.xhtml"' in out and out.count("</ol>") == 1


def test_只有目录列表时行为不变():
    """最常见的形态（只有一个 `<ol>`）：加固不能改变既有行为。"""
    nav = ('<html xmlns:epub="http://www.idpf.org/2007/ops"><body>'
           '<nav epub:type="toc" id="toc"><ol>'
           '<li><a href="c0000.xhtml">一</a></li>'
           "</ol></nav></body></html>")
    out = epub_update.add_nav_link(nav, href="c0001.xhtml", title="二")
    assert out.index('href="c0000.xhtml"') < out.index('href="c0001.xhtml"')
    assert out.rstrip().endswith("</html>")
