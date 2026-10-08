"""第 102 期：按 ID 取详情（`metasources.detail`）的行为契约。

「按 ID 取详情」补的是检索**猜不准**的那一半：库里已经记过 `openlibrary_id` /
`itunes_id` / `audible_id` 的书，用**精确键**回查比拿书名再猜一次更准。本文件钉住四件事：

- **只绑定真机核验过的家**：接口存在 + 返回形状对得上才在声明里写 `detail_name`。
  第 102 期核过 itunes 与 openlibrary，第 115 期核过 audible（`/products/{asin}` 回
  `{"product": {…}}`、与检索同形状）；googlebooks（匿名 429）/ goodreads（302 反爬）
  **未核过 ⇒ 不声明**（`AGENTS.md` §7「不做假能力」）。
- 未覆盖的家 / 缺标识 / 假标识**都不外呼**，且都回用户看得懂的中文 ——
  「这家没有这条通道」与「这家有但刚才失败了」要能分得开（处置不同）。
- 解析：iTunes 复用检索的字段映射（`/lookup` 与 `/search` 同响应形状）；
  OpenLibrary 的 `description` 是**字典**、作者名要逐条再查、works 端点
  **不返回**出版年 / 出版社 / ISBN（留空，不猜）。
- 详情缓存与检索缓存**不共用键** —— 详情回 `dict`、检索回 `list`，
  撞了双方都解析不出东西，而且**都不会报错**（静默失效最难查）。

⚠️ 全程离线：`_get_json` 换成按 URL 路由的桩，**任何意料外的外呼都会直接炸**。
"""
import httpx
import pytest

from novelforge.core import metasources as M

OL_BASE = "https://openlibrary.org"
OL_WORK = OL_BASE + "/works/OL17267881W.json"
OL_AUTHOR = OL_BASE + "/authors/OL7044246A.json"
OL_AUTHOR2 = OL_BASE + "/authors/OL999999A.json"

#: iTunes `/lookup` 的响应形状 —— 与 `/search` **一致**（`resultCount` + `results`）。
#: 这正是能复用 `_itunes_entry` 的理由；字段值取自 2024 年真机响应（trackId 597944491）。
ITUNES_DOC = {
    "resultCount": 1,
    "results": [{
        "wrapperType": "audiobook",
        "trackId": 597944491,
        "trackName": "Pride and Prejudice",
        "artistName": "Jane Austen",
        "releaseDate": "2013-01-01T08:00:00Z",
        "description": "An Apple Books <b>Classic</b> edition.",
        "genres": ["Fiction & Literature", "Classics"],
        "artworkUrl100": "https://is1-ssl.mzstatic.com/image/thumb/x/100x100bb.jpg",
    }],
}

#: OpenLibrary works 文档的**真实键集**（第 102 期真机核验：key/title/description/
#: subjects/covers/authors/first_publish_date 等；**没有** publisher / isbn / languages）。
OL_DOC = {
    "key": "/works/OL17267881W",
    "title": "Dune",
    "description": {"type": "/type/text", "value": "<p>The saga of Paul Atreides.</p>"},
    "subjects": ["Science fiction, American", "Dune (Imaginary place)"],
    "covers": [9157544],
    "authors": [{"author": {"key": "/authors/OL7044246A"}, "type": {"key": "/type/author_role"}}],
    "first_publish_date": None,
}


@pytest.fixture(autouse=True)
def _clean_state():
    M.clear_cache()
    M._LAST_CALL.clear()
    yield
    M.clear_cache()
    M._LAST_CALL.clear()


class _Routes:
    """`_get_json` 替身：按 URL 精确路由；**没登记的 URL 直接抛**（外呼会立刻暴露）。

    返回 ``calls`` 列表，用例据此断言「回绝路径真的没发请求」。
    """

    def __init__(self, **routes):
        self.routes = routes
        self.calls = []

    def __call__(self, url, params=None, headers=None, method="GET", data=None, hints=None):
        self.calls.append((url, dict(params or {})))
        if url not in self.routes:
            raise AssertionError(f"意料外的外呼：{url}（params={params}）")
        value = self.routes[url]
        return value() if callable(value) else value


