"""EPUB 元数据解析的**容错契约**（与「用什么解析器」无关）。

## 为什么单开一个文件

「正常书能不能读」已有一堆用例覆盖（`test_provider_ids` / `test_series_meta` /
`test_reader_fixed_layout`…）。本文件盯的是另一件事：**畸形书不许静默丢元数据**。

这组容错是**从旧正则继承下来的承诺**（旧正则逐条独立匹配 ⇒ 一处畸形不影响别处），
而它**丢了不报错** —— `probe_epub` 返回的是空字段，界面上表现为「这本书没有书名 / 作者」，
没人会把它和解析器联系起来。所以这些用例断言的是**行为契约**，不针对某个实现：
当前实现（`library.py` 里的正则）与将来任何一种实现都必须同时满足。

## 来历（第 95 期：一次**被回退**的重构留下的契约）

第 95 期试过把这一组解析从手写正则换成 `xml.etree.ElementTree`（动机是 §7.5「优先成熟库」），
**验证后回退**了。回退的理由与这次实测到的三处真实回归，记在
`docs/TODO.md` §1「EPUB 解析改成熟解析器」那条里 —— 想重试的人请**先读那一条**。

下面这些用例正是那三处回归的**可执行形式**，所以它们留下来了（对本文件当时的两个实现都绿）：

1. 🔴 **截断的 OPF**：`read_events()` 是**按文档顺序**吐事件的；若按「取最后一条 `end`
   当文档元素」，`<package>…<manifest><item/></manifest>` 截断时会取到内层的 `item`，
   于是 `<metadata>` 整个子树看不见、书名作者全空（**静默**，`unparsable` 还是 False）。
   文档元素是**第一条 `start`** 的那个（解析器复用对象 ⇒ 它上面挂着坏点之前的全部子节点）。
2. 🔴 **未定义实体**（`&nbsp;`）：`read_events()` 是生成器，`ParseError` 在**迭代中途**才抛，
   写成 `list(parser.read_events())` 一抛就把**已吐出的事件一起丢掉** ⇒ 整份文档作废，
   连坏点**之前**已解析好的书名也读不到。必须手工累积、只吞异常。
3. 🔴 **未声明的命名空间前缀**：旧正则比的是字面标签名，所以「写了 `dc:` 却没声明
   `xmlns:dc`」它照样读得到；而真 XML 解析器把这当**硬错误**（`unbound prefix`）⇒
   整本书元数据全空。这一条**也被下面的用例覆盖**（`test_未声明命名空间前缀的OPF仍读得到`）——
   它正是当初那次重构唯一一条被现有用例抓到的回归（`test_isbn_shape.py` 打了个正着）。
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
    """按给定 OPF 原文造一本最小 EPUB（故意允许 OPF 是畸形的）。"""
    p = pathlib.Path(root) / name
    p.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(p, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml", _CONTAINER)
        z.writestr("OEBPS/content.opf", opf)
        z.writestr("OEBPS/Text/chapter1.xhtml",
                   '<html xmlns="http://www.w3.org/1999/xhtml"><body><p>正文</p></body></html>')
    return p


_HEAD = """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="bookid">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>被截断的书</dc:title>
    <dc:creator>作者甲</dc:creator>
    <dc:language>zh</dc:language>
  </metadata>
  <manifest>
    <item id="c1" href="Text/chapter1.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine><itemref idref="c1"/></spine>
