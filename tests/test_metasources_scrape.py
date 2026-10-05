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
import json
import pathlib

import pytest

from novelforge.core import metasources

FIX_DIR = pathlib.Path(__file__).parent / "fixtures" / "metasources"
LUBIMYCZYTAC = FIX_DIR / "lubimyczytac_search.html"
AMAZON_CHALLENGE = FIX_DIR / "amazon_challenge.html"
GOODREADS = FIX_DIR / "goodreads_search.html"
AWSWAF = FIX_DIR / "awswaf_challenge.html"


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


# ---------------- Goodreads：RSC flight payload（第 101 期真机核验） ----------------

def _gr_html():
    return GOODREADS.read_text(encoding="utf-8")


def test_goodreads_夹具是从真机抓取的结果页片段():
    """夹具必须真的在，且带着「从哪来」的记录 —— 否则下一个人无从判断它是否过期。"""
    assert GOODREADS.exists()
    head = _gr_html()[:700]
    assert "Goodreads" in head, "夹具里要写明来源站点"
    assert "第 101 期" in head, "夹具里要写明抓取期号"
    assert "__next_f.push" in _gr_html(), "这份夹具的核心就是 RSC flight 结构"


def test_goodreads_旧结构确实已从页面下线():
    """**这一家的线上 bug 就是「旧选择器匹配 0 条」**，夹具要能证明这一点。

    真机结果页里 ``<tr itemscope>`` / ``bookTitle`` / ``authorName`` 各出现 0 次
    —— 旧实现（三者组合）只能返回空列表，且**不报错**，表现为「Goodreads 整家静默 0 条」。
    这条钉住夹具代表真实页面：若哪天夹具被换成旧结构，这条会红。
    """
    html = _gr_html()
    assert html.count("<tr itemscope") == 0
    assert "bookTitle" not in html
    assert "authorName" not in html


def test_goodreads_从flight载荷里取到书而不是从DOM(monkeypatch):
    """新结果页是 React Server Components：**书数据在 flight payload 里，不在 DOM 里**。

    实测 DOM 通道只能拿到第 1 本书（其余卡的详情在 ``<template>`` 占位符里，
    而 bs4 的 ``html.parser`` 不解析 `<template>` 内容）⇒ 必须走 payload。
    """
    _stub_page(monkeypatch, _gr_html())
    out = metasources._search_goodreads("three body problem", "", 10, {})

    assert len(out) == 2, [e.get("title") for e in out]
    assert out[0]["title"] == "The Three-Body Problem"
    assert out[1]["title"] == "The Dark Forest"
    assert all(e["source"] == "goodreads" for e in out)


def test_goodreads_多作者全部取到且不串台(monkeypatch):
    """作者取 ``primaryContributorEdge`` + ``secondaryContributorEdges`` 的**全部**人名。

    ⚠️ 这家的作者字段常常是**引用**（指向别的 RSC 行），解开后才有多作者 ——
    解不开时只会剩主作者，看着「有值」但其实是截断。
    """
    _stub_page(monkeypatch, _gr_html())
    out = metasources._search_goodreads("three body problem", "", 10, {})

    assert out[0]["author"] == "Liu Cixin, Ken Liu"
    assert out[1]["author"] == "Liu Cixin, Joel Martinsen"


def test_goodreads_简介解引用且剥掉HTML标签(monkeypatch):
    """简介有两种形态，**两种都要解出来**（实测同一页里并存）：

    * 内联字符串（第 1 本）；
    * 纯文本引用 ``"$73"`` —— 内容在另一行 ``73:T4f5,<正文>`` 里，且带 RSC 类型前缀
      ``T<十六进制长度>,``，必须剥掉。

    ⚠️ 不解引用的后果不是「空」，而是落进 ``'$73'`` 这种**看起来有值**的垃圾。
    """
    _stub_page(monkeypatch, _gr_html())
    out = metasources._search_goodreads("three body problem", "", 10, {})

    d0, d1 = out[0]["description"], out[1]["description"]
    assert d0.startswith("Set against the backdrop of China's Cultural Revolution")
    assert d1.startswith("Imagine the universe as a forest")
    for d in (d0, d1):
        assert not d.startswith("$"), f"引用没解开：{d[:40]!r}"
        assert "T4f5," not in d and "T552," not in d, f"RSC 类型前缀没剥掉：{d[:40]!r}"
        assert "<" not in d, f"简介里的 HTML 标签没剥掉：{d[:60]!r}"


def test_goodreads_年份从epoch毫秒换算(monkeypatch):
    """``details.publicationTime`` 是 **epoch 毫秒**（实测 1415692800000 = 2014）。"""
    _stub_page(monkeypatch, _gr_html())
    out = metasources._search_goodreads("three body problem", "", 10, {})

    assert out[0]["year"] == "2014"
    assert out[1]["year"] == "2015"


