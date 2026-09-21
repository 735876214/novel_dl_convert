"""第 36 期小轨：**固定版式（pre-paginated）识别**。

阅读器给正文套的那一整套排版偏好（字号 / 行高 / 首行缩进 / 段落间距 / 字距 / 分栏 / 内容宽度）
全是**重排**设置。固定版式的书每一页是**已经排好版的整页**（常见实现是整页 SVG 或绝对定位），
把这些设置套上去只会把整页排版揉烂 —— 所以必须先能**认出**这类书（上游那一项
「Fixed-layout page spreads」的前置条件就在这里）。

钉住四件事：

1. **三种真实写法都认**：EPUB3 的 ``<meta property="rendition:layout">pre-paginated</meta>``、
   EPUB3 的 ``content=`` 属性写法、早期 Apple 的 ``<meta name="fixed-layout" content="true"/>``。
2. **只认显式声明，不靠特征猜**：书里有一张整页 SVG 但**没**声明固定版式 → 仍算可重排。
   猜错的代价是把一本正常书的排版设置夺走，比不做判定更糟。
3. **显式 reflowable / false 一律不算**（不能把「声明了不是」当成是）。
4. **判定结果随书目与详情下发**（字段恒在，前端无需做 undefined 兜底），非 EPUB 恒 false。
"""
from __future__ import annotations

import pathlib
import zipfile

import pytest

from novelforge.core import library

CONTAINER = """<?xml version="1.0" encoding="utf-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>"""

# 整页 SVG：固定版式书的典型形态，但**它本身不是判据**（见「不靠特征猜」那条）
FULL_PAGE_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 1600" width="1200" height="1600">'
    '<image xlink:href="p1.jpg" width="1200" height="1600"/></svg>'
)


def _epub(root, name: str, meta: str = "", body: str = "<p>正文</p>") -> pathlib.Path:
    """手写一个最小 EPUB（mimetype / container.xml / content.opf）—— OPF 内容完全可控。

    刻意不用 ``epub_builder``：这里要验的是**OPF 里的某个 meta 怎么写**，
    交给组装器就等于「拿它自己写的 OPF 验它自己」。
    """
    path = pathlib.Path(root) / name
    path.parent.mkdir(parents=True, exist_ok=True)
    opf = f"""<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="id">urn:uuid:test</dc:identifier>
    <dc:title>整页排好的书</dc:title>
    <dc:creator>作者</dc:creator>
    <dc:language>zh</dc:language>
    {meta}
  </metadata>
  <manifest>
    <item id="c1" href="c1.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine><itemref idref="c1"/></spine>
</package>"""
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml", CONTAINER)
        z.writestr("content.opf", opf)
        z.writestr("c1.xhtml", f"<html><body>{body}</body></html>")
    return path


@pytest.fixture
def env(isolated, tmp_path: pathlib.Path, make_library):  # noqa: ARG001 —— 依赖 isolated 切目录
    root = tmp_path / "libraries" / "fixed"
    aroot = tmp_path / "libraries" / "spoken"
    make_library("fixed", "整页书库", "ebook", root)
    # 非 EPUB 的对照要另起一个**有声书库**：库类型收窄了扫描白名单，
    # 音频目录放进电子书库根本不出现在书目里（见 library._exts_for_type）
    make_library("spoken", "有声库", "audiobook", aroot)
    return {"lid": "fixed", "root": root, "audio_lid": "spoken", "audio_root": aroot}


# ---------------------------------------------------------------------------
# ① 三种真实写法都认
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("meta, why", [
    ('<meta property="rendition:layout">pre-paginated</meta>', "EPUB3 标签体写法"),
    ('<meta property="rendition:layout" content="pre-paginated"/>', "EPUB3 属性写法"),
    ('<meta name="fixed-layout" content="true"/>', "早期 Apple 约定"),
])
def test_三种写法的固定版式都认(env, meta: str, why: str):
    p = _epub(env["root"], "整页.epub", meta)
    assert library.probe_epub(p)["fixed_layout"] is True, f"{why}没被认出来：{meta}"


