"""第 110 期：MOBI / AZW3 / AZW **直读**契约（解包，不转换）。

用户口径（原话）：「mobi直接阅读，不进行转化」。落地方式是**解包**：

- 后端把书自身的 KF8 内容解包到 `CACHE_DIR/mobi-unpack/<book_id>/`，正文/插图/样式从
  这里下发 —— **不进书库**（不新增书目条目、不落成品目录）、**不写回源文件**（全程只读）；
- **KF8 / AZW3**（解包出 EPUB）⇒ 目录 / 正文 / 插图 / 书内样式 / **CFI 精确位置** 全部
  复用 EPUB 链路（`library._reading_list` / `chapter_html` / `chapter_assets` / `epub_cfi`）；
- **纯 MOBI6**（解包出 HTML）⇒ 复用既有分章器（`detect`），`cfi` 留空、恢复回落
  「章 + 全书百分比」（与 TXT 原生路线同款，**如实降级**）；
- 解包器缺失 ⇒ **503 + 明确文案**；这本书解不开 ⇒ **422 + 原因**，且源没变就不再重试
  （形态锁定）。绝不假装能读、绝不 500。

⚠️ **本文件不依赖任何第三方样本**：`unpackBook` 被 `_fake_*` 替掉，产物是用本仓自己的
`epub_builder` / 手写 HTML 造的**真字节** —— 于是状态机、读目标、目录、单章、资源、进度
CFI 与「源文件只读」整条链路都被真跑一遍。唯一没被自动化覆盖的是 KindleUnpack 自己：
把真实样本放到 `tests/fixtures/mobi/demo.mobi` 即自动启用
:func:`test_真实样本_KF8_经KindleUnpack解包后能读`，没有样本时**如实 skip**（样本无法手工
构造，缺了就跳过，不伪造）。
"""
import pathlib
import shutil
import zipfile

import pytest

from novelforge import config
from novelforge.core import detect, epub_builder, library, mobicache

#: 解包产物里那张图（KF8 路线的书内资源）
_IMAGE = b"\xff\xd8\xff\xe0" + b"fake-jpeg-bytes" * 8

#: 真实样本的可选位置（缺了就 skip 那一条用例，其余用例不依赖它）
_SAMPLE = pathlib.Path(__file__).parent / "fixtures" / "mobi" / "demo.mobi"


@pytest.fixture(autouse=True)
def _cache_dir_in_tmp(tmp_path, monkeypatch):
    """CACHE_DIR 默认指向真实配置目录；解包产物必须落进用例专属目录。"""
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path / "cache")
    mobicache._SPLIT_CACHE.clear()


def _write_mobi(root, name: str = "直读.mobi") -> tuple:
    """往库根放一本「书」（内容任意字节：扫描只按扩展名收书）。

    真解包器由各用例分别 monkeypatch；本函数只负责让书**出现在书架上**。
    """
    p = pathlib.Path(root) / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"BOOKMOBI" + b"\0" * 8192)
    library.invalidate()
    books = [b for b in library.books() if b["name"] == name]
    assert books, f"扫描没找到 {name}"
    return books[0]["id"], p


def _flat(detail: dict) -> list:
    return [c for v in (detail.get("chapters") or []) for c in v["chapters"]]


def _fake_kf8(monkeypatch, calls: list):
    """假解包器：产出**真 EPUB**（本仓 `epub_builder` 组装）+ 一张图，形态与 KF8 一致。

    返回的函数对象上挂 `image_rel`（图在 EPUB zip 里的条目名），供资源用例取用 ——
    不写死 `EPUB/Images/…` 这类路径，因为条目名由 ebooklib 决定，猜它就是在测 ebooklib。
    """
    def fake(infile, outdir, apnxfile=None, epubver=None, **kw):   # noqa: ARG001
        calls.append(infile)
        out = pathlib.Path(outdir) / "mobi8"
        out.mkdir(parents=True, exist_ok=True)
        epub_path = out / (pathlib.Path(infile).stem + ".epub")
        chapters = [{"title": f"第{i}章", "body_html": f"<p>正文{i}——MOBI直读</p>"}
                    for i in (1, 2, 3)]
        epub_builder.build_epub({"title": "直读样本", "author": "测试", "language": "zh"},
                                chapters, str(epub_path))
        with zipfile.ZipFile(epub_path) as z:
            names = z.namelist()
        doc = next(n for n in names if n.endswith((".xhtml", ".html")) and "nav" not in n)
        rel = (doc.rsplit("/", 1)[0] + "/pic.jpg") if "/" in doc else "pic.jpg"
        with zipfile.ZipFile(epub_path, "a") as z:
            z.writestr(rel, _IMAGE)
        fake.image_rel = rel
        return None

    fake.image_rel = ""
    monkeypatch.setattr("mobi.kindleunpack.unpackBook", fake)
    return fake


