"""第 147 期：**格式识别**与**书籍导入**的判据钉子。

本文件钉三件事，每一件都对应一次「同一份字节换个名字就有两种结论」的实测缺陷：

1. **归档书的内容形态按内容定，不看后缀**（`.cbz` 与 `.zip` 字节等价）。
   一份改了后缀的 EPUB（`书.cbz`）此前被数成「1 页漫画」—— 因为 EPUB 里的
   `cover.jpg` 恰好被 `_keep` 算作一页；页数不为 0 又让第 123 期「0 页 ⇒ 内容不符」
   那道闸门失效 ⇒ 静默错（书架显示一本 1 页漫画，点开只有一张图）。
2. **页数 / 封面与「能不能按漫画读」出自同一次开包**（`zipkind.analyze` 的
   `pages` / `cover`）—— 否则两处判据迟早分叉，书架的封面与阅读器第一页不是同一张。
3. **OPF 纯文本字段要解一次 HTML 实体**：写侧（`fileops._set_text_element`）转义、
   读侧（`library._plain`）还原，往返才不变形。此前只有 `dc:description` 解实体，
   于是 `<dc:title>Pride &amp; Prejudice</dc:title>` 在书架上**字面**显示 `&amp;`。

另外钉住 `probe_epub` 的 OPF 定位与全仓其它 5 处**同源**（`library._opf_path`）。
"""
import pathlib
import zipfile

import pytest

from novelforge.core import comics, fileops, library, zipkind

_PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 2048
_JPEG = b"\xff\xd8\xff" + b"\0" * 2048

_CONTAINER = ('<?xml version="1.0" encoding="utf-8"?>'
              '<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:'
              'xmlns:container"><rootfiles>'
              '<rootfile full-path="OEBPS/content.opf" '
              'media-type="application/oebps-package+xml"/></rootfiles></container>')


def _zip(path: pathlib.Path, entries: dict) -> pathlib.Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        for name, data in entries.items():
            z.writestr(name, data)
    return path


def _epub_bytes_entries() -> dict:
    """一份**内容完整**的最小 EPUB（含一张封面图）—— 用来伪装成 `.cbz`。"""
    opf = ('<?xml version="1.0" encoding="utf-8"?>'
           '<package xmlns="http://www.idpf.org/2007/opf" version="2.0">'
           '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
           '<dc:title>真书名</dc:title></metadata>'
           '<manifest><item id="cov" href="cover.jpg" media-type="image/jpeg"/></manifest>'
           '<spine/></package>')
    return {"mimetype": "application/epub+zip",
            "META-INF/container.xml": _CONTAINER,
            "OEBPS/content.opf": opf,
            "OEBPS/cover.jpg": _JPEG}


# ---------------------------------------------------------------------------
# 1. 内容形态按内容定：`.cbz` 不再「按后缀猜成漫画」
# ---------------------------------------------------------------------------

def test_装了epub的cbz不许当成一页漫画(tmp_path, isolated):                # noqa: ARG001
    """🔴 第 147 期主缺陷：`书.cbz` 内容其实是一份 EPUB。

    此前：`pages=1`（cover.jpg 被 `_keep` 算作一页）、`unparsable=False`
    ⇒ 书架登记成一本 1 页漫画，点开是漫画阅读器里孤零零一张图，**且不进「待修复」**。
    现在：与同名内容的 `.zip` 完全同判 —— 判不出可读的图片序列就如实标无法解析。
    """
    p = _zip(tmp_path / "伪漫画.cbz", _epub_bytes_entries())
    info = library._probe_entry(p)                                        # noqa: SLF001

    assert info["unparsable"] is True, "内容不是图片序列 ⇒ 不许假装能按漫画读"
    assert info["pages"] == 0, "页数必须清零：留着那个 1 就是「假的 1 页」"
    assert info["cover"] == ""
    assert info["format"] == "CBZ", "后缀没变，format 也不必跟着变（它说的是文件名）"


