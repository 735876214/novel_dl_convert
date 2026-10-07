"""第 112 期：FB2（FictionBook）**直读**契约（解析成派生 EPUB，见 `core/fb2cache.py`）。

FB2 是**单文件 XML** 电子书：章节（`<section>` + `<title>`）、插图（顶层 `<binary>` 的
base64 图片，正文用 `<image l:href="#id"/>` 引用）、封面（`<coverpage>`）、元数据
（`<description><title-info>`）。本期的落地方式与 `mobicache`（MOBI 解包）同形态：

- 后端把 FB2 解析成一份**真 EPUB**，落到 `CACHE_DIR/fb2-epub/<book_id>/derived.epub`
  —— **不进书库**（不新增书目条目、不落成品目录）、**不写回源文件**（全程只读）；
- 派生 EPUB 与真 EPUB 走**完全相同**的链路：目录（`library._reading_list`）/ 正文
  （`library.chapter_html`）/ 插图（资产接口）/ 书内样式 / **CFI 精确位置**；
- 解析不了 ⇒ **422 + 原因**，且源没变就不再重试（形态锁定）。绝不 500、绝不假装能读。

⚠️ **本文件不依赖任何第三方样本**：FB2 是纯文本 XML，用例内**直接写真实字节**
（含 `<?xml?>` 声明、`DOCTYPE`、未转义 HTML5 实体、嵌套 section、脚注 body、坏 base64）
—— 于是预清洗、分章、元素映射、图片解码、封面提取、状态机整条链路都被真跑一遍。
"""

import base64
import pathlib
import shutil
import zipfile

import pytest

from novelforge import config
from novelforge.core import fb2cache, library

#: 一张**真** PNG 头 + 任意字节（内容不重要，判据是「取到的字节与 `<binary>` 逐字节相同」）
_PNG = b"\x89PNG\r\n\x1a\n" + b"fake-png-payload" * 6
_JPEG = b"\xff\xd8\xff\xe0" + b"fake-jpeg-payload" * 6


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _fb2(chapters: str, *, cover=None, images: str = "", meta: str = "", notes: bool = False,
         head: str = '<?xml version="1.0" encoding="utf-8"?>', doctype: str = "") -> str:
    """拼一份 FB2。默认带命名空间 —— 真 FB2 几乎都带，`_local()` 必须能剥掉。"""
    notes_body = ('<body name="notes"><section><title><p>注释</p></title>'
                  '<p>脚注正文不该出现在正文里。</p></section></body>') if notes else ""
    cover_page = f'<coverpage><image l:href="#{cover}"/></coverpage>' if cover else ""
    return (
        f'{head}\n{doctype}\n'
        '<FictionBook xmlns="http://www.gribuser.ru/xml/fictionbook/2.0"'
        ' xmlns:l="http://www.w3.org/1999/xlink">'
        '<description><title-info>'
        '<genre>sf</genre>'
        '<author><first-name>慈欣</first-name><last-name>刘</last-name></author>'
        '<book-title>FB2 测试之书</book-title>'
        '<annotation>一句简介</annotation>'
        '<lang>zh</lang>'
        f'{meta}{cover_page}'
        '</title-info></description>'
        f'<body>{chapters}</body>{notes_body}{images}'
        '</FictionBook>')


def _binary(bid: str, data: bytes, ct: str = "image/png") -> str:
    return f'<binary id="{bid}" content-type="{ct}">{_b64(data)}</binary>'


@pytest.fixture(autouse=True)
def _cache_dir_in_tmp(tmp_path, monkeypatch):
    """CACHE_DIR 默认指向真实配置目录；派生产物必须落进用例专属目录。"""
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path / "cache")


def _write_fb2(root, text: str, name: str = "直读.fb2") -> "tuple[str, pathlib.Path]":
    p = pathlib.Path(root) / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    library.invalidate()
    books = [b for b in library.books() if b["name"] == name]
    assert books, f"扫描没找到 {name}（`.fb2` 没进白名单？）"
    return books[0]["id"], p