def _fake_mobi6(monkeypatch, calls: list):
    """假解包器：只产出 `mobi7/book.html`（纯 MOBI6 的形态），三章正文。"""
    def fake(infile, outdir, apnxfile=None, epubver=None, **kw):   # noqa: ARG001
        calls.append(infile)
        d = pathlib.Path(outdir) / "mobi7"
        d.mkdir(parents=True, exist_ok=True)
        parts = [f"第{i}章 标题{i}\n" + "正文内容在这里，写长一点。" * 20 for i in (1, 2, 3)]
        (d / "book.html").write_text(
            "<html><body><p>" + "</p><p>".join(parts) + "</p></body></html>",
            encoding="utf-8")
        return None

    monkeypatch.setattr("mobi.kindleunpack.unpackBook", fake)
    return fake


# ---------------------------------------------------------------------------
# 缺解包器：如实报，不假装能读
# ---------------------------------------------------------------------------

def test_缺解包器时章节接口503而不是假装能读(client, auth_headers, default_root, monkeypatch):  # noqa: ARG001
    bid, src = _write_mobi(default_root, "缺解包器.mobi")
    monkeypatch.setattr(mobicache, "state", lambda: {
        "available": False, "version": "", "reason": "MOBI 直读需要 mobi（未安装）"})

    detail = client.get(f"/api/books/{bid}", headers=auth_headers).json()
    assert str(detail["format"]).upper() == "MOBI"
    assert _flat(detail) == [], "解包器不在 ⇒ 目录如实为空，不能摆一份假目录"

    r = client.get(f"/api/books/{bid}/chapter/0", headers=auth_headers)
    assert r.status_code == 503, r.text
    assert "MOBI 解包能力" in r.json()["detail"]

    # 进度**照常**能存：缺解包器只影响「读到什么」，不该把进度保存打成失败
    assert client.put(f"/api/books/{bid}/progress",
                      json={"locator": 0, "percent": 1.0},
                      headers=auth_headers).status_code == 200
    assert src.stat().st_size > 0


# ---------------------------------------------------------------------------
# KF8：解包出的 EPUB 走完整链路
# ---------------------------------------------------------------------------

def test_KF8直读_目录正文资源与CFI全部可用且源文件只读(client, auth_headers, default_root, monkeypatch):  # noqa: ARG001
    calls: list = []
    fake = _fake_kf8(monkeypatch, calls)
    bid, src = _write_mobi(default_root, "直读KF8.mobi")
    before = (src.stat().st_size, src.stat().st_mtime_ns)
    root_before = sorted(p.name for p in pathlib.Path(default_root).iterdir())

    detail = client.get(f"/api/books/{bid}", headers=auth_headers).json()
    chaps = _flat(detail)
    assert len(chaps) >= 3, f"KF8 该解出目录：{detail.get('chapters')}"

    # ⚠️ spine 首条是 **nav 目录页**（`build_epub(nav=True)` 与 KindleUnpack 的真实产物同形态，
    # 真 EPUB 也是这样，见 `landing.py` 里「成品 EPUB 首条是 nav 目录页」那条注释）⇒
    # 正文断言取**末章**，别把「目录页没有正文」误判成「读不了」。
    first = client.get(f"/api/books/{bid}/chapter/{chaps[0]['index']}", headers=auth_headers)
    assert first.status_code == 200, first.text
    assert "<nav" in first.json()["html"], "首条该是 nav 目录页（与 EPUB 一致）"

    idx = chaps[-1]["index"]
    ch = client.get(f"/api/books/{bid}/chapter/{idx}", headers=auth_headers)
    assert ch.status_code == 200, ch.text
    assert "MOBI直读" in ch.json()["html"]

    # 书内资源：判据是「资源解析到了**解包产物**」，不是「这本书里有图」
    a = client.get(f"/api/books/{bid}/asset", params={"p": fake.image_rel},
                   headers=auth_headers)
    assert a.status_code == 200, f"{fake.image_rel} 取不到：{a.text}"
    assert a.content == _IMAGE

    # 书内样式通道：没有样式时是空串 + 空清单，**不是**错误
    css = client.get(f"/api/books/{bid}/epub-css", headers=auth_headers)
    assert css.status_code == 200
    assert set(css.json()) >= {"css", "sheets"}

    # 进度：KF8 路线 CFI 照常生成（精确位置不丢）
    assert client.put(f"/api/books/{bid}/progress",
                      json={"locator": idx, "percent": 3.0, "offset": 3},
                      headers=auth_headers).status_code == 200
    prog = client.get(f"/api/books/{bid}/progress", headers=auth_headers).json()
    assert prog["cfi"], "KF8 直读必须保留 CFI 精确位置（解包出的就是真 EPUB）"

    # 产物落缓存目录，**不进书库**；源文件逐字节未动
    assert mobicache._cache_dir(bid).exists()
    assert mobicache._cache_dir(bid) != pathlib.Path(default_root)
    assert (src.stat().st_size, src.stat().st_mtime_ns) == before
    assert sorted(p.name for p in pathlib.Path(default_root).iterdir()) == root_before
    assert len(calls) == 1