def test_goodreads_系列两种形态都解得开(monkeypatch):
    """``bookSeries`` 在真机上**两种形态并存**，两种都要解出来（第 103 期）：

    * 第 1 本：内联字典 —— ``bookSeries[0].series`` 直接就是 Series 对象；
    * 第 2 本：**路径引用** —— ``series`` 是 ``"$4d:props:children:…:series"``，
      只解外层 ``bookSeries`` 的话这里会拿到一个**字符串**（看着有值，其实没法用）。

    系列与卷号此前一直被丢掉：候选结构里没有这两个键，传了也会被静默剔除 ——
    同一份 payload 里其实**早就带着**它们。
    """
    _stub_page(monkeypatch, _gr_html())
    out = metasources._search_goodreads("three body problem", "", 10, {})

    assert [e["series"] for e in out] == ["Remembrance of Earth's Past"] * 2
    assert [e["series_index"] for e in out] == ["1", "2"], "卷号来自身份引用解出的 seriesPlacement"


def test_goodreads_封面与provider_id成套(monkeypatch):
    """``legacyId`` 是该源的规范 ID，落在 ``goodreads_id`` 字段；封面是 Amazon 图床。"""
    _stub_page(monkeypatch, _gr_html())
    out = metasources._search_goodreads("three body problem", "", 10, {})

    assert out[0]["provider_field"] == "goodreads_id"
    assert out[0]["provider_id"] == "20518872"
    assert out[1]["provider_id"] == "66562105"
    assert out[0]["cover_url"].startswith("https://")
    assert out[0]["raw_id"] == "https://www.goodreads.com/book/show/20518872-the-three-body-problem"


def test_goodreads_遵守limit(monkeypatch):
    _stub_page(monkeypatch, _gr_html())
    assert len(metasources._search_goodreads("t", "", 1, {})) == 1
    assert len(metasources._search_goodreads("t", "", 2, {})) == 2


def test_goodreads_同一本书在payload里重复出现时去重(monkeypatch):
    """同一本书会被不同 RSC 行各带一份 ⇒ 不去重结果列表就会灌水。"""
    html = _gr_html()
    rows = metasources._rsc_rows(html)
    # 把承载第 1 本书的那一行再推一次（模拟真实页面里的重复携带）
    dup = html.replace("</body>",
                       '<script>self.__next_f.push([1,"4d:'
                       + json.dumps(rows["4d"])[1:-1].replace('"', '\\"') + '\\n"])</script></body>')
    _stub_page(monkeypatch, dup)
    out = metasources._search_goodreads("three body problem", "", 10, {})
    assert len(out) == 2, [e.get("title") for e in out]


def test_goodreads_不再是永远0条(monkeypatch):
    """**这条是本次修的线上 bug 本身**：旧实现在真页面上返回 0 条，新实现必须给出结果。"""
    _stub_page(monkeypatch, _gr_html())
    out = metasources._search_goodreads("three body problem", "cixin liu", 5, {})
    assert out, "真机夹具上必须能解析出结果（旧实现这里是空列表）"


# ---------------- AWS WAF 挑战页：归因（第 101 期真机核验） ----------------

def test_awswaf挑战页被归因成可重试而不是站点改版(monkeypatch):
    """Goodreads 与 Libro.fm **同一套防护**（AWS WAF），回的是 ~2 KB 挑战页。

    ⚠️ 关键在于**归因**：命中与否取决于出口 IP 信誉，同一 URL 稍后可能就正常。
    若说成「站点改版」，用户会白等修复；说成「可重试 / 降频 / 带 Cookie」才对。
    夹具是真机原样字节（Goodreads 二次请求命中挑战页时抓到的）。
    """
    import httpx

    html = AWSWAF.read_text(encoding="utf-8")
    assert "gokuProps" in html and "awswaf" in html, "夹具应当是真实 WAF 挑战页"

    def fake_request(method, url, **kw):
        # 真机就是这个组合：HTTP 202 + 挑战页正文
        return httpx.Response(202, request=httpx.Request(method, url), text=html)

    monkeypatch.setattr(httpx, "request", fake_request)
    res = metasources.search("goodreads", "three body problem", "", 5, {})
    assert res["ok"] is False and res["entries"] == []
    assert "拦截" in res["error"], res["error"]
    # 归因必须指向 WAF 且给出可行动的说法，不是笼统的「HTTP 202」
    assert "WAF" in res["error"], res["error"]
    assert "重试" in res["error"], res["error"]


def test_awswaf判据不误伤正常结果页(monkeypatch):
    """Goodreads 的真结果页里**不含** ``gokuProps`` / ``awswaf`` —— 判据不能误伤它。"""
    import httpx

    html = _gr_html()

    def fake_request(method, url, **kw):
        return httpx.Response(200, request=httpx.Request(method, url), text=html)

    monkeypatch.setattr(httpx, "request", fake_request)
    text = metasources._get_text("https://www.goodreads.com/search")
    assert "__next_f.push" in text, "真结果页必须原样返回"


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
