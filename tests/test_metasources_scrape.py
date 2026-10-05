"""第 99 期：页面抓取型元数据源的**解析契约**（真机夹具驱动）。

背景：`novelforge/core/metasources.py` 里六家 `fragile` 源（Amazon / Goodreads / Kobo /
Audible / Libro.fm / Lubimyczytac）此前**零测试覆盖** —— `tests/test_metadata_providers.py`
只钉注册表一致性与密钥口径，从不碰解析。结果两个线上真 bug 长期没被发现：

1. **Audible 整家失效**：`response_groups` 里带了非法的 `publisher`，接口直接回
   ``400 {"message":"Invalid response group(s) requested: publisher"}`` ⇒ **永远 0 结果**。
2. **Lubimyczytac 多作者被截断**：三次独立 `findall` 再按下标配对，多作者书
   （作者之间是 ``, `` 分隔）只拿得到第一位，其余静默丢失。

本文件用**真机抓到的页面夹具**钉住这两条，外加「解析失败一律回落空列表」的既有纪律。
夹具与出处的口径沿用 `tests/fixtures/legado2_real.json` 的先例：真样本裁成代表性片段。

⚠️ 这些用例**不出网**：一律打桩 `metasources._get_text`（页面型的唯一出网处）。
真机核验的结论记在 `docs/roadmap-gaps-remaining.md` 第 99 期段。
"""
import pathlib

import pytest

from novelforge.core import metasources

FIX_DIR = pathlib.Path(__file__).parent / "fixtures" / "metasources"
LUBIMYCZYTAC = FIX_DIR / "lubimyczytac_search.html"
AMAZON_CHALLENGE = FIX_DIR / "amazon_challenge.html"


def _stub_page(monkeypatch, html):
    """把该源的唯一出网处换成夹具内容（不发任何请求）。"""
    monkeypatch.setattr(metasources, "_get_text",
                        lambda url, params=None, headers=None, hints=None: html)


# ---------------- Lubimyczytac：真机页面 + 多作者 ----------------

def _lubi_html():
    return LUBIMYCZYTAC.read_text(encoding="utf-8")


def test_书源夹具存在且是真机抓取的片段():
    """夹具必须真的在，且带着「从哪来」的记录 —— 否则下一个人无从判断它是否过期。"""
    assert LUBIMYCZYTAC.exists() and AMAZON_CHALLENGE.exists()
    head = _lubi_html()[:600]
    assert "lubimyczytac.pl/szukaj" in head, "夹具里要写明抓取 URL"
    assert "真机" in head, "夹具里要写明这是真机抓到的字节"


def test_lubimyczytac_多作者全部取到而不是只取第一位(monkeypatch):
    """**第 99 期修掉的那个缺陷本身**。

    夹具前 3 张卡里有两张是多作者（作者之间 ``, `` 分隔）：
    旧实现（三次 findall + 按下标）只拿得到第一位作者。
    """
    _stub_page(monkeypatch, _lubi_html())
    out = metasources._search_lubimyczytac("three body problem", "", 10, {})

    assert len(out) == 3, [e.get("title") for e in out]
    assert out[1]["author"] == "Karol Derwich, Magdalena Modrzejewska"
    assert out[2]["author"] == "Joanna Marszałek-Kawa, Maria Ochwat"
    # 单作者那条不许被改成带逗号的样子
    assert out[0]["author"] == "Sophia Bennett"


def test_lubimyczytac_书名优先取属性且封面链接带出来(monkeypatch):
    _stub_page(monkeypatch, _lubi_html())
    out = metasources._search_lubimyczytac("three body problem", "", 10, {})

    # 书名取 title="…" 属性（锚文本带首尾空格）
    assert out[0]["title"] == "A Three Dog Problem"
    assert out[0]["title"] == out[0]["title"].strip()
    assert out[1]["title"].startswith("Latin American Thought")
    assert all(e["cover_url"].startswith("https://") for e in out), [e["cover_url"] for e in out]
    # raw_id 是详情页链接，供 dedupe / 溯源
    assert out[0]["raw_id"].startswith("/") or out[0]["raw_id"].startswith("http")


def test_lubimyczytac_遵守limit(monkeypatch):
    _stub_page(monkeypatch, _lubi_html())
    assert len(metasources._search_lubimyczytac("t", "", 2, {})) == 2
    assert len(metasources._search_lubimyczytac("t", "", 1, {})) == 1


# ---------------- 挑战页 / 空页：一律 0 条且不抛异常 ----------------

def test_amazon_反爬挑战页解析出0条且不抛异常(monkeypatch):
    """Amazon 真机回的就是这个页面（HTTP 200，2344 字节，不含结果项）。

    纪律是「宁可这家没结果，也绝不能让它的异常打断整轮抓取」——
    挑战页没有 ``data-asin``，必须安静地给空列表。
    """
    _stub_page(monkeypatch, AMAZON_CHALLENGE.read_text(encoding="utf-8"))
    assert metasources._search_amazon("three body problem", "cixin liu", 5, {}) == []