def test_第二次请求命中缓存不重复解包(client, auth_headers, default_root, monkeypatch):  # noqa: ARG001
    calls: list = []
    _fake_kf8(monkeypatch, calls)
    bid, _src = _write_mobi(default_root, "命中缓存.mobi")

    client.get(f"/api/books/{bid}", headers=auth_headers)
    client.get(f"/api/books/{bid}", headers=auth_headers)
    client.get(f"/api/books/{bid}/chapter/0", headers=auth_headers)
    assert len(calls) == 1, "源没变就不该重复解包（解包是秒级操作）"


def test_asset路径穿越被拒(client, auth_headers, default_root, monkeypatch):  # noqa: ARG001
    calls: list = []
    _fake_kf8(monkeypatch, calls)
    bid, _src = _write_mobi(default_root, "穿越.mobi")

    r = client.get(f"/api/books/{bid}/asset", params={"p": "../../../etc/passwd"},
                   headers=auth_headers)
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# 纯 MOBI6：HTML 路线（如实降级）
# ---------------------------------------------------------------------------

def test_纯MOBI6走HTML路线_分章可读但CFI如实留空(client, auth_headers, default_root, monkeypatch):  # noqa: ARG001
    calls: list = []
    _fake_mobi6(monkeypatch, calls)
    bid, _src = _write_mobi(default_root, "老MOBI6.mobi")

    detail = client.get(f"/api/books/{bid}", headers=auth_headers).json()
    chaps = _flat(detail)
    assert len(chaps) >= 2, f"HTML 路线也该出目录：{detail.get('chapters')}"

    idx = chaps[0]["index"]
    ch = client.get(f"/api/books/{bid}/chapter/{idx}", headers=auth_headers)
    assert ch.status_code == 200, ch.text
    assert "正文内容" in ch.json()["html"]

    # 越界仍是 404（与 EPUB 路径同一约定，由 `_chapter_read` 翻译）
    assert client.get(f"/api/books/{bid}/chapter/{len(chaps) + 5}",
                      headers=auth_headers).status_code == 404

    client.put(f"/api/books/{bid}/progress",
               json={"locator": idx, "percent": 2.0, "offset": 3}, headers=auth_headers)
    prog = client.get(f"/api/books/{bid}/progress", headers=auth_headers).json()
    assert prog["cfi"] == "", "HTML 路线没有 CFI：如实留空并回落「章 + 百分比」"
    assert prog["locator"] == idx and prog["percent"] == 2.0

    assert calls and len(calls) == 1


# ---------------------------------------------------------------------------
# 解不开 / 形态锁定 / 失效通道
# ---------------------------------------------------------------------------

def test_解不开时422且源没变就不再重试(client, auth_headers, default_root, monkeypatch):  # noqa: ARG001
    calls: list = []

    def fake(infile, outdir, apnxfile=None, epubver=None, **kw):   # noqa: ARG001
        calls.append(infile)
        raise ValueError("Coud not extract from %s" % infile)      # 真解包器失败时抛的就是它

    monkeypatch.setattr("mobi.kindleunpack.unpackBook", fake)
    bid, _src = _write_mobi(default_root, "坏MOBI.mobi")

    r = client.get(f"/api/books/{bid}/chapter/0", headers=auth_headers)
    assert r.status_code == 422, r.text
    assert "解不开" in r.json()["detail"]
    assert len(calls) == 1

    client.get(f"/api/books/{bid}", headers=auth_headers)
    client.get(f"/api/books/{bid}/chapter/0", headers=auth_headers)
    assert len(calls) == 1, "源没变就该锁定形态 —— 坏书不能每次请求都重解一遍"