def test_图片cbz与图片zip同判且zip归一成cbz(tmp_path, isolated):           # noqa: ARG001
    """`.zip` 里是图片 ⇒ **归一成 CBZ**（前端阅读器/封面/逐页接口认的就是它）。

    ⚠️ 这条防的是把 `comics.is_comic` 当成「后缀已经是漫画名」来用 ——
    它**包含** `.zip/.rar/.7z`，那样写会让 `.zip` 的图片档退化成 `format=ZIP`，
    前端整档打不开。
    """
    src = {"01.png": _PNG, "02.png": _PNG}
    cbz = library._probe_entry(_zip(tmp_path / "a.cbz", src))             # noqa: SLF001
    zp = library._probe_entry(_zip(tmp_path / "a.zip", src))              # noqa: SLF001

    assert cbz["format"] == "CBZ" and zp["format"] == "CBZ"
    assert cbz["pages"] == zp["pages"] == 2
    assert cbz["cover"] == zp["cover"] == "01.png"
    assert cbz["unparsable"] is False and zp["unparsable"] is False


def test_装了文档的zip仍是zip并如实标无法解析(tmp_path, isolated):          # noqa: ARG001
    """对照面：内容判不出来时 `format` 保持后缀（`ZIP`）—— 不冒充能读的东西。"""
    p = _zip(tmp_path / "书.zip", _epub_bytes_entries())
    info = library._probe_entry(p)                                        # noqa: SLF001

    assert info["format"] == "ZIP"
    assert info["unparsable"] is True
    assert info["pages"] == 0


# ---------------------------------------------------------------------------
# 2. 页数 / 封面 = `analyze` 的同一次开包结果（封面必须就是第 1 页）
# ---------------------------------------------------------------------------

def test_页数与封面出自分析且封面就是第1页(tmp_path, isolated):             # noqa: ARG001
    """`cover` 按 `_natural_key` 排 —— 与阅读器里的第一页是**同一张**。

    归档顺序故意写成 「10 / 2 / 1」：按字节序 `"10.png"` 排最前，
    按自然序才是 `"1.png"`。封面对不上第一页，用户点封面进去看的就不是封面。
    """
    p = _zip(tmp_path / "乱序.cbz", {"10.png": _PNG, "2.png": _PNG, "1.png": _PNG})
    v = zipkind.analyze(p)

    assert v["kind"] == "comic" and v["readable"] is True
    assert v["pages"] == 3
    assert v["cover"] == "1.png"
    # 与「取页」那条路（读者真正看到的第一页）必须一致
    assert comics.pages(p)["pages"][0]["name"] == "1.png"


def test_非漫画形态不带页数封面(tmp_path, isolated):                        # noqa: ARG001
    """其余各档 `pages`/`cover` 恒为 0 / 空串（调用方不必判 kind 就能安全取用）。"""
    inner = _epub_bytes_entries()
    for name, ents in (("坏.zip", dict(inner)), ("空.zip", {})):
        v = zipkind.analyze(_zip(tmp_path / name, ents))
        assert v["pages"] == 0 and v["cover"] == "", f"{name} 不该带页数/封面"


# ---------------------------------------------------------------------------
# 3. OPF 纯文本字段：解一次 HTML 实体（与写侧的 escape 成对）
# ---------------------------------------------------------------------------

def _epub_with_opf(root, opf: str, name: str = "书.epub") -> pathlib.Path:
    p = pathlib.Path(root) / name
    return _zip(p, {"mimetype": "application/epub+zip",
                    "META-INF/container.xml": _CONTAINER,
                    "OEBPS/content.opf": opf,
                    "OEBPS/Text/chapter1.xhtml":
                        '<html xmlns="http://www.w3.org/1999/xhtml"><body><p>正文</p>'
                        '</body></html>'})