# ---------------------------------------------------------------- 声明范围

def test_只有核过的三家声明了详情通道():
    """声明范围**就是**契约：多一家 = 多一个没核过的端点在假装有这项能力。

    要加一家，先真机核出「接口存在 + 形状对得上」，再把它的解析函数写进 `metasources`
    并在声明里填 `detail_name` —— 顺序不能倒（倒过来就是拿单测绿冒充线上可用）。
    """
    assert sorted(M._DETAIL_FETCHERS) == ["audible", "itunes", "openlibrary"]
    for sid, fn in M._DETAIL_FETCHERS.items():
        p = next(x for x in M._src_registry.DECLARED if x.id == sid)
        assert p.detail_name == fn.__name__, f"{sid} 的声明与绑定对不上"
    # 其余家必须是**空声明**（不是「声明了绑不上」，那样 `_bind_declared` 会直接报错）
    others = [p.id for p in M._src_registry.DECLARED if p.id not in M._DETAIL_FETCHERS]
    assert all(not p.detail_name for p in M._src_registry.DECLARED if p.id in others)


def test_详情通了检索就有抓取器():
    """详情是**检索的补充**：没有检索通道的家不该先有详情通道。"""
    assert set(M._DETAIL_FETCHERS) <= set(M.SOURCES)
    assert set(M._DETAIL_FETCHERS) <= set(M.IMPLEMENTED)


# ---------------------------------------------------------------- 回绝路径

def test_没有详情通道的家回明确中文而不是抛异常():
    res = M.detail("comicvine", "12345")

    assert res["ok"] is False and res["entry"] is None
    assert "按 ID 取详情" in res["error"] and "按书名检索" in res["error"]


def test_未知源如实说未知():
    assert "未知源" in M.detail("nope", "x")["error"]


@pytest.mark.parametrize("pid", ["", "   "])
def test_缺标识不外呼(monkeypatch, pid):
    routes = _Routes()
    monkeypatch.setattr(M, "_get_json", routes)

    res = M.detail("itunes", pid)

    assert res["ok"] is False and "缺少" in res["error"]
    assert routes.calls == [], "缺标识不该发外呼"


def test_认不出的标识不外呼(monkeypatch):
    """editions 的 `/books/OL…M` 认不出来 ⇒ 回绝。

    拿它去猜一个 works 地址会回**别的书**的记录 —— 那比失败更糟（用户看不出错了）。
    """
    routes = _Routes()
    monkeypatch.setattr(M, "_get_json", routes)

    res = M.detail("openlibrary", "/books/OL1M")

    assert res["ok"] is False and "标识可能已失效" in res["error"]
    assert routes.calls == []


# ---------------------------------------------------------------- iTunes

def test_itunes详情复用检索的字段映射(monkeypatch):
    routes = _Routes(**{"https://itunes.apple.com/lookup": ITUNES_DOC})
    monkeypatch.setattr(M, "_get_json", routes)

    res = M.detail("itunes", "597944491")

    assert res["ok"] is True
    e = res["entry"]
    assert e["source"] == "itunes"
    assert e["title"] == "Pride and Prejudice"
    assert e["author"] == "Jane Austen"
    assert e["year"] == "2013", "releaseDate 要走与检索同一套年份归一"
    assert e["provider_id"] == "597944491"
    assert e["tags"][:2] == ["Fiction & Literature", "Classics"]
    # 复用 `_itunes_entry` ⇒ 简介也走同一套剥标签（否则标签会落进书目简介）
    assert e["description"] == "An Apple Books Classic edition."
    assert routes.calls == [("https://itunes.apple.com/lookup", {"id": "597944491"})]