#: 三章 + 一张插图 + 封面 + 一个纯容器 section（无正文 ⇒ 该被丢掉）+ 脚注 body
_FULL = _fb2(
    '<section><title><p>第一章 开端</p></title>'
    '<p>正文一 &amp; 一点点 <emphasis>斜体</emphasis> 与 <strong>粗体</strong>'
    ' 再加 <strikethrough>删除线</strikethrough>。</p>'
    '<subtitle>小标题</subtitle>'
    '<empty-line/>'
    '<epigraph><p>引语</p><text-author>某人</text-author></epigraph>'
    '</section>'
    '<section><title><p>第二章 发展</p></title>'
    '<p>正文二。</p><image l:href="#pic"/></section>'
    '<section><title><p>第三部</p></title>'
    '<section><title><p>第三章 结局</p></title><p>正文三。</p></section></section>',
    cover="cover", notes=True,
    images=_binary("cover", _PNG) + _binary("pic", _JPEG, "image/jpeg"))

#: `<title>` 里出现 &nbsp; —— 真 FB2 里裸具名实体极常见，预清洗必须兜住
_ENTITY = _fb2('<section><title><p>第一章&nbsp;带&nbsp;实体</p></title>'
               '<p>正文。</p></section>')


def _flat(detail: dict) -> list:
    return [c for v in (detail.get("chapters") or []) for c in v["chapters"]]


def _illust_rels(epub: pathlib.Path) -> list:
    """派生 EPUB 里的**书内插图**条目名（封面那张不算）。

    名字由本仓 `epub_builder` 决定（`images/bNNNN.<ext>`），**不写死连封面一起猜**。
    """
    with zipfile.ZipFile(epub) as z:
        return [n for n in z.namelist() if "/images/" in n or n.startswith("images/")]


# ---------------------------------------------------------------------------
# 上架：`.fb2` 此前连书架都上不去
# ---------------------------------------------------------------------------

def test_FB2进白名单且被收成一本ebook(default_root):  # noqa: ARG001
    assert ".fb2" in library.BOOK_EXTS
    assert ".fb2" in library._EBOOK_EXTS
    bid, _src = _write_fb2(default_root, _FULL, "上架.fb2")
    b = library.by_id(bid)
    assert b and str(b["format"]).upper() == "FB2"


def test_扫描期靠头部扫描认出内嵌封面(default_root):  # noqa: ARG001
    """扫描期**不许**解析整本 XML（NAS 上很贵）—— 只做头部扫描，但结果要对。"""
    _bid, src = _write_fb2(default_root, _FULL, "带封面.fb2")
    assert fb2cache.has_embedded_cover(src) is True

    plain = pathlib.Path(default_root) / "无封面.fb2"
    plain.write_text(_fb2('<section><title><p>第一章</p></title><p>正文。</p></section>'),
                     encoding="utf-8")
    assert fb2cache.has_embedded_cover(plain) is False
    assert fb2cache.has_embedded_cover(pathlib.Path(default_root) / "不存在.fb2") is False


# ---------------------------------------------------------------------------
# 主链路：目录 / 正文 / 插图 / 封面 / 样式 / CFI / 源只读
# ---------------------------------------------------------------------------