_FULL_OPF = ('<?xml version="1.0" encoding="utf-8"?>'
             '<package xmlns="http://www.idpf.org/2007/opf" version="2.0">'
             '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
             '<dc:title>Pride &amp; Prejudice &lt;Annotated&gt;</dc:title>'
             '<dc:creator>O&#8217;Brien &amp; Co</dc:creator>'
             '<dc:publisher>Penguin &amp; Sons</dc:publisher>'
             '<dc:language>en</dc:language>'
             '<dc:subject>Fiction &amp; Romance</dc:subject>'
             '<dc:identifier>978&#45;7&#45;115&#45;00000&#45;0</dc:identifier>'
             '<meta name="calibre:series" content="Classics &amp; More"/>'
             '<meta name="calibre:series_index" content="2.00"/>'
             '</metadata>'
             '<manifest><item id="c1" href="Text/chapter1.xhtml" '
             'media-type="application/xhtml+xml"/></manifest>'
             '<spine><itemref idref="c1"/></spine></package>')


def test_opf纯文本字段都解实体(tmp_path, isolated):                         # noqa: ARG001
    """🔴 一条覆盖 7 个字段：标题 / 作者 / 出版社 / 题材 / ISBN / 系列 / 序号。

    这 7 个字段都走 :func:`library._plain`（剥标签 + 解一次实体）。此前它们各写一遍
    `re.sub(r"<[^>]+>", "", …)`，只剥标签不解实体 ⇒ `&amp;` 原样上屏。
    """
    out = library.probe_epub(_epub_with_opf(tmp_path, _FULL_OPF))

    assert out["title"] == "Pride & Prejudice <Annotated>", "标签要剥（它是真标签）"
    assert out["author"] == "O\u2019Brien & Co"
    assert out["publisher"] == "Penguin & Sons"
    assert out["tags"] == ["Fiction & Romance"]
    assert out["series"] == "Classics & More"
    assert out["series_index"] == "2"
    assert out["isbn"] == "978-7-115-00000-0", "`&#45;` 也是连字符，先解再判形状"


def test_写侧转义与读侧解实体对称(tmp_path, isolated):                      # noqa: ARG001
    """🔴 往返钉：`fileops` 写进 OPF 的标题带 `&`，扫回来必须是**同一个标题**。

    写侧 `escape()` 把 `&` 变成 `&amp;`；读侧不解 ⇒ 出版副本被重新探测后，
    书名从「Tom & Jerry」变成「Tom &amp; Jerry」—— 同一本书在库里出现两种写法。
    """
    p = _epub_with_opf(tmp_path, _FULL_OPF)
    with zipfile.ZipFile(p) as z:
        opf = zipkind.read_entry(z, "OEBPS/content.opf").decode("utf-8")
    written = fileops._set_text_element(opf, "dc:title", "Tom & Jerry")    # noqa: SLF001
    assert "Tom &amp; Jerry" in written, "写侧必须转义（否则 OPF 是非法 XML）"

    p2 = _epub_with_opf(tmp_path, written, name="往返.epub")
    assert library.probe_epub(p2)["title"] == "Tom & Jerry"


# ---------------------------------------------------------------------------
# 4. OPF 定位与全仓同源（`library._opf_path`）
# ---------------------------------------------------------------------------

def test_没有container的epub退回首个opf(tmp_path, isolated):                # noqa: ARG001
    """`_opf_path` 的第二条分支：container.xml 缺失/坏掉时退化为首个 `.opf`。

    `probe_epub` 第 147 期起直接调用 `_opf_path` —— 此前它把这段逻辑原地又写了一遍，
    两份实现一旦分叉，「书目显示的信息」与「阅读器打开的章节」会来自两个不同的 OPF。
    """
    opf = ('<?xml version="1.0" encoding="utf-8"?>'
           '<package xmlns="http://www.idpf.org/2007/opf" version="2.0">'
           '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
           '<dc:title>没有 container 的书</dc:title></metadata></package>')
    p = _zip(tmp_path / "无容器.epub", {
        "mimetype": "application/epub+zip",
        "OEBPS/book.opf": opf,
        "OEBPS/Text/chapter1.xhtml": "<html><body>正文</body></html>"})

    with zipfile.ZipFile(p) as z:
        assert library._opf_path(z) == "OEBPS/book.opf"                    # noqa: SLF001
    assert library.probe_epub(p)["title"] == "没有 container 的书"