"""


def test_良构OPF各字段都读得到(tmp_path, isolated):                       # noqa: ARG001
    """基线：正常书照常读出（确认下面几条容错用例不是「反正都读不到」）。"""
    opf = _HEAD + "</package>\n"
    out = library.probe_epub(_epub_with_opf(tmp_path, opf))

    assert out["title"] == "被截断的书"
    assert out["author"] == "作者甲"
    assert out["language"] == "zh"
    assert out["unparsable"] is False


def test_根元素未闭合的OPF仍能读到metadata(tmp_path, isolated):            # noqa: ARG001
    """🔴 回归钉：截断的 OPF（少了 `</package>`）不许把 `<metadata>` 整个丢掉。

    旧实现取「最后一条 `end` 事件」当文档元素 —— 这里最后一条 `end` 是内层的 `<item/>`，
    于是只看见 `item` 一个子树，书名 / 作者全空（**静默**，`unparsable` 还是 False）。
    真正的文档元素是**第一条 `start`**：`<package>`，它上面挂着坏点之前的全部子节点。
    """
    opf = _HEAD + "  <!-- 作者没写完就断电了：manifest 之后没有 </package> -->\n"
    out = library.probe_epub(_epub_with_opf(tmp_path, opf))

    assert out["title"] == "被截断的书", "截断的 OPF 也读得到坏点之前的书名"
    assert out["author"] == "作者甲"
    assert out["language"] == "zh"


def test_未定义实体之前的内容仍读得到(tmp_path, isolated):                # noqa: ARG001
    """🔴 回归钉：`&nbsp;`（XML 里没有、HTML 里才有）**不许把坏点之前已解析好的字段带走**。

    ⚠️ 这里**刻意不**断言坏点**之后**的字段：那是**实现定义**的 ——
    旧正则对实体一无所知，照读不误；换成真解析器后可能在那一处停住（读不到）。
    真实契约只有一条：**前面读到的不能因为后面的畸形而丢**（旧正则「一处畸形不影响别处」
    的语义）。断言「后面一定读不到」会把某个实现的局限写成契约。
    """
    opf = _HEAD.replace(
        "  </metadata>",
        "    <dc:description>bad&nbsp;entity</dc:description>\n"
        "    <dc:publisher>坏点之后</dc:publisher>\n"
        "  </metadata>",
    ) + "</package>\n"
    out = library.probe_epub(_epub_with_opf(tmp_path, opf))

    assert out["title"] == "被截断的书", "坏实体之前解析好的书名必须还在"
    assert out["author"] == "作者甲"


def test_垃圾内容不抛异常且字段为空(tmp_path, isolated):                   # noqa: ARG001
    """`probe_epub` 同时是「缺失资源」工具的判定依据 ⇒ **必须全程容错**。

    旧正则从不因文档畸形而抛；换成真解析器后这条不能丢（否则一次扫描遇到一本坏书
    就会把整轮扫描打断）。

    ⚠️ 这里**不断言** `unparsable`：它的口径是「**抛了异常**」（不是 zip、或库里根本没有
    OPF 文件）—— 见 `tests/test_reader_fixed_layout.py::test_破损EPUB不抛异常且不算固定版式`。
    OPF 文件**存在**但内容是垃圾时，解析不出东西但也不抛，字段留空、`unparsable` 保持 False。
    """
    for bad in ("", "<", "这不是 XML", '<?xml version="1.0"?><package><metadata>'):
        p = _epub_with_opf(tmp_path, bad, name="坏书.epub")
        out = library.probe_epub(p)                                      # 不许抛
        assert isinstance(out, dict)
        assert out["title"] == "", f"{bad!r} 应读不出书名"
        assert out["author"] == ""
        assert out["unparsable"] is False, "内容是垃圾但没抛异常 ⇒ 不算 unparsable"


def test_未声明命名空间前缀的OPF仍读得到(tmp_path, isolated):             # noqa: ARG001
    """🔴 回归钉：用了 `dc:` 前缀却没声明 `xmlns:dc` 的 OPF，元数据**不许变空**。

    这种写法**不合规但真实存在**（野生 EPUB 里就有）。旧正则比的是字面标签名，
    所以它读得到；而真 XML 解析器把它当**硬错误**（`unbound prefix: line 1`）⇒
    整本书书名 / 作者全空，且**不报错**。

    这正是第 95 期那次重构**唯一被现有用例抓到的**回归（`test_isbn_shape.py` 打了个正着，
    它用一段没带命名空间声明的 OPF 片段测 `_isbn_of`）。换解析器的人必须自己解决它
    （可选方案见 `docs/TODO.md` §1 那条），不许让它静默变空。
    """
    opf = ('<?xml version="1.0" encoding="utf-8"?>'
           '<package version="3.0"><metadata>'
           '<dc:title>没声明前缀的书</dc:title>'
           '<dc:creator>作者乙</dc:creator>'
           '<dc:language>zh</dc:language>'
           '</metadata><manifest/><spine/></package>')
    out = library.probe_epub(_epub_with_opf(tmp_path, opf))

    assert out["title"] == "没声明前缀的书"
    assert out["author"] == "作者乙"
    assert out["language"] == "zh"
