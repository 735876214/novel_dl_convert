"""格式一致性：**通用能力不许出现「某格式支持、另一格式静默失败」**（第 87 期第②步）。

这里钉的是三处实测到的「入口在、点了静默失败」——它们比「入口消失」更难查，
因为用户看到的是「抓取没成功 / 下载坏了」这类离原因十万八千里的现象：

1. 服务端抓取的封面只对 EPUB 生效 ⇒ PDF/TXT/MOBI/AZW3 卡片显示「有封面」却永远 404；
2. OPDS 给目录型条目（有声书 / 合集）广告一条必然 404 的下载链；
3. 前端「无封面」分面只算 EPUB ⇒ 与卡片显示各说各话（见下面的前端源码契约）。

零网络：全部本机文件与内存对象。
"""
import xml.etree.ElementTree as ET

from novelforge.core import db, library, opds


def _book(**over):
    b = {"id": "bid1", "name": "x", "title": "x", "format": "EPUB", "size": 0,
         "has_cover": False}
    b.update(over)
    return b


# ---------------- ① 抓取的封面与格式无关 ----------------

def test_抓取的封面对非_EPUB_格式也生效(isolated, default_root, client,  # noqa: ARG001
                                      auth_headers):
    """TXT 的抓取封面必须取得出来。

    `core/library._apply_overlay` 对**任何格式**只要库里存了抓取封面就把 `has_cover`
    置真（并撤掉 `no-cover`）⇒ 卡片说有封面、前端就会请求这个接口。封面接口此前
    只在 EPUB 分支里读 `db.get_cover` ⇒ 非 EPUB 永远 404，用户以为「抓取没成功」。
    """
    default_root.mkdir(parents=True, exist_ok=True)      # 会话临时根可能还没建出来
    (default_root / "无封面.txt").write_text("正文", encoding="utf-8")
    library.invalidate()
    b = next(x for x in library.books() if x["name"] == "无封面.txt")
    assert b["format"] == "TXT" and b["has_cover"] is False

    db.set_cover(b["id"], b"FAKECOVER", "image/jpeg")
    library.invalidate()
    assert library.by_id(b["id"])["has_cover"] is True, \
        "存了抓取封面之后 has_cover 必须为真（覆盖层对任何格式都算）"

    r = client.get(f"/api/books/{b['id']}/cover", headers=auth_headers)
    assert r.status_code == 200, "卡片说有封面、接口就得给得出来（此前这里必然 404）"
    assert r.content == b"FAKECOVER"


def test_没有抓取封面时非_EPUB_仍然如实_404(isolated, default_root, client):  # noqa: ARG001
    """修①不能把「本来就没有封面」变成 500 或空响应：没有就是 404（前端回退渐变占位）。"""
    default_root.mkdir(parents=True, exist_ok=True)
    (default_root / "真没封面.txt").write_text("正文", encoding="utf-8")
    library.invalidate()
    b = next(x for x in library.books() if x["name"] == "真没封面.txt")
    r = client.get(f"/api/books/{b['id']}/cover")
    assert r.status_code in (401, 404), f"没有封面要如实 404，不是 {r.status_code}"


# ---------------- ② OPDS 不给必然失败的链接 ----------------

def _entry_xml(b: dict) -> str:
    feed = ET.Element("feed")
    opds.book_entry(feed, b, "http://host")
    return ET.tostring(feed, encoding="unicode")


def test_OPDS_目录型条目不广告下载链(isolated):  # noqa: ARG001
    """有声书目录 / 序号单元合集是**目录**，`/opds/download/{bid}` 要求 `path.is_file()`
    ⇒ 给了链接客户端点了必然 404。前端的下载按钮早已刻意隐藏，OPDS 缺的是同一条口径。"""
    for fmt in ("AUDIO", "UNITS"):
        xml = _entry_xml(_book(format=fmt))
        assert "/download/bid1" not in xml, f"{fmt} 不该拿到必然 404 的下载链"


def test_OPDS_普通文件条目仍然给下载链(isolated):  # noqa: ARG001
    """修②不能一刀切把下载功能砍掉 —— 单文件条目照旧（这是 OPDS 的主用途）。"""
    for fmt in ("EPUB", "PDF", "CBZ", "TXT", "ZIP"):
        assert "/download/bid1" in _entry_xml(_book(format=fmt)), f"{fmt} 必须仍可下载"


# ---------------- ③ 前端「无封面」分面的源码契约 ----------------

def test_前端无封面分面不再只算_EPUB():
    """前端分面的判据要与后端一致（服务端封面对任何格式都生效）。

    这里扫源码而不是跑前端单测：本仓的前端契约测试就是**扫源码**的形态
    （见 `tests/test_frontend_unit_contract.py`），加一条最便宜的护栏 ——
    免得以后有人「顺手」把 EPUB 那条件加回来。
    """
    import pathlib
    src = pathlib.Path(__file__).resolve().parent.parent / "frontend/src/stores/library.ts"
    text = src.read_text(encoding="utf-8")
    seg = text[text.index("nocover:1"):]
    seg = seg[:seg.index("}")]                     # 只取这一段，避免匹配到别处
    assert "!b.has_cover" in seg, "无封面分面的判据应当是「没有封面」"
    assert "'EPUB'" not in seg.upper() or "EPUB" not in seg, \
        "不许再把「无封面」限定在 EPUB —— 抓取封面对任何格式都生效"