def test_amazon的JS校验页被识别成被拦截而不是静默0条(monkeypatch):
    """**第 99 期真机核验发现的第三处问题**。

    Amazon 回的是「200 + meta refresh 跳转到 …&bm-verify=… + 混淆 JS」的 JS 校验页，
    它**不含任何验证码关键词** ⇒ 旧判据放行，用户只看到「0 条结果」。

    用户要能分清「站点改版（等修复）」与「被拦（降频率 / 带 Cookie）」——
    这两种处置完全不同，所以必须在出网口当场判掉。本用例走真实 `_get_text`（打桩 httpx）。
    """
    import httpx

    html = AMAZON_CHALLENGE.read_text(encoding="utf-8")

    def fake_request(method, url, **kw):
        return httpx.Response(200, request=httpx.Request(method, url), text=html)

    monkeypatch.setattr(httpx, "request", fake_request)
    res = metasources.search("amazon", "three body problem", "", 5, {})
    assert res["ok"] is False
    assert "拦截" in res["error"], res["error"]


def test_真结果页不会被误判成被拦截(monkeypatch):
    """判据（bm-verify）必须**不误伤正常结果页** —— 否则这家会好页也报被拦。"""
    import httpx

    html = _lubi_html()                       # 真机抓到的正常搜索结果页

    def fake_request(method, url, **kw):
        return httpx.Response(200, request=httpx.Request(method, url), text=html)

    monkeypatch.setattr(httpx, "request", fake_request)
    text = metasources._get_text("https://example.invalid/s")
    assert "book-card__title" in text, "正常页必须原样返回"


def test_空页面与垃圾内容对各家都是空列表而不是异常(monkeypatch):
    """真实站点会给出各种「不是我们期待的形状」的响应；一家炸了不能拖垮整轮。"""
    for html in ("", "<html></html>", "not html at all", "<div><span>", "\x00\x01"):
        _stub_page(monkeypatch, html)
        for fn, args in ((metasources._search_amazon, ("t", "a", 5, {})),
                         (metasources._search_goodreads, ("t", "a", 5, {})),
                         (metasources._search_librofm, ("t", "a", 5, {})),
                         (metasources._search_lubimyczytac, ("t", "a", 5, {}))):
            assert fn(*args) == [], (fn.__name__, repr(html))


# ---------------- Audible：response_groups 不许带非法值 ----------------

def test_audible_响应组不含非法的publisher(monkeypatch):
    """**第 99 期修掉的线上 bug**：带 ``publisher`` 会被接口回 400 ⇒ 整家永远 0 结果。

    这条**不出网**地钉住请求参数形状；真机 200 的核验记在 roadmap 第 99 期段
    （``publisher_name`` 随 ``product_desc`` 照旧返回，删它不少拿出版方）。
    """
    seen = {}

    def fake_get_json(url, params=None, headers=None, method="GET", data=None):
        seen["url"] = url
        seen["params"] = dict(params or {})
        return {"products": [{
            "asin": "B0CTRZ4XGN", "title": "The Three-Body Problem",
            "authors": [{"name": "Cixin Liu"}, {"name": "Ken Liu - translator"}],
            "publisher_name": "Macmillan Audio",
            "product_images": {"500": "https://example.invalid/c.jpg"},
        }]}

    monkeypatch.setattr(metasources, "_get_json", fake_get_json)
    out = metasources._search_audible("three body problem", "", 3, {})

    groups = seen["params"].get("response_groups", "")
    assert "publisher" not in [g.strip() for g in groups.split(",")], \
        f"`publisher` 不是合法响应组，接口会回 400：{groups}"
    assert "product_desc" in groups and "contributors" in groups

    # 出版方**字段**仍要取到（它随 product_desc 返回，与那个非法组名无关）
    assert len(out) == 1
    assert out[0]["publisher"] == "Macmillan Audio"
    assert out[0]["author"] == "Cixin Liu, Ken Liu - translator"


def test_audible_接口400时如实带回错误而不是静默空列表(monkeypatch):
    """修好参数形状后，接口再出错要**如实说**（走 search() 的错误通道）。"""
    import httpx

    def boom(method, url, **kw):
        req = httpx.Request(method, url)
        return httpx.Response(400, request=req,
                              json={"message": "Invalid response group(s) requested: publisher"})

    monkeypatch.setattr(httpx, "request", boom)
    res = metasources.search("audible", "three body problem", "", 3, {})
    assert res["ok"] is False and res["entries"] == []
    assert "400" in res["error"], res["error"]


# ---------------- 打桩点本身要成立 ----------------

def test_页面型的唯一出网处就是_get_text():
    """打桩 `_get_text` 能覆盖全部页面型抓取 —— 本文件的离线前提。

    若哪天有人给某家加了**自己的**出网调用（绕过 `_get_text`），这条会红：
    那些用例就会偷偷变成真出网用例。
    """
    import inspect
    for fn in (metasources._search_amazon, metasources._search_goodreads,
               metasources._search_librofm, metasources._search_lubimyczytac):
        src = inspect.getsource(fn)
        assert "httpx." not in src, f"{fn.__name__} 不该自己出网"
        assert "_get_text(" in src, f"{fn.__name__} 应当经 _get_text 出网"


def test_没装bs4时ubs4型解析如实回落空列表(monkeypatch):
    """bs4 是显式声明的依赖，但缺了要**如实降级**（既有口径），不是抛异常打断整轮。"""
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *a, **kw):
        if name == "bs4":
            raise ImportError("simulated: bs4 未安装")
        return real_import(name, *a, **kw)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    _stub_page(monkeypatch, _lubi_html())
    assert metasources._search_lubimyczytac("t", "", 5, {}) == []


if __name__ == "__main__":                                # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
