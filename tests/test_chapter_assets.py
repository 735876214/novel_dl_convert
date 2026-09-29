"""第 76 期：正文资源 URL 与书内样式的**改写口径**。

`library._rewrite_assets`（正文）与 `library.chapter_assets`（书内样式）是
「书内资源 → 后端 `/asset` 接口」这条链路的**唯一构造点**。它们错一处就表现为
「插图不显示」，而浏览器**不会报错**（静静 404 / 401）—— 所以判据全部钉在这里。

三条必须成立的形状：

1. **`..` 要折叠**：真实 EPUB 写的是 `../Images/x.png`，而 `/asset` 是拿 `namelist()`
   精确相等匹配的 —— 不折叠就永远命不中（改造前正是这样）；
2. **覆盖面**：单引号属性、`srcset`、`xlink:href`、`style="…"` 与 `<style>` 块里的
   `url(...)` 都要改写；`data:` / 锚 / 外链 / 协议相对 / 章节间链接一律不动；
3. **只改属性值、不增删文本节点** —— 进度与批注的偏移按正文字符数算
   （`core/epub_cfi` 与前端 `textContent` 同一把尺子），多一个字符就全错位。
"""
import re

from novelforge.core import library

BID = "lib$abc"
#: 改写后的资源 URL 前缀（`$` 在**路径**里不编码，只有 query 里的 `p` 会被 quote）
ASSET = "/api/books/lib$abc/asset?p="

MEDIA = "OEBPS/Text/chapter1.xhtml"


def _rewrite(html: str, media: str = MEDIA) -> str:
    return library._rewrite_assets(html, media, BID)


# ---------------------------------------------------------------------------
# 判据 ①：`..` 折叠（改造前插图全 404 的直接原因）
# ---------------------------------------------------------------------------

def test_双引号相对路径被折叠成zip内条目():
    assert _rewrite('<img src="../Images/pic.png"/>') == f'<img src="{ASSET}OEBPS/Images/pic.png"/>'


def test_同目录相对路径也改写():
    assert _rewrite('<img src="pic.png"/>') == f'<img src="{ASSET}OEBPS/Text/pic.png"/>'


def test_svg的xlink_href同样改写():
    out = _rewrite('<image xlink:href="../Images/pic.png"/>')
    assert f'xlink:href="{ASSET}OEBPS/Images/pic.png"' in out


# ---------------------------------------------------------------------------
# 判据 ②：覆盖面
# ---------------------------------------------------------------------------

def test_单引号属性同样改写():
    """真实 EPUB 里单引号写法不少，改造前只认双引号 ⇒ 那些书图全不出来。
    改写**保留原引号**（换成另一种会在值里含该引号时把属性截断）。"""
    assert _rewrite("<img src='../Images/pic.png'/>") == f"<img src='{ASSET}OEBPS/Images/pic.png'/>"


def test_srcset逐条改写并保留描述符():
    out = _rewrite('<img srcset="../Images/a.png 1x, ../Images/b.png 2x"/>')
    assert f"{ASSET}OEBPS/Images/a.png 1x" in out
    assert f"{ASSET}OEBPS/Images/b.png 2x" in out


def test_内联样式属性里的url改写():
    """⚠️ 改写后的 `url()` **不带引号**：它嵌在 `style="…"` 里，加双引号会把属性提前截断。"""
    out = _rewrite('<p style="background:url(../Images/pic.png)">x</p>')
    assert f"background:url({ASSET}OEBPS/Images/pic.png)" in out
    assert out.count('"') == 2, out          # 只有属性定界符那两个引号


def test_正文里的style块里的url改写():
    out = _rewrite("<style>em{background:url('../Images/pic.png')}</style>")
    assert f"url({ASSET}OEBPS/Images/pic.png)" in out


def test_data_锚_外链_协议相对一律不动():
    for val in ("data:image/png;base64,AAAA", "#frag", "https://e.com/a.png", "//e.com/a.png"):
        assert _rewrite(f'<img src="{val}"/>') == f'<img src="{val}"/>', val


