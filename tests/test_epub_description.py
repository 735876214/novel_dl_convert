"""`dc:description` 的**解码口径**契约（来自第 100 期的真实语料实测）。

## 为什么单开一个文件

`dc:description` 在真实 OPF 里**常常是双写转义的 HTML 片段**。实测 30 本
Standard Ebooks 真实书（37 本语料里含 OPF 的那 30 本）：

- `title` / `creator` / `publisher` / `language` 与真 XML 解析器**逐字相同（0/30 不一致）**；
- **`description` 30/30 本都不一致**，且 `html.unescape(旧结果) == 真解析器结果` **逐字成立**
  —— 差异**唯一**就是「旧实现不解 HTML 实体」。

OPF 里写的是 ``&lt;p&gt;In the &lt;i&gt;Treatise…``（双写转义），真解析器解**一次**得 ``<p>In the <i>…``，
而旧实现原样返回 ⇒ 界面上直接露出 ``&lt;p&gt;`` 字面量。

⚠️ **用户可见**：`probe_epub` 把未解码的串直接写进 DB，前端又用 ``{{ }}`` **文本插值**渲染
`BookPreviewDialog.vue:310` / `detail/OverviewTab.vue:112` —— 浏览器**不会**再解一次实体。

## 口径（两条，用户 2026-10-05 拍板）

1. **解一次 HTML 实体**（``&lt;`` → ``<``）；用标准库 :func:`html.unescape`，
   手写对照表会漏（`core/metasources.py:493` 已记过同样的教训）。
2. **保留标签** —— 不许再套 `re.sub(r"<[^>]+>", "", …)`。
   解出来的 ``<p>`` / ``<i>`` / ``<a>`` 是**描述本身的内容**（description 在很多源里
   本就是 HTML 片段）；剥了就丢信息。这与 `dc:title` 这类**纯文本字段**的处理刚好相反。

⚠️ **顺序不可颠倒**：先剥标签再解实体，``&lt;p&gt;`` 会被当成文本留下；
先解实体再剥标签，刚解出的真标签立刻被吃掉。所以只 unescape，**不**剥标签。

与在线源口径的对齐点是「实体已解」这一步本身：``core/metasources.py`` 抓来的描述
也做了 :func:`html.unescape`（它额外剥标签是因为它拿到的是**网页**、标签是站点模板）。
"""
import pathlib
import zipfile

from novelforge.core import library