@pytest.mark.parametrize("resolution,size", [("high", "1000x1000"), ("standard", "100x100")])
def test_itunes详情尊重封面分辨率(monkeypatch, resolution, size):
    """改设置必须看得出变化 —— 覆盖尺寸只认注册表给的取值。"""
    routes = _Routes(**{"https://itunes.apple.com/lookup": ITUNES_DOC})
    monkeypatch.setattr(M, "_get_json", routes)

    e = M.detail("itunes", "597944491", {"resolution": resolution})["entry"]

    assert e["cover_url"].endswith(f"{size}bb.jpg")


def test_itunes不同分辨率不共用缓存(monkeypatch):
    """`opts` 进缓存键的**详情侧**证明：先 high 再 standard 必须发第二次外呼。"""
    routes = _Routes(**{"https://itunes.apple.com/lookup": ITUNES_DOC})
    monkeypatch.setattr(M, "_get_json", routes)

    a = M.detail("itunes", "597944491", {"resolution": "high"})["entry"]
    b = M.detail("itunes", "597944491", {"resolution": "standard"})["entry"]

    assert len(routes.calls) == 2, "换了选项还命中缓存 ⇒ 用户改了设置看不出变化"
    assert a["cover_url"] != b["cover_url"]


def test_itunes空结果回明确说明而不是假装可用(monkeypatch):
    routes = _Routes(**{"https://itunes.apple.com/lookup": {"resultCount": 0, "results": []}})
    monkeypatch.setattr(M, "_get_json", routes)

    res = M.detail("itunes", "999999999999")

    assert res["ok"] is False and res["entry"] is None
    assert "没有返回这条记录" in res["error"], "不能报成「可用」——界面据此会说元数据是新的"


# ---------------------------------------------------------------- OpenLibrary

def test_openlibrary详情会取字典简介的值(monkeypatch):
    """真机核验：`description` 是 `{"type": "/type/text", "value": …}`。

    直接透给 `_entry` 会被 `str()` 成一坨 Python 字面量落进简介（用户直接看见）。
    """
    routes = _Routes(**{OL_WORK: OL_DOC, OL_AUTHOR: {"name": "Frank Herbert"}})
    monkeypatch.setattr(M, "_get_json", routes)

    e = M.detail("openlibrary", "/works/OL17267881W")["entry"]

    assert e["title"] == "Dune"
    assert e["description"] == "The saga of Paul Atreides."
    assert "{'type'" not in e["description"]
    # subject 的复合值要按逗号拆开，否则整串成了一个标签（还过不了黑名单）
    assert e["tags"][:2] == ["Science fiction", "American"]
    assert e["cover_url"] == "https://covers.openlibrary.org/b/id/9157544-L.jpg"
    assert e["provider_id"] == "/works/OL17267881W"
    assert e["author"] == "Frank Herbert"


def test_openlibrary详情会逐条补作者名(monkeypatch):
    """works 文档只有作者边的 key；名字要再查一次（并拼成与检索一致的形式）。"""
    doc = dict(OL_DOC, authors=[{"author": {"key": "/authors/OL7044246A"}},
                                {"author": {"key": "/authors/OL999999A"}}])
    routes = _Routes(**{OL_WORK: doc, OL_AUTHOR: {"name": "Frank Herbert"},
                        OL_AUTHOR2: {"name": "Kevin J. Anderson"}})
    monkeypatch.setattr(M, "_get_json", routes)

    e = M.detail("openlibrary", "/works/OL17267881W")["entry"]

    assert e["author"] == "Frank Herbert, Kevin J. Anderson"
    assert [c[0] for c in routes.calls] == [OL_WORK, OL_AUTHOR, OL_AUTHOR2]