def test_章节之间的链接不改写():
    """`<a href="chapter2.xhtml">` 指向的是**另一章的文档**，不是资源 ——
    改写它会让点开变成「把 XHTML 当文件下下来」。"""
    html = '<a href="chapter2.xhtml">下一章</a>'
    assert _rewrite(html) == html


def test_逃出zip根的引用原样保留():
    """`..` 多到越过 zip 根 ⇒ 不重写：与其造一个必然 404 的 URL，不如保留原值
    （那本来就说明这本书自身的引用是坏的）。"""
    html = '<img src="../../../x.png"/>'
    assert _rewrite(html) == html


# ---------------------------------------------------------------------------
# 判据 ③：不动文本（进度 / 批注偏移的前提）
# ---------------------------------------------------------------------------

def test_改写不增删文本节点():
    """⚠️ 不变量：改写只换属性值。

    进度与批注的字符偏移是 `textContent.length` 口径（后端 `core/epub_cfi` 读书里的
    **原始 XHTML**、前端量渲染后的正文容器，同一把尺子）—— 正文里多一个字符，
    所有位置偏移就**静默**错位。"""
    html = '<p>正文</p><img src="../Images/pic.png"/>'
    assert re.sub(r"<[^>]+>", "", _rewrite(html)) == "正文"


# ---------------------------------------------------------------------------
# `chapter_assets`：书内样式（`<link>` 表 + `@import` 链 + head 内联 `<style>`）
# ---------------------------------------------------------------------------

_LINKED_CHAPTER = (
    '<html><head><title>一</title>'
    '<link rel="stylesheet" href="../Styles/style.css"/>'
    '<style>em{background:url(../Images/pic.png)}</style>'
    '</head><body><p>正文</p></body></html>'
)


def test_书内样式含link表_import链与head内联style(tmp_path, make_epub):
    ep = make_epub(
        tmp_path,
        chapter=_LINKED_CHAPTER,
        css='@import "sub/extra.css";\np{background:url("../Images/pic.png")}',
        # ⚠️ 落在 `Styles/sub/` 下：它的 `../../Images` 必须以**自己**为基准解析，
        # 才能与其余两处指向同一张图（证明 base 用的是被导入文件自己的目录）
        extra_css='h1{background:url(../../Images/pic.png)}',
    )

    out = library.chapter_assets(ep, BID)

    assert out["sheets"] == ["OEBPS/Styles/style.css"]
    assert out["fixed_layout"] is False
    css = out["css"]
    # 三处 url() 全部改写，且都指向同一张图（link 表 1 处 + @import 进来的 1 处 + 内联 1 处）
    assert css.count(f"url({ASSET}OEBPS/Images/pic.png)") == 3, css
    # head 里那段内联 `<style>` 也在（改造前整个 head 都被丢掉）
    assert "em{" in css, css


def test_没有样式表时返回空样式(tmp_path, make_epub):
    """取不到样式**不是错误**：前端据此回落应用自身的排版。"""
    ep = make_epub(tmp_path, chapter='<html><head><title>一</title></head><body><p>x</p></body></html>')
    out = library.chapter_assets(ep, BID)
    assert out["css"] == ""
    assert out["sheets"] == []


def test_坏文件静默降级(tmp_path):
    """非 EPUB / 坏书一律降级为空样式 —— 绝不因为「抽不到样式」而读不了书。"""
    bad = tmp_path / "bad.epub"
    bad.write_bytes(b"not a zip at all")
    assert library.chapter_assets(bad, BID) == {"css": "", "sheets": [], "fixed_layout": False}


def test_书内样式里的链接表不会二次改写(tmp_path, make_epub):
    """`@import` 是**内联**的（不是改写成 asset URL）—— 内联进来的文本已经改写完，
    外层再跑一遍不许把它变成 `/api/…` 套 `/api/…`。"""
    ep = make_epub(
        tmp_path,
        chapter='<html><head><title>一</title></head><body><p>x</p></body></html>',
        css='@import "sub/extra.css";',
        extra_css='h1{background:url(../../Images/pic.png)}',
    )
    css = library.chapter_assets(ep, BID)["css"]
    assert css.count("/api/books/") == 1, css
