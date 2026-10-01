"""第 85 期：阅读顺序的「卷 / 段 → 章」分组（`core/reading_list.py` + `library._reading_list`）。

这一层此前**零直接覆盖**，而它是整个目录面板与阅读器的坐标系来源：

- 分组错 ⇒ 「有卷的书看不到卷」、卷尾的后记被塞进最后一卷；
- 标题解析链缺环 ⇒ 楔子（不在 nav/NCX 里的那些文档）一律显示成「第 3 章」；
- `index` 被顺手重排 ⇒ 阅读进度、批注、书签**全体错位**（第 65 / 73 期反复钉过，
  且 TXT 两条路线的索引空间是刻意对齐的）。

所以这里逐条钉住。全程离线：EPUB 就地手写（**可自定义 nav 与 spine** ——
`conftest._build_epub_with_assets` 的 OPF 与 spine 是写死的单章，造不出这些形态）。
"""
import pathlib
import zipfile

from novelforge.core import detect, library, reading_list

# ---------------- 最小 EPUB 构造器 ----------------

_CONTAINER = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
    '<rootfiles><rootfile full-path="OEBPS/content.opf" '
    'media-type="application/oebps-package+xml"/></rootfiles></container>'
)


def _build(root: pathlib.Path, name: str, docs: list, *, nav: str = "",
           spine: list = None) -> pathlib.Path:
    """造一本最小 EPUB。

    ``docs``：``[(文件名, <title>/<h1> 文本)]``，顺序即 manifest 顺序；
    ``nav``：``OEBPS/nav.xhtml`` 的内容（空串 = **不写目录文档**）；
    ``spine``：文件名顺序（``None`` = 与 ``docs`` 同序）—— 与目录故意错开才像真实电子书
    （封面 / 楔子这类文档常常根本不在目录里）。
    """
    root.mkdir(parents=True, exist_ok=True)
    p = root / name
    names = [f for f, _ in docs]
    order = list(spine or names)
    man = [
        f'<item id="i{n}" href="Text/{f}" media-type="application/xhtml+xml"/>'
        for n, f in enumerate(names)
    ]
    if nav:
        man.append('<item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" '
                   'properties="nav"/>')
    spine_xml = "".join(f'<itemref idref="i{names.index(f)}"/>' for f in order)
    opf = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id">'
        '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>测试书</dc:title>'
        "</metadata><manifest>" + "".join(man) + "</manifest><spine>" + spine_xml
        + "</spine></package>"
    )
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml", _CONTAINER)
        z.writestr("OEBPS/content.opf", opf)
        if nav:
            z.writestr("OEBPS/nav.xhtml", nav)
        for f, head in docs:
            z.writestr(
                f"OEBPS/Text/{f}",
                '<?xml version="1.0" encoding="utf-8"?>'
                '<html xmlns="http://www.w3.org/1999/xhtml"><head>'
                f"<title>{head}</title></head><body><h1>{head}</h1><p>正文</p></body></html>",
            )
    return p


def _nav(inner: str) -> str:
    """两/多级目录的 nav.xhtml 外壳（``inner`` 是``<li>`` 序列）。"""
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<html xmlns="http://www.w3.org/1999/xhtml" '
        'xmlns:epub="http://www.idpf.org/2007/ops"><head><title>目录</title></head><body>'
        f'<nav epub:type="toc"><ol>{inner}</ol></nav></body></html>'
    )


def _flat(groups: list) -> list:
    return [c for g in groups for c in g["chapters"]]


# ---------------- 判据（唯一真值源）----------------

def test_卷首与无编号条目判据():
    assert detect.is_volume_title("第一卷")
    assert detect.is_volume_title("第二部 风起")
    assert detect.is_volume_title("卷一 起风")
    assert not detect.is_volume_title("第一章")
    assert not detect.is_volume_title("一部分内容")          # 见 test_detect_chapters.py 的同类口径

    assert detect.is_unnumbered_title("楔子") == "front"
    assert detect.is_unnumbered_title("序章") == "front"
    assert detect.is_unnumbered_title("番外一 开始") == "back"   # 前缀判据
    assert detect.is_unnumbered_title("后记") == "back"
    assert detect.is_unnumbered_title("第一章") == ""


