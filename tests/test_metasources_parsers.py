"""第 57 期：14 家元数据提供商的**解析**契约（全部离线，不碰公网）。

做法：只 monkeypatch 出网收口层 —— `metasources._get_json` / `metasources._get_text`，
喂各家真实响应形状的样例，断言候选字段映射正确。这样：

- 解析逻辑 100% 可离线回归（网络不可用的 CI 也能跑）；
- 抓取型 6 家（HTML）也照样测得了 —— 它们的真实可用性无法离线保证（站点反爬 / 改版），
  但「页面结构没变时解析对不对」是可测的，这才是代码的责任边界。

⚠️ 样例是**手工按各站文档/页面结构写的**，不是实时抓的：它们钉住的是「我们的解析器对这份
结构怎么解」，**不**代表站点现在就是这个结构（这也是注册表 `fragile` 标记的意义）。
"""
import novelforge.core.metasources as m


def _patch(monkeypatch, json_router=None, text_router=None):
    """把两个出网口换成路由函数：按 URL 子串命中。**

    router 形式：``{"itunes": {...响应...}}``（返回 dict/str），未命中抛断言方便定位。
    """
    def fake_json(url, params=None, headers=None, method="GET", data=None, hints=None):
        for key, val in (json_router or {}).items():
            if key in url:
                return val
        raise AssertionError(f"未预置该 URL 的假响应：{url}")

    def fake_text(url, params=None, headers=None, hints=None):
        for key, val in (text_router or {}).items():
            if key in url:
                return val
        raise AssertionError(f"未预置该 URL 的假响应：{url}")

    monkeypatch.setattr(m, "_get_json", fake_json)
    monkeypatch.setattr(m, "_get_text", fake_text)


def _one(source, title="x", author="y", opts=None):
    r = m.search(source, title, author, 5, opts)
    assert r["ok"] is True, r
    return r["entries"]


# ---------------- 公开 JSON 接口 ----------------

def test_itunes_解析并放大封面(monkeypatch):
    _patch(monkeypatch, json_router={"itunes": {"results": [{
        "trackName": "Dune", "artistName": "Frank Herbert", "publisher": "Ace",
        "releaseDate": "1965-08-01T07:00:00Z", "description": "沙丘",
        "genres": ["科幻", "冒险"], "artworkUrl100": "https://x/100x100bb.jpg",
        "trackId": 7,
    }]}})
    e = _one("itunes")[0]

    assert e["title"] == "Dune" and e["author"] == "Frank Herbert"
    assert e["year"] == "1965" and e["tags"] == ["科幻", "冒险"]
    # 默认分辨率 = high（1000×1000）；standard 的取值在下面的专门用例里验
    assert e["cover_url"] == "https://x/1000x1000bb.jpg", "封面应换成大图尺寸"


def test_audnexus_解析对象数组作者(monkeypatch):
    _patch(monkeypatch, json_router={"audnexus": {"books": [{
        "asin": "B01N", "title": "Project Hail Mary",
        "authors": [{"name": "Andy Weir"}], "publisherName": "Audible Studios",
        "releaseDate": "2021-05-04", "description": "太空求生",
        "genres": [{"name": "科幻"}], "language": "english",
        "image": "https://x/a.jpg",
    }]}})
    e = _one("audnexus")[0]

    assert e["title"] == "Project Hail Mary" and e["author"] == "Andy Weir"
    assert e["publisher"] == "Audible Studios" and e["year"] == "2021"
    assert e["tags"] == ["科幻"] and e["language"] == "en"


def test_ranobedb_两段式补详情(monkeypatch):
    _patch(monkeypatch, json_router={
        "/books": {"books": [{"id": 41, "title": "青春猪头少年", "lang": "ja",
                              "c_release_date": 2014}]},
        "/book/41": {"id": 41, "description": "简介", "publishers": [{"name": "KADOKAWA"}],
                     "editions": [{"staff": [{"role_type": "author", "name": "鸭志田一"}]}]},
    })
    e = _one("ranobedb")[0]

    assert e["title"] == "青春猪头少年"
    assert e["author"] == "鸭志田一", "作者只有详情里有（列表不返回 staff）"
    assert e["publisher"] == "KADOKAWA" and e["year"] == "2014"
    assert e["description"] == "简介"
    assert e["cover_url"] == "", "官方没公布封面 CDN 前缀 ⇒ 宁可留空也不拼猜测 URL"


def test_ranobedb_详情失败回落列表字段(monkeypatch):
    def json_router(url, params=None, headers=None, method="GET", data=None, hints=None):
        if url.endswith("/books"):
            return {"books": [{"id": 9, "title": "某轻小说", "lang": "ja"}]}
        raise RuntimeError("详情接口 500")

    monkeypatch.setattr(m, "_get_json", json_router)
    e = _one("ranobedb")[0]

    assert e["title"] == "某轻小说" and e["author"] == "", "单本详情失败只丢那本的字段"