def test_规则版本升级触发重建(client, auth_headers, default_root, monkeypatch):  # noqa: ARG001
    calls: list = []
    _fake_kf8(monkeypatch, calls)
    bid, _src = _write_mobi(default_root, "规则升级.mobi")

    client.get(f"/api/books/{bid}", headers=auth_headers)
    assert len(calls) == 1
    monkeypatch.setattr(mobicache, "RULE_VERSION", mobicache.RULE_VERSION + 1)
    client.get(f"/api/books/{bid}", headers=auth_headers)
    assert len(calls) == 2, "本模块规则版本变了 ⇒ 源没动也要重建（否则改了看不见效果）"


def test_解包器版本升级触发重建(client, auth_headers, default_root, monkeypatch):  # noqa: ARG001
    calls: list = []
    _fake_kf8(monkeypatch, calls)
    bid, _src = _write_mobi(default_root, "解包器升级.mobi")

    client.get(f"/api/books/{bid}", headers=auth_headers)
    assert len(calls) == 1
    monkeypatch.setattr(mobicache, "state", lambda: {
        "available": True, "version": "9.9.9", "reason": ""})
    client.get(f"/api/books/{bid}", headers=auth_headers)
    assert len(calls) == 2, "换了抽取器版本 ⇒ 旧产物作废重建"
    # 重建后的 state 记的是新版本 ⇒ 再请求就该命中（不是每次都重建）
    client.get(f"/api/books/{bid}", headers=auth_headers)
    assert len(calls) == 2


def test_产物被手工删掉视同未命中而不是错误(client, auth_headers, default_root, monkeypatch):  # noqa: ARG001
    calls: list = []
    _fake_kf8(monkeypatch, calls)
    bid, _src = _write_mobi(default_root, "删产物.mobi")

    assert client.get(f"/api/books/{bid}/chapter/0", headers=auth_headers).status_code == 200
    shutil.rmtree(mobicache._cache_dir(bid))
    r = client.get(f"/api/books/{bid}/chapter/0", headers=auth_headers)
    assert r.status_code == 200, r.text
    assert len(calls) == 2


def test_非MOBI扩展名不碰本模块(default_root):  # noqa: ARG001
    """判据必须只对 `.mobi/.azw3/.azw` 生效 —— 否则 EPUB / TXT 会被拖去解包。"""
    assert mobicache.read_target({"id": "x", "name": "a.epub"}, path=pathlib.Path("a.epub")) == (None, "")
    assert detect.CHAPTER_RULE_VERSION > 0      # 顺带钉住本模块依赖的分章真值源在


# ---------------------------------------------------------------------------
# 白名单：`.azw` 此前不是「书」，第 110 期补进来
# ---------------------------------------------------------------------------

def test_AZW进白名单且被收成一本ebook(default_root):  # noqa: ARG001
    assert ".azw" in library.BOOK_EXTS
    assert ".azw" in library._EBOOK_EXTS
    bid, _src = _write_mobi(default_root, "旧格式.azw")
    b = library.by_id(bid)
    assert b and str(b["format"]).upper() == "AZW"


# ---------------------------------------------------------------------------
# 真实样本（可选）：唯一能覆盖 KindleUnpack 自己的用例
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not _SAMPLE.exists(),
    reason="需要真实 .mobi 样本（把 <任意>.mobi 放到 tests/fixtures/mobi/demo.mobi 即自动启用）"
           "—— MOBI 无法手工构造，缺样本时如实跳过，不伪造")
def test_真实样本_KF8_经KindleUnpack解包后能读(client, auth_headers, default_root):  # noqa: ARG001
    p = pathlib.Path(default_root) / "demo.mobi"
    shutil.copyfile(_SAMPLE, p)
    library.invalidate()
    books = [b for b in library.books() if b["name"] == "demo.mobi"]
    assert books, "样本没被扫描收进来"
    bid = books[0]["id"]
    before = (p.stat().st_size, p.stat().st_mtime_ns)

    detail = client.get(f"/api/books/{bid}", headers=auth_headers).json()
    chaps = _flat(detail)
    assert chaps, f"真实样本该解出目录：{detail.get('chapters')}"

    ch = client.get(f"/api/books/{bid}/chapter/{chaps[0]['index']}", headers=auth_headers)
    assert ch.status_code == 200, ch.text
    assert ch.json()["html"].strip(), "真实样本的正文不该是空的"
    assert (p.stat().st_size, p.stat().st_mtime_ns) == before