def test_openlibrary单个作者查不到不影响整条详情(monkeypatch):
    """详情是**补字段**用的：第 2 位作者超时不该让整条作废（宁可少一个名字）。"""
    doc = dict(OL_DOC, authors=[{"author": {"key": "/authors/OL7044246A"}},
                                {"author": {"key": "/authors/OL999999A"}}])

    def boom():
        raise httpx.ConnectTimeout("模拟第 2 位作者超时")

    routes = _Routes(**{OL_WORK: doc, OL_AUTHOR: {"name": "Frank Herbert"}, OL_AUTHOR2: boom})
    monkeypatch.setattr(M, "_get_json", routes)

    res = M.detail("openlibrary", "/works/OL17267881W")

    assert res["ok"] is True
    assert res["entry"]["author"] == "Frank Herbert"


def test_openlibrary不猜出版年出版社ISBN(monkeypatch):
    """works 端点**没有**这三项（在 edition 上）⇒ 留空。

    宁可少几个字段，也不要凭空给一本书安一个出版年 —— 用户没法分辨那是不是编的，
    而「看起来填好了」比空着危险得多。
    """
    routes = _Routes(**{OL_WORK: OL_DOC, OL_AUTHOR: {"name": "Frank Herbert"}})
    monkeypatch.setattr(M, "_get_json", routes)

    e = M.detail("openlibrary", "/works/OL17267881W")["entry"]

    assert (e["year"], e["publisher"], e["isbn"]) == ("", "", "")


def test_openlibrary接受裸标识并归一成works地址(monkeypatch):
    """库里存的是 `/works/OL…W`，但用户可能粘裸 id 或带查询串的 URL 过来。"""
    routes = _Routes(**{OL_WORK: OL_DOC, OL_AUTHOR: {"name": "Frank Herbert"}})
    monkeypatch.setattr(M, "_get_json", routes)

    for raw in ("OL17267881W", "ol17267881w",
                "https://openlibrary.org/works/OL17267881W?edition=x"):
        M.clear_cache()
        res = M.detail("openlibrary", raw)
        assert res["ok"] is True, f"{raw} 应能归一"
        assert res["entry"]["provider_id"] == "/works/OL17267881W"


def test_openlibrary空文档如实失败(monkeypatch):
    """HTTP 200 但正文没有 title（下架的占位文档）⇒ 不能当成一条正常记录。"""
    routes = _Routes(**{OL_WORK: {"key": "/works/OL17267881W"}})
    monkeypatch.setattr(M, "_get_json", routes)

    assert M.detail("openlibrary", "/works/OL17267881W")["ok"] is False


# ---------------------------------------------------------------- Audible

AUDIBLE_ASIN = "B002V1OF70"
AUDIBLE_URL = "https://api.audible.com/1.0/catalog/products/" + AUDIBLE_ASIN
AUDIBLE_UK_URL = "https://api.audible.co.uk/1.0/catalog/products/" + AUDIBLE_ASIN
#: 检索与详情**逐字同组**（第 99 期：带一个非法组名会让接口 400、整家永远 0 结果）
AUDIBLE_CALL = {"response_groups": "product_desc,contributors,media,series"}

#: Audible `/1.0/catalog/products/{asin}` 的**真实响应**（第 115 期真机核验，ASIN B002V1OF70）：
#: 单条包在 `{"product": {…}}` 里，字段形状与检索**完全一致** —— 这正是能复用
#: `_audible_entry` 的理由（写第二份字段映射就是 §7.1 说的「第二份实现」）。
AUDIBLE_DOC = {"product": {
    "asin": AUDIBLE_ASIN,
    "title": "Dune",
    "subtitle": "Book One in the Dune Chronicles",
    "authors": [{"name": "Frank Herbert"}],
    "narrators": [{"name": n} for n in (
        "Scott Brick", "Orlagh Cassidy", "Euan Morton", "Simon Vance", "Ilyana Kadushin",
        "Byron Jennings", "David R. Gordon", "Jason Culp", "Kent Broadhurst", "Oliver Wyman",
        "Patricia Kilgarriff", "Scott Sowers")],
    "series": [{"title": "Dune", "sequence": "1"},
               {"title": "The Dune Sequence", "sequence": "12"}],
    "publisher_name": "Macmillan Audio",
    "publication_datetime": "2007-05-29T01:13:52Z",
    "language": "english",
    "product_images": {"500": "https://m.media-amazon.com/images/I/x._SL500_.jpg"},
}}