# ---------------- 需密钥接口 ----------------

def test_hardcover_映射作者出版社封面(monkeypatch):
    _patch(monkeypatch, json_router={"hardcover": {"data": {"books": [{
        "title": "Dune", "description": "沙丘", "release_date": "1965-06-01",
        "slug": "dune", "contributions": [{"author": {"name": "Frank Herbert"}}],
        "publisher": {"name": "Ace"}, "image": {"url": "https://x/h.jpg"},
    }]}}})
    e = _one("hardcover", opts={"api_key": "tok"})[0]

    assert e["title"] == "Dune" and e["author"] == "Frank Herbert"
    assert e["publisher"] == "Ace" and e["year"] == "1965" and e["raw_id"] == "dune"


def test_comicvine_映射卷信息(monkeypatch):
    _patch(monkeypatch, json_router={"comicvine": {"results": [{
        "id": 12345, "name": "Saga", "description": "太空歌剧漫画",
        "publisher": {"name": "Image"}, "start_year": "2012",
        "image": {"medium_url": "https://x/cv.jpg"},
    }]}})
    e = _one("comicvine", opts={"api_key": "k"})[0]

    assert e["title"] == "Saga" and e["publisher"] == "Image"
    assert e["year"] == "2012" and e["cover_url"] == "https://x/cv.jpg"


def test_aladin_能从带前缀的响应里抠出JSON(monkeypatch):
    body = ('var aladinResult = {"item": [{"title": "채식주의자", "author": "한강", '
            '"publisher": "창비", "pubDate": "2007-10-30", "isbn13": "9788936433598", '
            '"cover": "https://x/al.jpg", "categoryName": "소설>한국소설", "itemId": "1"}]};')
    _patch(monkeypatch, text_router={"aladin": body})
    e = _one("aladin", opts={"api_key": "ttb"})[0]

    assert e["title"] == "채식주의자" and e["isbn"] == "9788936433598"
    assert e["tags"] == ["소설", "한국소설"], "分类是按 > 拆开的层级标签"


# ---------------- 页面抓取型（易失效）----------------

def test_amazon_按data_asin解析(monkeypatch):
    html = (
        '<div data-asin="B000000001"><span class="a-size-medium a-color-base a-text-normal">三体</span>'
        '<span class="a-size-base">刘慈欣</span></div>'
        '<div data-asin="B000000002"><span class="a-size-medium a-color-base a-text-normal">三体 II</span>'
        '<span class="a-size-base">刘慈欣</span></div>'
    )
    _patch(monkeypatch, text_router={"amazon": html})
    items = _one("amazon")

    assert [i["title"] for i in items] == ["三体", "三体 II"]
    assert items[0]["author"] == "刘慈欣" and items[0]["raw_id"] == "B000000001"


def test_goodreads_按tr块解析(monkeypatch):
    html = (
        '<tr itemscope><td><a class="bookTitle" href="/book/show/1"><span>Dune</span></a>'
        '<a class="authorName"><span itemprop="name">Frank Herbert</span></a></td></tr>'
    )
    _patch(monkeypatch, text_router={"goodreads": html})
    e = _one("goodreads")[0]

    assert e["title"] == "Dune" and e["author"] == "Frank Herbert"
    assert e["raw_id"] == "/book/show/1"


def test_kobo_从NEXT_DATA递归找书(monkeypatch):
    html = ('<script id="__NEXT_DATA__" type="application/json">'
            '{"props":{"pageProps":{"items":[{"title":"Dune","authors":[{"name":"Frank Herbert"}],'
            '"url":"/us/en/ebook/dune"}]}}}</script>')
    _patch(monkeypatch, text_router={"kobo": html})
    e = _one("kobo")[0]

    assert e["title"] == "Dune" and e["author"] == "Frank Herbert"


def test_audible_按catalog接口解析(monkeypatch):
    _patch(monkeypatch, json_router={"audible": {"products": [{
        "asin": "B07", "title": "Dune", "authors": [{"name": "Frank Herbert"}],
        "publisher_name": "Macmillan Audio", "publication_datetime": "2019-05-28",
        "publisher_summary": "沙丘有声版", "language": "english",
        "series": [{"title": "Dune"}], "product_images": {"500": "https://x/au.jpg"},
    }]}})
    e = _one("audible")[0]

    assert e["title"] == "Dune" and e["author"] == "Frank Herbert"
    assert e["cover_url"] == "https://x/au.jpg" and e["tags"] == ["Dune"]


def test_librofm_标题与作者配对(monkeypatch):
    html = (
        '<a class="audiobook-list__title" href="/audiobooks/1">Dune</a>'
        '<a class="audiobook-list__title" href="/audiobooks/2">Dune Messiah</a>'
        '<span class="audiobook-list__author">Frank Herbert</span>'
        '<span class="audiobook-list__author">Frank Herbert</span>'
    )
    _patch(monkeypatch, text_router={"libro": html})
    items = _one("librofm")

    assert [i["title"] for i in items] == ["Dune", "Dune Messiah"]
    assert items[0]["author"] == "Frank Herbert"