def test_书目条目里带固定版式标记(env):
    _epub(env["root"], "整页.epub",
          '<meta property="rendition:layout">pre-paginated</meta>')
    library.invalidate()
    row = next(b for b in library.books("fixed"))
    # 字段**恒在**（不是只有固定版式才有）：前端不用写 undefined 兜底
    assert row["fixed_layout"] is True


# ---------------------------------------------------------------------------
# ② 只认显式声明 —— 不靠特征猜
# ---------------------------------------------------------------------------

def test_有整页SVG但没声明仍算可重排(env):
    """整页 SVG 是固定版式书的常见形态，但它**不是判据**。

    拿特征猜的代价是把一本正常书的排版设置夺走（用户调字号没反应却不知道为什么），
    比不做判定更糟 —— 所以这里钉死「不猜」。
    """
    p = _epub(env["root"], "像整页.epub", "", body=FULL_PAGE_SVG)
    assert library.probe_epub(p)["fixed_layout"] is False


@pytest.mark.parametrize("meta", [
    "",
    '<meta property="rendition:layout">reflowable</meta>',
    '<meta property="rendition:layout" content="reflowable"/>',
    '<meta name="fixed-layout" content="false"/>',
])
def test_可重排与显式否定都不算固定版式(env, meta: str):
    p = _epub(env["root"], "可重排.epub", meta)
    assert library.probe_epub(p)["fixed_layout"] is False


def test_破损EPUB不抛异常且不算固定版式(env):
    """解析失败照旧折算成 unparsable（probe_epub 是「缺失资源」的判定依据，必须容错）。"""
    p = env["root"] / "坏的.epub"
    p.write_bytes(b"EPUB")  # 不是 zip
    out = library.probe_epub(p)
    assert out["unparsable"] is True
    assert out["fixed_layout"] is False
    # 扫描同样不能因为这一本炸掉，且它照样出现在书目里（缺资源工具要能找到它）
    library.invalidate()
    rows = {b["name"]: b for b in library.books("fixed")}
    assert rows["坏的.epub"]["fixed_layout"] is False


# ---------------------------------------------------------------------------
# ③ 非 EPUB 恒 false（本项目不解析它们的内容）
# ---------------------------------------------------------------------------

def test_有声书目录与文本文件恒为非固定版式(env, make_audio_dir):
    make_audio_dir(env["audio_root"], "整页有声书", tracks=2)
    (env["root"] / "占位.txt").write_bytes(b"TXT")
    library.invalidate()
    spoken = {b["name"]: b for b in library.books(env["audio_lid"])}
    assert spoken["整页有声书"]["fixed_layout"] is False
    assert {b["name"]: b for b in library.books("fixed")}["占位.txt"]["fixed_layout"] is False


# ---------------------------------------------------------------------------
# ④ 接口：书目与详情都要把判定结果给到前端
# ---------------------------------------------------------------------------

def test_接口把固定版式下发到书目与详情(env, client, auth_headers):
    _epub(env["root"], "整页.epub",
          '<meta property="rendition:layout">pre-paginated</meta>')
    _epub(env["root"], "可重排.epub")
    library.invalidate()

    r = client.get("/api/books?limit=200", headers=auth_headers)
    assert r.status_code == 200, r.text
    got = {b["name"]: b for b in r.json()["items"]}
    assert got["整页.epub"]["fixed_layout"] is True
    assert got["可重排.epub"]["fixed_layout"] is False

    # 阅读器读的是详情（/api/books/{id}），它必须同样带着这个标记
    d = client.get(f"/api/books/{got['整页.epub']['id']}", headers=auth_headers)
    assert d.status_code == 200, d.text
    assert d.json()["fixed_layout"] is True