def test_一个opf都没有时如实报无法解析(tmp_path, isolated):                  # noqa: ARG001
    """绝不抛异常：`probe_epub` 是「缺失资源」工具的判定依据，容错是契约。"""
    p = _zip(tmp_path / "无opf.epub", {"mimetype": "application/epub+zip",
                                      "OEBPS/Text/chapter1.xhtml": "<html/>"})
    out = library.probe_epub(p)
    assert out["unparsable"] is True
    assert out["title"] == ""


@pytest.mark.parametrize("name", ["书.cbz", "书.zip", "书.cbr", "书.rar", "书.7z"])
def test_归档书都走内容分派(tmp_path, isolated, name):                       # noqa: ARG001
    """`.cbz/.cbr/.zip/.rar/.7z` 一律按内容判（`comics.COMIC_EXTS` 全覆盖）。

    只让 `.zip` 走内容分派、其余按后缀猜，就是同一份字节两种结论。
    """
    p = _zip(tmp_path / ("x" + pathlib.PurePosixPath(name).suffix),
             {"01.png": _PNG, "02.png": _PNG})
    info = library._probe_entry(p)                                        # noqa: SLF001
    assert info["pages"] == 2 and info["unparsable"] is False


# ---------------------------------------------------------------------------
# 5. 判出「内容不是图片」之后，用户必须有一个按钮可点（待展开清单）
# ---------------------------------------------------------------------------

def test_装文档的cbz进待展开清单(isolated, tmp_path, make_library):        # noqa: ARG001
    """🔴 第 147 期的**收尾**：`.cbz` 里装的不是图片 ⇒ 探针记 unparsable、理由说「要先展开」。

    `.cbz` 不在 `zipkind.CONTAINER_FORMATS` 里（那是**通用容器**的清单，加进去会把整个
    漫画库拖进待展开页），于是这句话此前**没有对应的按钮** —— 用户被告知要去一个
    清单里展开，而那份清单不收它。这里钉住：它进得去、且展开后得到的正是 `书.epub`。
    同时钉住反例：**读得动的 `.cbz` 一条都不许出现**（否则漫画库每条都挂个不可展开的提示）。
    """
    root = tmp_path / "libs" / "comic"
    make_library("comic", "漫画库", "comic", root)
    # ① 装的是一份 EPUB（判不出的那种）；② 正常图片档（读得动的）
    _zip(root / "伪漫画.cbz", _epub_bytes_entries())
    _zip(root / "真漫画.cbz", {"01.png": _PNG, "02.png": _PNG})
    library.invalidate()

    items = library.container_books()
    names = [i["name"] for i in items]
    assert "伪漫画.cbz" in names, f"判出「不是图片」却没给出展开入口：{names}"
    assert "真漫画.cbz" not in names, f"读得动的漫画不该出现在待展开清单：{names}"

    mine = next(i for i in items if i["name"] == "伪漫画.cbz")
    assert mine["unpackable"] is True
    assert mine["targets"] == ["伪漫画.epub"], "展开结果必须说清是哪一个文件"


def test_普通zip仍在待展开清单(isolated, tmp_path, make_library):            # noqa: ARG001
    """防回归：新判据只是**加**了一条，通用容器那条原样不动。"""
    root = tmp_path / "libs" / "ebook"
    make_library("ebook", "电子书库", "ebook", root)
    _zip(root / "两本.zip", {"a.pdf": b"%PDF-1.4", "b.pdf": b"%PDF-1.4"})
    library.invalidate()

    names = [i["name"] for i in library.container_books()]
    assert names == ["两本.zip"], names