def test_lubimyczytac_标题作者配对(monkeypatch):
    html = (
        '<a class="authorAllBooks__singleTextTitle" href="/ksiazka/1">Dune</a>'
        '<a class="authorAllBooks__singleTextTitle" href="/ksiazka/2">Mesjasz Diuny</a>'
        '<a class="authorAllBooks__singleTextAuthor">Frank Herbert</a>'
    )
    _patch(monkeypatch, text_router={"lubimyczytac": html})
    items = _one("lubimyczytac")

    assert [i["title"] for i in items] == ["Dune", "Mesjasz Diuny"]
    assert items[0]["author"] == "Frank Herbert" and items[1]["author"] == ""


# ---------------- 边界：坏响应 / 空响应 ----------------

def test_空响应一律回落空列表且不抛(monkeypatch):
    _patch(monkeypatch, json_router={"": {}}, text_router={"": ""})

    for sid in m.IMPLEMENTED:
        r = m.search(sid, "三体", "刘慈欣", 5, {"api_key": "k"})
        assert r["entries"] == [], (sid, r)
        assert r["ok"] is True, f"{sid} 不该因空响应报错：{r}"


def test_异形响应不让单源炸整轮(monkeypatch):
    """列表里混进 None / 字符串 / 缺字段 —— 解析器只能跳过，不能抛。"""
    _patch(monkeypatch, json_router={
        "itunes": {"results": [None, "不是对象", {"trackName": None}]},
        "/books": {"books": [None, {"id": None, "title": "只有标题"}]},
    }, text_router={"amazon": "<div data-asin=\"BAD\">没有标题</div>"})

    for sid in ("itunes", "ranobedb", "amazon"):
        r = m.search(sid, "x", "y", 5, {"api_key": "k"})
        assert r["ok"] is True, (sid, r)


# ---------------- 行内抓取参数**真的被用上**（不是摆设）----------------

def test_amazon_配了Cookie才带Cookie头(monkeypatch):
    seen: list = []

    def spy(url, params=None, headers=None, hints=None):
        seen.append(headers or {})
        return '<div data-asin="B000000001"><span class="a-size-medium a-color-base a-text-normal">三体</span></div>'

    monkeypatch.setattr(m, "_get_text", spy)

    m.search("amazon", "三体", "", 5, {"cookie": "session-id=1; ubid-main=2"})
    assert seen[0].get("Cookie") == "session-id=1; ubid-main=2", seen[0]

    seen.clear()
    m.search("amazon", "三体", "", 5, {})
    assert "Cookie" not in seen[0], "没配就别带空 Cookie 头（更容易被拦）"


def test_itunes_封面尺寸按配置(monkeypatch):
    _patch(monkeypatch, json_router={"itunes": {"results": [
        {"trackName": "Dune", "artworkUrl100": "https://x/100x100bb.jpg"}]}})

    hi = _one("itunes", opts={"resolution": "high"})[0]
    std = _one("itunes", opts={"resolution": "standard"})[0]

    assert hi["cover_url"] == "https://x/1000x1000bb.jpg"
    assert std["cover_url"] == "https://x/100x100bb.jpg"


def test_kobo_区域与语言进URL(monkeypatch):
    seen: list = []

    def spy(url, params=None, headers=None, hints=None):
        seen.append(url)
        return ""

    monkeypatch.setattr(m, "_get_text", spy)

    m.search("kobo", "Dune", "", 5, {"region": "uk", "language": "en"})
    m.search("kobo", "Dune", "", 5, {})

    assert seen[0] == "https://www.kobo.com/uk/en/search", seen[0]
    assert seen[1] == "https://www.kobo.com/us/en/search", "缺配置要回落 us/en"


def test_audible_地区决定分站(monkeypatch):
    seen: list = []

    def spy(url, params=None, headers=None, method="GET", data=None, hints=None):
        seen.append(url)
        return {"products": []}

    monkeypatch.setattr(m, "_get_json", spy)

    m.search("audible", "Dune", "", 5, {"region": "uk"})
    m.search("audible", "Dune", "", 5, {"region": "未知区域"})

    assert seen[0].startswith("https://api.audible.co.uk/"), seen[0]
    assert seen[1].startswith("https://api.audible.com/"), "没见过的地区回落美站"


def test_两个解析小工具行为():
    assert m._first_json('var x = {"a": 1};') == {"a": 1}
    assert m._first_json("不是 JSON") == {}
    assert m._first_json('前缀 [1,2] 后缀') == {}, "顶层是数组时按空处理（约定只要对象）"

    found = [d for d in m._walk_dicts({"a": [{"title": "t"}]}) if d.get("title")]
    assert found == [{"title": "t"}]