def test_FB2直读_目录正文插图封面与CFI全部可用且源文件只读(client, auth_headers, default_root):  # noqa: ARG001
    bid, src = _write_fb2(default_root, _FULL, "全覆盖.fb2")
    before = (src.stat().st_size, src.stat().st_mtime_ns)
    root_before = sorted(p.name for p in pathlib.Path(default_root).iterdir())

    detail = client.get(f"/api/books/{bid}", headers=auth_headers).json()
    chaps = _flat(detail)
    # 「第三部」是纯容器（只有嵌套 section 的标题、自己没正文）⇒ 过滤掉；其余三章留下
    assert [c["title"] for c in chaps] == ["第一章 开端", "第二章 发展", "第三章 结局"], \
        f"目录该来自 `<title>` 且丢掉空章：{detail.get('chapters')}"
    assert [c["index"] for c in chaps] == [0, 1, 2], "index 必须 0 基且连续（过滤之后编号）"

    ch = client.get(f"/api/books/{bid}/chapter/0", headers=auth_headers)
    assert ch.status_code == 200, ch.text
    body = ch.json()["html"]
    assert "第一章 开端" in body and "正文一" in body
    assert "<em>" in body and "<strong>" in body and "<s>" in body
    assert 'class="subtitle"' in body and "<blockquote>" in body and "引语" in body
    assert "<br/>" in body, "`<empty-line/>` 该renders成换行"

    # 插图：判据是「资源解析到了**派生产物**」且字节与 `<binary>` 逐字节相同
    epub = fb2cache.read_target(library.by_id(bid), path=src)[0]
    assert epub is not None and epub.is_file()
    rels = _illust_rels(epub)
    assert len(rels) == 2, f"两个 binary 都该进派生 EPUB：{rels}"
    b64_ok = {_PNG, _JPEG}
    got = set()
    for rel in rels:
        r = client.get(f"/api/books/{bid}/asset", params={"p": rel}, headers=auth_headers)
        assert r.status_code == 200, f"{rel} 取不到：{r.text}"
        got.add(r.content)
    assert got == b64_ok, "取到的插图字节必须与 `<binary>` 里的原图逐字节相同"

    # 正文里的 `<image>` 已被改写成资产接口 URL（与真 EPUB 插图同一机制）
    body2 = client.get(f"/api/books/{bid}/chapter/1", headers=auth_headers).json()["html"]
    assert "/asset?p=" in body2, f"插图该被改写成资产接口：{body2}"

    # 封面：`<coverpage>` 那张图（已进派生 EPUB）与 EPUB 走同一条读取
    cv = client.get(f"/api/books/{bid}/cover", headers=auth_headers)
    assert cv.status_code == 200, cv.text
    assert cv.content == _PNG, "封面该是 `<coverpage>` 指的那张图"

    # 书内样式通道：没有样式时是空串 + 空清单，**不是**错误
    css = client.get(f"/api/books/{bid}/epub-css", headers=auth_headers)
    assert css.status_code == 200
    assert set(css.json()) >= {"css", "sheets"}

    # 进度：派生 EPUB 是真 EPUB ⇒ CFI 照常生成（精确位置不丢）
    assert client.put(f"/api/books/{bid}/progress",
                      json={"locator": 1, "percent": 20.0, "offset": 3},
                      headers=auth_headers).status_code == 200
    prog = client.get(f"/api/books/{bid}/progress", headers=auth_headers).json()
    assert prog["cfi"], "FB2 直读必须保留 CFI 精确位置（产出的就是真 EPUB）"

    # 源文件逐字节未动；书库目录一个文件都没多出来（产物落缓存）
    assert (src.stat().st_size, src.stat().st_mtime_ns) == before
    assert sorted(p.name for p in pathlib.Path(default_root).iterdir()) == root_before
    assert fb2cache._cache_dir(bid).exists()
    assert fb2cache._cache_dir(bid) != pathlib.Path(default_root)


def test_脚注body本期不进正文(client, auth_headers, default_root):  # noqa: ARG001
    """`<body name="notes">` 本期**如实跳过**（记在「没做」）—— 别把它混进正文冒充内容。"""
    bid, _src = _write_fb2(default_root, _FULL, "脚注.fb2")
    detail = client.get(f"/api/books/{bid}", headers=auth_headers).json()
    assert "注释" not in [c["title"] for c in _flat(detail)]
    for c in _flat(detail):
        html = client.get(f"/api/books/{bid}/chapter/{c['index']}",
                          headers=auth_headers).json()["html"]
        assert "脚注正文" not in html


def test_未转义的HTML5实体也能解析(client, auth_headers, default_root):  # noqa: ARG001
    """真 FB2 里裸 `&nbsp;` 很常见 —— 预清洗要把具名实体转成数字引用再喂解析器。"""
    bid, _src = _write_fb2(default_root, _ENTITY, "实体.fb2")
    chaps = _flat(client.get(f"/api/books/{bid}", headers=auth_headers).json())
    assert chaps, "带 &nbsp; 的 FB2 不该整本读不出"
    t = chaps[0]["title"]
    assert "第一章" in t and "实体" in t, f"实体该被还原（换成空格也算）：{t!r}"