def test_audible详情复用检索的字段映射(monkeypatch):
    """第 115 期新接：`/products/{asin}` 与检索**同端点、同响应组、同形状**。

    这家的意义就是**演播者**：检索已经能拿到（第 103 期），但只有存过 ASIN 的书
    才能用精确键回查 —— 而那正是「库里记过的书」最常见的形态。
    """
    routes = _Routes(**{AUDIBLE_URL: AUDIBLE_DOC})
    monkeypatch.setattr(M, "_get_json", routes)

    res = M.detail("audible", AUDIBLE_ASIN)

    assert res["ok"] is True
    e = res["entry"]
    assert e["source"] == "audible"
    assert e["title"] == "Dune"
    assert e["subtitle"] == "Book One in the Dune Chronicles"
    assert e["author"] == "Frank Herbert"
    # 真机 Dune 是 **12 位**演播者 —— 一条不少（第 116 期起上限按字段取，见 `MULTI_VALUE_MAX`；
    # 旧口径与 `tags` 共用 `[:8]`，会把这份阵容砍成 8 位）
    assert e["narrators"] == ["Scott Brick", "Orlagh Cassidy", "Euan Morton", "Simon Vance",
                              "Ilyana Kadushin", "Byron Jennings", "David R. Gordon",
                              "Jason Culp", "Kent Broadhurst", "Oliver Wyman",
                              "Patricia Kilgarriff", "Scott Sowers"]
    # 多支系列里取**卷号最小**的那支（不是第一条）—— 与检索同一套 `_best_series`
    assert (e["series"], e["series_index"]) == ("Dune", "1")
    assert (e["year"], e["publisher"]) == ("2007", "Macmillan Audio")
    assert e["provider_id"] == AUDIBLE_ASIN
    assert routes.calls == [(AUDIBLE_URL, AUDIBLE_CALL)]


def test_audible详情按区域换分站(monkeypatch):
    """UK / DE / JP 的 ASIN 在 US 站查不到 ⇒ 区域必须跟着 `opts` 走。"""
    routes = _Routes(**{AUDIBLE_UK_URL: AUDIBLE_DOC})
    monkeypatch.setattr(M, "_get_json", routes)

    assert M.detail("audible", AUDIBLE_ASIN, {"region": "uk"})["ok"] is True
    assert routes.calls == [(AUDIBLE_UK_URL, AUDIBLE_CALL)]


def test_audible不同区域不共用缓存(monkeypatch):
    """`opts` 进缓存键的**详情侧**证明：先 us 再 uk 必须发第二次外呼。

    否则「用户把区域从 us 改成 uk」看不出任何变化 —— 回的是 US 站的缓存。
    """
    routes = _Routes(**{AUDIBLE_URL: AUDIBLE_DOC, AUDIBLE_UK_URL: AUDIBLE_DOC})
    monkeypatch.setattr(M, "_get_json", routes)

    M.detail("audible", AUDIBLE_ASIN)
    M.detail("audible", AUDIBLE_ASIN, {"region": "uk"})

    assert [c[0] for c in routes.calls] == [AUDIBLE_URL, AUDIBLE_UK_URL]


def test_audible空结果回明确说明(monkeypatch):
    """`{"product": null}`（ASIN 已下架）⇒ 如实说「没返回」，不能报成可用。"""
    routes = _Routes(**{AUDIBLE_URL: {"product": None}})
    monkeypatch.setattr(M, "_get_json", routes)

    res = M.detail("audible", AUDIBLE_ASIN)

    assert res["ok"] is False and res["entry"] is None
    assert "没有返回这条记录" in res["error"]