_CONTAINER = """<?xml version="1.0" encoding="utf-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""


def _epub_with_opf(root, opf: str, name: str = "书.epub") -> pathlib.Path:
    """按给定 OPF 原文造一本最小 EPUB。"""
    p = pathlib.Path(root) / name
    p.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml", _CONTAINER)
        z.writestr("OEBPS/content.opf", opf)
        z.writestr("OEBPS/Text/chapter1.xhtml",
                   '<html xmlns="http://www.w3.org/1999/xhtml"><body><p>正文</p></body></html>')
    return p


def _opf_with_description(desc: str) -> str:
    return ('<?xml version="1.0" encoding="utf-8"?>'
            '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id">'
            '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
            '<dc:title>书名</dc:title>'
            '<dc:creator>作者</dc:creator>'
            f'<dc:description>{desc}</dc:description>'
            '</metadata>'
            '<manifest><item id="c1" href="Text/chapter1.xhtml" '
            'media-type="application/xhtml+xml"/></manifest>'
            '<spine><itemref idref="c1"/></spine>'
            '</package>')


def test_双写转义的HTML片段解一次实体(tmp_path, isolated):                 # noqa: ARG001
    """本文件的核心契约：``&lt;p&gt;`` → ``<p>``（解**一次**，不是两次）。

    这是真实语料里 30/30 本的实际写法（Standard Ebooks 把 HTML 片段双写转义进 OPF）。
    """
    opf = _opf_with_description('&lt;p&gt;In the &lt;i&gt;Treatise&lt;/i&gt;, written in 1739.&lt;/p&gt;')
    out = library.probe_epub(_epub_with_opf(tmp_path, opf))

    assert out["description"] == "<p>In the <i>Treatise</i>, written in 1739.</p>"
    assert "&lt;" not in out["description"], "不许再把实体字面量暴露给界面"
    assert "&lt;p&gt;" not in out["description"], "不许解两次（会得到 `&lt;p&gt;` 的字面量残留）"


def test_标签必须保留不许剥掉(tmp_path, isolated):                         # noqa: ARG001
    """口径第 2 条：解出来的真标签**是描述的内容**，剥了就丢信息。

    `dc:title` 走的是 `_tag_text`（会剥标签）—— 那条路是给**纯文本字段**的，
    description 不能复用（这正是它单独一个函数的原因）。
    """
    opf = _opf_with_description('&lt;p&gt;带&lt;b&gt;粗体&lt;/b&gt;的描述&lt;/p&gt;')
    out = library.probe_epub(_epub_with_opf(tmp_path, opf))

    assert out["description"] == "<p>带<b>粗体</b>的描述</p>"
    assert "<b>" in out["description"], "`<b>` 是描述本身的内容，不许被剥掉"


def test_纯文本描述原样保留(tmp_path, isolated):                           # noqa: ARG001
    """没有实体的描述不该被改动（解实体对它是恒等变换）。"""
    opf = _opf_with_description("一本很普通的书，没有任何标记。")
    out = library.probe_epub(_epub_with_opf(tmp_path, opf))

    assert out["description"] == "一本很普通的书，没有任何标记。"


def test_命名实体与数字实体都解得开(tmp_path, isolated):                   # noqa: ARG001
    """``&amp;`` / ``&#8212;`` 这类也要解 —— 只处理 ``&lt;``/``&gt;`` 是不够的。

    ⚠️ ``&nbsp;`` **不在这一条里**：它在 XML 里是**未定义实体**（HTML 才有），
    真解析器会当硬错误。本函数跑在正则路径上、拿得到原文，所以能解 ——
    但这是「比真解析器宽容」，不是契约，故不在此断言。
    """
    opf = _opf_with_description("Tom &amp; Jerry &#8212; 一部漫画")
    out = library.probe_epub(_epub_with_opf(tmp_path, opf))

    assert out["description"] == "Tom & Jerry \u2014 一部漫画"


def test_没有description字段时为空串(tmp_path, isolated):                 # noqa: ARG001
    """缺失字段仍然是空串（不能变成 ``None`` —— 调用方按下标取用）。"""
    opf = ('<?xml version="1.0" encoding="utf-8"?>'
           '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id">'
           '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
           '<dc:title>只有书名</dc:title></metadata>'
           '<manifest><item id="c1" href="Text/chapter1.xhtml" '
           'media-type="application/xhtml+xml"/></manifest>'
           '<spine><itemref idref="c1"/></spine></package>')
    out = library.probe_epub(_epub_with_opf(tmp_path, opf))

    assert out["description"] == ""
    assert out["title"] == "只有书名"


def test_前缀别名也读得到(tmp_path, isolated):                             # noqa: ARG001
    """🔴 回归钉：Dublin Core 被声明成**别的别名**时，描述**不许静默变空**。

    野生 EPUB 里有 ``xmlns:dc1="http://purl.org/dc/elements/1.1/"`` + ``<dc1:description>``
    这种写法。旧实现走 ``_tag_text(opf, "dc:description")`` 时按**调用点传进来的标签名**
    匹配，本来就认；若把新函数的正则写死成 ``dc:``，这类书的描述会**静默变成空串**
    —— 正是本文件最忌讳的失败模式（丢了不报错，只表现为「这本书没有简介」）。

    ⚠️ 前缀大小写也要认（`re.I`），与 `_tag_text` 保持一致。
    """
    opf = ('<?xml version="1.0" encoding="utf-8"?>'
           '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id">'
           '<metadata xmlns:dc1="http://purl.org/dc/elements/1.1/">'
           '<dc1:title>别名书名</dc1:title>'
           '<dc1:description>&lt;p&gt;别名前缀的描述&lt;/p&gt;</dc1:description>'
           '</metadata>'
           '<manifest><item id="c1" href="Text/chapter1.xhtml" '
           'media-type="application/xhtml+xml"/></manifest>'
           '<spine><itemref idref="c1"/></spine></package>')
    out = library.probe_epub(_epub_with_opf(tmp_path, opf))

    assert out["description"] == "<p>别名前缀的描述</p>", "前缀别名也读得到，且实体照解"


def test_其他字段不受影响(tmp_path, isolated):                             # noqa: ARG001
    """🔴 回归钉：只改了 description 一条路，别的字段**必须逐字不变**。

    真实语料实测：title / creator / publisher / language 与真 XML 解析器
    **0/30 不一致** ⇒ 它们本来就是对的不许被这次修改波及。
    """
    opf = ('<?xml version="1.0" encoding="utf-8"?>'
           '<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id">'
           '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
           '<dc:title>书名 &amp; 副标题</dc:title>'
           '<dc:creator>作者甲</dc:creator>'
           '<dc:publisher>出版社</dc:publisher>'
           '<dc:language>zh</dc:language>'
           '<dc:description>&lt;p&gt;描述&lt;/p&gt;</dc:description>'
           '</metadata>'
           '<manifest><item id="c1" href="Text/chapter1.xhtml" '
           'media-type="application/xhtml+xml"/></manifest>'
           '<spine><itemref idref="c1"/></spine></package>')
    out = library.probe_epub(_epub_with_opf(tmp_path, opf))

    assert out["description"] == "<p>描述</p>", "描述解了实体"
    # ⚠️ title 走 `_tag_text`（剥标签、**不解**实体）—— 这是**既有**行为，本次没改它：
    #    真实语料里 title 与真解析器 0/30 不一致，说明这条路上没有实体可用（或解不解都一样）。
    #    这里如实钉住**当前**行为，将来要不要给 title 也解实体是**另一件事**。
    assert out["title"] == "书名 &amp; 副标题"
    assert out["author"] == "作者甲"
    assert out["publisher"] == "出版社"
    assert out["language"] == "zh"