def test_坏base64图片被跳过而正文照读(client, auth_headers, default_root):  # noqa: ARG001
    text = _fb2('<section><title><p>第一章</p></title><p>正文。</p>'
                '<image l:href="#bad"/></section>',
                images='<binary id="bad" content-type="image/png">@@@not-base64@@@</binary>')
    bid, _src = _write_fb2(default_root, text, "坏图.fb2")
    r = client.get(f"/api/books/{bid}/chapter/0", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert "正文。" in r.json()["html"]
    assert "<img" not in r.json()["html"], "坏图该被丢掉，不留一个指不到东西的 <img>"


def test_文件名回落当元数据且不改成书名(client, auth_headers, default_root):  # noqa: ARG001
    """元数据（书名 / 作者）仍按**文件名** —— 与 MOBI / TXT 同口径（本期不改这一层）。"""
    bid, _src = _write_fb2(default_root, _FULL, "文件名说了算.fb2")
    b = library.by_id(bid)
    assert b["title"] == "文件名说了算"


# ---------------------------------------------------------------------------
# 状态机：缓存命中 / 规则升级 / 自愈分量 / 锁定 / 产物被删
# ---------------------------------------------------------------------------

def _count_builds(monkeypatch) -> list:
    calls: list = []
    real = fb2cache._build

    def spy(book, src, bid, cdir, fp):
        calls.append(str(src))
        return real(book, src, bid, cdir, fp)

    monkeypatch.setattr(fb2cache, "_build", spy)
    return calls


def test_第二次请求命中缓存不重复解析(client, auth_headers, default_root, monkeypatch):  # noqa: ARG001
    calls = _count_builds(monkeypatch)
    bid, _src = _write_fb2(default_root, _FULL, "命中缓存.fb2")

    client.get(f"/api/books/{bid}", headers=auth_headers)
    client.get(f"/api/books/{bid}", headers=auth_headers)
    client.get(f"/api/books/{bid}/chapter/0", headers=auth_headers)
    client.get(f"/api/books/{bid}/cover", headers=auth_headers)
    assert len(calls) == 1, "源没变就不该重复解析（解析整本 XML 是纯 CPU 开销）"


def test_规则版本升级触发重建(client, auth_headers, default_root, monkeypatch):  # noqa: ARG001
    calls = _count_builds(monkeypatch)
    bid, _src = _write_fb2(default_root, _FULL, "规则升级.fb2")

    client.get(f"/api/books/{bid}", headers=auth_headers)
    assert len(calls) == 1
    monkeypatch.setattr(fb2cache, "RULE_VERSION", fb2cache.RULE_VERSION + 1)
    client.get(f"/api/books/{bid}", headers=auth_headers)
    assert len(calls) == 2, "本模块规则版本变了 ⇒ 源没动也要重建（否则改了看不见效果）"
    # 重建后的 state 记的是新版本 ⇒ 再请求就该命中（不是每次都重建）
    client.get(f"/api/books/{bid}", headers=auth_headers)
    assert len(calls) == 2


def test_lxml兜底从无到有也能自愈重建(client, auth_headers, default_root, monkeypatch):  # noqa: ARG001
    """`recover` 分量是**自愈钩子**：先前没有 lxml 时锁死失败的文件，装上后指纹没变也该重建。

    只比指纹的话这种文件就**永远锁死**了（源没动 ⇒ 永远不重试）。
    """
    calls = _count_builds(monkeypatch)
    bid, _src = _write_fb2(default_root, _FULL, "自愈.fb2")

    monkeypatch.setattr(fb2cache, "_recover_available", lambda: False)
    client.get(f"/api/books/{bid}", headers=auth_headers)
    assert len(calls) == 1
    client.get(f"/api/books/{bid}", headers=auth_headers)
    assert len(calls) == 1, "同一个 recover 分量下不该重复解析"

    monkeypatch.setattr(fb2cache, "_recover_available", lambda: True)
    client.get(f"/api/books/{bid}", headers=auth_headers)
    assert len(calls) == 2, "recover 分量变了 ⇒ 源没动也要重建（否则坏文件永远锁死）"


def test_坏FB2时422且源没变就不再重试(client, auth_headers, default_root, monkeypatch):  # noqa: ARG001
    calls = _count_builds(monkeypatch)
    bid, _src = _write_fb2(default_root, "这不是 XML，更不是 FB2。", "坏书.fb2")

    r = client.get(f"/api/books/{bid}/chapter/0", headers=auth_headers)
    assert r.status_code == 422, r.text
    assert "读不了" in r.json()["detail"]
    assert len(calls) == 1

    client.get(f"/api/books/{bid}", headers=auth_headers)
    client.get(f"/api/books/{bid}/chapter/0", headers=auth_headers)
    assert len(calls) == 1, "源没变就该锁定形态 —— 坏书不能每次请求都重解一遍"
    # 进度**照常**能存：坏书只影响「读到什么」，不该把进度保存打成失败
    assert client.put(f"/api/books/{bid}/progress",
                      json={"locator": 0, "percent": 1.0},
                      headers=auth_headers).status_code == 200


def test_根不是FictionBook时如实判读不出(client, auth_headers, default_root, monkeypatch):  # noqa: ARG001
    """根闸门：解析得出来的任意 XML 也不算 FB2 —— 否则会把别的 XML 当成书渲染。"""
    bid, _src = _write_fb2(default_root, "<root><body><p>别的 XML</p></body></root>",
                           "非FB2.fb2")
    r = client.get(f"/api/books/{bid}/chapter/0", headers=auth_headers)
    assert r.status_code == 422, r.text


def test_产物被手工删掉视同未命中而不是错误(client, auth_headers, default_root, monkeypatch):  # noqa: ARG001
    calls = _count_builds(monkeypatch)
    bid, _src = _write_fb2(default_root, _FULL, "删产物.fb2")

    assert client.get(f"/api/books/{bid}/chapter/0", headers=auth_headers).status_code == 200
    shutil.rmtree(fb2cache._cache_dir(bid))
    r = client.get(f"/api/books/{bid}/chapter/0", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert len(calls) == 2


def test_asset路径穿越被拒(client, auth_headers, default_root):  # noqa: ARG001
    bid, _src = _write_fb2(default_root, _FULL, "穿越.fb2")
    r = client.get(f"/api/books/{bid}/asset", params={"p": "../../../etc/passwd"},
                   headers=auth_headers)
    assert r.status_code == 404


def test_非FB2扩展名不碰本模块(default_root):  # noqa: ARG001
    """判据必须只对 `.fb2` 生效 —— 否则 EPUB / MOBI 会被拖来做 XML 解析。"""
    for name in ("a.epub", "a.mobi", "a.txt", "a.zip"):
        assert fb2cache.read_target({"id": "x", "name": name},
                                    path=pathlib.Path(name)) == (None, "")


def test_拒绝超过上限的源文件(client, auth_headers, default_root, monkeypatch):  # noqa: ARG001
    """整本 XML 会进内存 ⇒ 超大文件如实拒绝（不 OOM、不假装能读）。"""
    monkeypatch.setattr(fb2cache, "SOURCE_MAX_BYTES", 16)
    bid, _src = _write_fb2(default_root, _FULL, "太大.fb2")
    r = client.get(f"/api/books/{bid}/chapter/0", headers=auth_headers)
    assert r.status_code == 422, r.text


# ---------------------------------------------------------------------------
# lxml 兜底（可选）：只有装了 lxml 才测得到这一层
# ---------------------------------------------------------------------------

@pytest.mark.skipif(not fb2cache._recover_available(),
                    reason="需要 lxml（requirements.txt 里本就有）才能测「轻微坏 XML 的兜底」")
def test_轻微坏XML靠lxml兜底(client, auth_headers, default_root):  # noqa: ARG001
    """未闭合标签 + 坏 DOCTYPE：stdlib 解析不了，lxml recover 该接住。"""
    text = _fb2('<section><title><p>第一章</p></title><p>正文一。<p>没闭合</section>',
                doctype='<!DOCTYPE FictionBook PUBLIC "-//FictionBook//DTD" "x.dtd">')
    bid, _src = _write_fb2(default_root, text, "轻微坏.fb2")
    r = client.get(f"/api/books/{bid}/chapter/0", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert "正文一" in r.json()["html"]