# ---------------------------------------------------------------- 缓存 / 限流

def test_详情命中缓存不再外呼(monkeypatch):
    routes = _Routes(**{OL_WORK: OL_DOC, OL_AUTHOR: {"name": "Frank Herbert"}})
    monkeypatch.setattr(M, "_get_json", routes)

    a = M.detail("openlibrary", "/works/OL17267881W")
    n = len(routes.calls)
    b = M.detail("openlibrary", "/works/OL17267881W")

    assert len(routes.calls) == n, "第二次应命中缓存"
    assert a["entry"] == b["entry"]


def test_详情与检索的缓存键不互撞(monkeypatch):
    """详情回 dict、检索回 list：共用键会让双方都解析不出东西，而且**都不报错**。"""
    assert M._detail_key("openlibrary", "x") != M._cache_key("openlibrary", "x", "", 5)
    assert M._detail_key("openlibrary", "", "")[0] == "@detail"

    routes = _Routes(**{OL_WORK: OL_DOC, OL_AUTHOR: {"name": "Frank Herbert"}})
    monkeypatch.setattr(M, "_get_json", routes)
    monkeypatch.setattr(M, "_FETCHERS", {"openlibrary": lambda *a: [
        {"title": "Dune", "author": "Frank Herbert"}]})

    M.search("openlibrary", "Dune", "Frank Herbert", 5)
    assert M.detail("openlibrary", "/works/OL17267881W")["ok"] is True, "检索的缓存不该被详情读到"


def test_详情照常走限流(monkeypatch):
    """详情与检索**共用**同一家的限流窗口（同一台主机，分开记等于把频率翻倍）。"""
    seen = []
    monkeypatch.setattr(M, "_throttle", lambda s: seen.append(s))
    monkeypatch.setattr(M, "_get_json", _Routes(**{OL_WORK: OL_DOC,
                                                   OL_AUTHOR: {"name": "Frank Herbert"}}))

    M.detail("openlibrary", "/works/OL17267881W")

    assert seen == ["openlibrary"]


# ---------------------------------------------------------------- 错误文案

def test_错误文案按状态码分开(monkeypatch):
    """同一份文案给 `search` 与 `detail` 用 —— 两处各写一份必然走散。"""
    def _err(code):
        req = httpx.Request("GET", "https://example.com")
        return httpx.HTTPStatusError("boom", request=req,
                                     response=httpx.Response(code, request=req))

    assert "反爬" in M._error_text(_err(302))
    assert "下架" in M._error_text(_err(404)), "404 是「记录没了」，不是「站点坏了」"
    assert M._error_text(_err(500)) == "接口返回错误（HTTP 500）"
    assert "连接失败" in M._error_text(httpx.ConnectError("x"))
    assert "请求超时" in M._error_text(httpx.ReadTimeout("x"))
    # `_raise_for_status` 抛的是 RuntimeError（429/401/403 的中文口径），原样透出
    assert M._error_text(RuntimeError("被限流（429）：稍后再试")) == "被限流（429）：稍后再试"


def test_检索也走同一套错误文案(monkeypatch):
    """把 `_error_text` 抽出来的意义：`search` 的 302/404 口径与 `detail` 一致。"""
    def boom(title, author, limit, opts):
        req = httpx.Request("GET", "https://example.com")
        raise httpx.HTTPStatusError("boom", request=req, response=httpx.Response(404, request=req))

    monkeypatch.setitem(M._FETCHERS, "openlibrary", boom)

    assert "下架" in M.search("openlibrary", "三体", "刘慈欣", 5)["error"]


def test_来源抛异常时详情回错误而不是抛(monkeypatch):
    def boom(url, **kw):
        raise httpx.ConnectError("网络不可达")

    monkeypatch.setattr(M, "_get_json", boom)

    res = M.detail("openlibrary", "/works/OL17267881W")

    assert res["ok"] is False and "连接失败" in res["error"]