# ---------------- 分组（纯函数）----------------

def test_纯分组_卷前楔子与卷尾番外各自成段():
    """楔子 / 番外与卷**同级** ⇒ 各自成段，且不参与编号（用户第 85 期口径）。"""
    entries = [
        {"title": "楔子", "index": 0, "depth": 1},
        {"title": "第一卷", "index": 1, "depth": 1},
        {"title": "第一章", "index": 2, "depth": 2},
        {"title": "第二章", "index": 3, "depth": 2},
        {"title": "第二卷", "index": 4, "depth": 1},
        {"title": "第三章", "index": 5, "depth": 2},
        {"title": "番外", "index": 6, "depth": 1},
    ]
    gs = reading_list.build_reading_list(entries)
    assert [(g["volume"], g.get("kind")) for g in gs] == [
        ("", "front"), ("第一卷", None), ("第二卷", None), ("", "back"),
    ]
    assert [c.get("num") for c in gs[0]["chapters"]] == [None]          # 无编号条目不给序号
    assert [c["num"] for c in gs[1]["chapters"]] == [1, 2]
    assert [c["num"] for c in gs[2]["chapters"]] == [1]                 # 每段从 1 重新计
    assert [c.get("num") for c in gs[3]["chapters"]] == [None]
    # ⚠️ index 有**洞**（1 / 4 是卷名页，不进章节）—— 这是**改造前就有的口径**（旧实现里
    # 「卷容器」同样只当段头、不进章节），不是本期引入；动它会让进度与批注错位。
    assert [c["index"] for c in _flat(gs)] == [0, 2, 3, 5, 6]


def test_纯分组_平铺目录靠标题形态认卷():
    """卷与章同层级（很多书的 nav 就是这样）⇒ 退到标题形态，否则整本退化成一条平铺。"""
    entries = [
        {"title": "第一卷", "index": 0, "depth": 1},
        {"title": "第一章", "index": 1, "depth": 1},
        {"title": "第二章", "index": 2, "depth": 1},
        {"title": "第二卷", "index": 3, "depth": 1},
        {"title": "第三章", "index": 4, "depth": 1},
    ]
    gs = reading_list.build_reading_list(entries)
    assert [g["volume"] for g in gs] == ["第一卷", "第二卷"]
    # 标题形态认出的卷首**自己是一条可读章节**（TXT 的 index 连续性靠它）：它只是开了个新段，
    # 不像「卷容器」那样被吃掉。另一条同样重要：**卷内的章必须留在卷里**，不能被「顶层兄弟」
    # 规则弹出去各成一段 —— 平铺目录的层级里没有嵌套信息，拿它当位置用就会一章一段。
    assert [c["title"] for c in gs[0]["chapters"]] == ["第一卷", "第一章", "第二章"]
    assert [c["num"] for c in gs[1]["chapters"]] == [1, 2]
    assert [c["index"] for c in _flat(gs)] == [0, 1, 2, 3, 4]           # 一条不丢（TXT 口径）


def test_纯分组_整本平铺且没有卷时外观与改造前一致():
    entries = [{"title": f"第 {i + 1} 章", "index": i, "depth": None} for i in range(3)]
    gs = reading_list.build_reading_list(entries)
    assert len(gs) == 1 and gs[0]["volume"] == "" and "kind" not in gs[0]
    assert [c["num"] for c in gs[0]["chapters"]] == [1, 2, 3]


def test_纯分组_连着的同类无编号条目合成一段():
    entries = [
        {"title": "楔子", "index": 0, "depth": 1},
        {"title": "序章", "index": 1, "depth": 1},
        {"title": "第一卷", "index": 2, "depth": 1},
    ]
    gs = reading_list.build_reading_list(entries)
    assert [(g["volume"], g.get("kind"), len(g["chapters"])) for g in gs] == [
        ("", "front", 2), ("第一卷", None, 1),
    ]
    assert [c["index"] for c in _flat(gs)] == [0, 1, 2]


