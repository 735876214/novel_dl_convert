"""不可信 XML 的实体膨胀防护（第 292 期）。

## 为什么要有这份测试

项目解析的外部 XML（EPUB 的 container/OPF/SMIL、FB2、播客 RSS、OPML、上传的 SVG）全是
**不可信输入**。stdlib `xml.etree.ElementTree` 的「放大比」保护**可以被稀释**：实测同一份
「10^5 实体 × 100 引用」的炸弹，743 B 输入会被拦；在 DOCTYPE 后**垫 1 MB 注释**（放大比
降到 30 倍）就放行，3 秒展开 30 MB。而 zip 条目上限是 128 MB、RSS 上限 8 MB —— 一份精心
构造的书 / 订阅就能在自动扫描时把进程内存打爆。

判据收敛到 `core/xmlsafe.py`：**含 `<!ENTITY` 的内部实体声明一律拒绝**（正常 EPUB / RSS /
OPML / FB2 不需要自定义实体；外部 DTD 引用不受影响）。这里钉住：

1. 判据与输入大小无关（垫大输入也拦）；
2. 正常 XML / 预定义实体 / 外部 DTD 不受影响；
3. 六个解析入口真的都走 `xmlsafe`（源码级契约，防以后又冒出一处裸解析）。
"""
from __future__ import annotations

import pathlib
import xml.etree.ElementTree as ET

import pytest

from novelforge.core import customicons, fb2cache, podcasts, xmlsafe

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _bomb(levels: int = 6, refs: int = 50, pad: str = "", root: str = "r") -> str:
    """内部实体膨胀炸弹：10^5 个 lol × refs 次引用；pad 用来稀释「输出/输入」比。"""
    ents = ['<!ENTITY e0 "lol">']
    for i in range(1, levels):
        ents.append('<!ENTITY e%d "%s">' % (i, ("&e%d;" % (i - 1)) * 10))
    return ('<?xml version="1.0"?><!DOCTYPE %s [%s]>%s<%s>%s</%s>'
            % (root, "".join(ents), pad, root, ("&e%d;" % (levels - 1)) * refs, root))


def test_拒绝内部实体声明() -> None:
    with pytest.raises(ET.ParseError) as ei:
        xmlsafe.fromstring(_bomb())
    assert "实体" in str(ei.value), str(ei.value)


def test_普通_XML_与预定义实体照常解析() -> None:
    root = xmlsafe.fromstring("<r><a>1 &amp; 2 &lt; 3</a></r>")
    assert root.find("a").text == "1 & 2 < 3"


def test_外部_DTD_引用不受影响() -> None:
    """`<!DOCTYPE … PUBLIC …>` 没有内部实体声明 —— 正常 EPUB2 / 网页常见形态。"""
    root = xmlsafe.fromstring('<!DOCTYPE r PUBLIC "-//X//DTD" "x.dtd"><r>ok</r>')
    assert root.text == "ok"


def test_垫大输入也拦得住() -> None:
    """判据必须与输入大小无关 —— 只靠放大比的保护会被「垫注释」稀释。"""
    bomb = _bomb(pad="<!--%s-->" % ("x" * 200_000))
    assert len(bomb) > 200_000
    with pytest.raises(ET.ParseError):
        xmlsafe.fromstring(bomb)


def test_播客_RSS_拒绝实体炸弹订阅() -> None:
    with pytest.raises(ValueError) as ei:
        podcasts.parse_feed(_bomb())
    assert "实体" in str(ei.value), str(ei.value)


def test_OPML_拒绝实体炸弹() -> None:
    with pytest.raises(ValueError) as ei:
        podcasts.opml_import(_bomb())
    assert "实体" in str(ei.value), str(ei.value)


def test_上传_SVG_拒绝实体炸弹() -> None:
    svg = _bomb().replace("<r>", "<svg><g>").replace("</r>", "</g></svg>")
    with pytest.raises(ValueError) as ei:
        customicons.parse_svg(svg)
    assert "实体" in str(ei.value), str(ei.value)


def test_FB2_拒绝实体炸弹() -> None:
    assert fb2cache._parse(_bomb()) is None


#: 六处解析入口（`xmlsafe` 之外不许直接 `ET.fromstring`）。
_XML_MODULES = (
    "novelforge/core/customicons.py",
    "novelforge/core/epub_cfi.py",
    "novelforge/core/fb2cache.py",
    "novelforge/core/podcasts.py",
    "novelforge/core/publish.py",
    "novelforge/core/readaloud.py",
)


@pytest.mark.parametrize("rel", _XML_MODULES)
def test_解析入口都走_xmlsafe(rel: str) -> None:
    """源码级契约：这些模块里不许再出现 `ET.fromstring(`（唯一入口是 xmlsafe）。"""
    text = (ROOT / rel).read_text(encoding="utf-8")
    assert "ET.fromstring(" not in text, (
        f"{rel} 又出现了裸 `ET.fromstring(` —— 不可信 XML 必须走 `core/xmlsafe.py`")
    assert "xmlsafe" in text, f"{rel} 没有接 `xmlsafe`"