def test_目录不清楚的判据只认兜底标题():
    """「整本都是第 N 章」= 本地没标题 ⇒ 值得去书城取；**平铺长篇不算**（否则人人外呼）。"""
    fallback = [{"volume": "", "chapters": [
        {"title": f"第 {i + 1} 章", "index": i} for i in range(10)]}]
    assert reading_list.toc_unclear(fallback) is True

    normal = [{"volume": "", "chapters": [
        {"title": "楔子", "index": 0}, {"title": "第一章", "index": 1},
        {"title": "第二章", "index": 2}]}]
    assert reading_list.toc_unclear(normal) is False

    # 只有 2 章时样本太小，不下结论
    assert reading_list.toc_unclear([{"volume": "", "chapters": [
        {"title": "第 1 章", "index": 0}, {"title": "第 2 章", "index": 1}]}]) is False

    # 「第 3 章」是真书里合法标题 —— 只有它自己的序位也对得上才算兜底名
    shifted = [{"volume": "", "chapters": [
        {"title": "第 1 章", "index": 7}, {"title": "第 9 章", "index": 8},
        {"title": "第 3 章", "index": 9}]}]
    assert reading_list.toc_unclear(shifted) is False


# ---------------- EPUB 端到端（library._reading_list）----------------

def test_EPUB_两级目录_卷楔子番外都认得出(tmp_path):
    p = _build(
        tmp_path, "两级.epub",
        [("xiezi.xhtml", "楔子"), ("v1.xhtml", "第一卷"), ("c1.xhtml", "第一章"),
         ("c2.xhtml", "第二章"), ("v2.xhtml", "第二卷"), ("c3.xhtml", "第三章"),
         ("fanwai.xhtml", "番外")],
        nav=_nav(
            '<li><a href="Text/xiezi.xhtml">楔子</a></li>'
            '<li><a href="Text/v1.xhtml">第一卷</a><ol>'
            '<li><a href="Text/c1.xhtml">第一章</a></li>'
            '<li><a href="Text/c2.xhtml">第二章</a></li></ol></li>'
            '<li><a href="Text/v2.xhtml">第二卷</a><ol>'
            '<li><a href="Text/c3.xhtml">第三章</a></li></ol></li>'
            '<li><a href="Text/fanwai.xhtml">番外</a></li>',
        ),
    )
    gs = library._reading_list(p)
    assert [(g["volume"], g.get("kind")) for g in gs] == [
        ("", "front"), ("第一卷", None), ("第二卷", None), ("", "back"),
    ]
    # 1 / 4（两页卷名页）不进章节：层级判出的「卷容器」就是段头本身（改造前口径）
    assert [c["index"] for c in _flat(gs)] == [0, 2, 3, 5, 6]


def test_EPUB_楔子不在目录里时标题来自文档自身(tmp_path):
    """这是被修掉的主症状：nav 没列楔子 ⇒ 它此前一律显示成「第 1 章」。"""
    p = _build(
        tmp_path, "缺条目.epub",
        [("xiezi.xhtml", "楔子"), ("v1.xhtml", "第一卷"), ("c1.xhtml", "第一章")],
        nav=_nav(
            '<li><a href="Text/v1.xhtml">第一卷</a><ol>'
            '<li><a href="Text/c1.xhtml">第一章</a></li></ol></li>',
        ),
    )
    gs = library._reading_list(p)
    assert gs[0]["chapters"][0]["title"] == "楔子"      # 不是「第 1 章」
    assert gs[0].get("kind") == "front"


def test_EPUB_没有目录文档时不抛且逐条有标题(tmp_path):
    p = _build(
        tmp_path, "无目录.epub",
        [("a.xhtml", "序章"), ("b.xhtml", "第一章")],
        nav="",
    )
    gs = library._reading_list(p)
    assert [c["title"] for c in _flat(gs)] == ["序章", "第一章"]
    assert [c["index"] for c in _flat(gs)] == [0, 1]
    # 无目录 ⇒ 章节数不足，不该判「目录不清楚」而去外呼
    assert reading_list.toc_unclear(gs) is False
