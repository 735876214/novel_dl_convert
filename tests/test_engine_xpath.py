"""第 94 期 · 阶段 2c：**XPath 通道**（唯一执行处 `rules._xpath_nodes`）。

## 证据（`202003.txt`，1537 条真实 2.x 书源，实测）

共 **120 条**源里有 XPath（搜索列表 48 / 目录 46 / 正文 16 / 搜索字段 10），形状只有三种：

1. **搜索列表**（文档级取一批条目）+ **搜索字段**（`//dd[1]/h3[1]/a[1]/text()`、
   `//dt[1]/a[1]/@href`）——字段是**相对当天那条结果**求值的；
2. **目录容器**（`//*[@class="chapterlist"]/dd/a`，已经取到 `<a>`）；
3. **正文容器**（`//body[1]/div[2]/div[3]/div[3]`、`//*[@id="content"]/text()`，文档级）。

补上这条通道后：可用条数 **993 → 1042**（+49），XPath 类阻塞从 106 条降到 46 条
（其中 27 条是**真的通道对不上**：容器是 XPath、字段却写着阅读的选择器方言
`tag.a.0@href` —— 如实点名，仍判不可用）。

## 本文件钉住的东西

* 三种形状**真的取到值**（不是只过审计的纸面能力）；
* **字段相对条目求值**（漏了那个 `.` 会在整页里取到第一条 —— 十条结果全指向同一本书，
  而且一个错都不报）；
* **红线**：XPath 写坏了只许空值 + 人话，绝不许抛异常（搜索 / 目录的调用点没有 try）；
* **降级如实**：没装 lxml ⇒ 引擎取空值、审计报「需要 lxml（未安装）」，**不冒充可用**；
* 通道判据只有 `selspec.is_xpath` 一处（含「带 `{` 的相对地址模板不算 XPath」那道闸）。
"""
import json
import pathlib

import pytest

from novelforge.sources import formats, legado, rules, selspec

FIXTURE2 = pathlib.Path(__file__).parent / "fixtures" / "legado2_real.json"

PAGE = """
<html><body>
<div id="content">第1段<br>第2段<span>行内</span></div>
<ul class="list">
  <li><h3><a href="/b/1">一</a></h3><span class="au">甲</span></li>
  <li><h3><a href="/b/2">二</a></h3><span class="au">乙</span></li>
</ul>
<dl class="chapterlist"><dd><a href="/c/1">第一章</a></dd><dd><a href="/c/2">第二章</a></dd></dl>
<div class="imgs"><img data-src="/i/1.jpg"><img src="/i/2.jpg"></div>
</body></html>
"""


def _rule(**search) -> dict:
    sp = {"url": "https://a.com/s?q={title}", "mode": "xpath",
          "container": '//*[@class="list"]/li',
          "fields": {"title": "//h3/a/text()", "url": "//a/@href"}}
    sp.update(search)
    return {"name": "xpath 源", "domains": ["a.com"], "search": sp,
            "book": {"mode": "single",
                     "content": {"mode": "xpath", "container": '//*[@id="content"]'}}}


# ---------------- 通道判据（唯一一处：selspec.is_xpath）----------------

@pytest.mark.parametrize("value, want", [
    ("//a/@href", True),
    (".//a", True),
    ("//*[@id=\"content\"]/text()", True),
    ("  //div[@class='x']/ul/li  ", True),
    # ⚠️ 下面这些**不是** XPath：相对链接 / 相对地址模板（实测 2.x 真源里成片出现，
    #    按「以 `/` 开头」判会把它们当 XPath ⇒ 取不到值且没有痕迹）
    ("/i/{$.NovelID}/", False),
    ("/Book/getChapterListByBookId?bookId={$._id}", False),
    ("/book/123", False),
    ("{{$.x}}/a", False),
    ("class.a@text", False),
    ("tag.a.0@href", False),
    ("", False),
    (None, False),
    (3, False),
])
def test_is_xpath的形状判据(value, want):
    assert selspec.is_xpath(value) is want
    assert (legado._leading_mode(value) == "xpath") is want


def test_通道选择与判据同一份():
    """`legado._leading_mode` 对 XPath 的判定**就是** `selspec.is_xpath`（不是第二份）。"""
    from novelforge.sources.legado import _leading_mode
    assert _leading_mode("//a/@href") == "xpath"
    assert _leading_mode("//*[@id='c']/text()") == "xpath"
    assert _leading_mode("/i/{$.NovelID}/") == "css"      # 地址模板，不是 XPath
    assert _leading_mode("tag.a.0@href") == "css"
    assert _leading_mode("@js:result") == "js"


# ---------------- 三种形状真的取到值 ----------------

def test_正文容器是文档级():
    assert rules._extract(PAGE, {"mode": "xpath", "container": '//*[@id="content"]'}) == \
        "第1段\n第2段行内"
    # `html: true` 保留标签（与 css 通道的 `@html` 同一口径）
    assert "<br>" in rules._extract(PAGE, {"mode": "xpath", "container": '//*[@id="content"]',
                                           "html": True})
    # 容器直接写 `/text()` 取到的是**直接文本子节点**（`<span>行内</span>` 不在其中 —— 这是
    # XPath 自己的语义，不是本项目挑三拣四）；多条用换行拼，与 CSS 通道同一分段口径。
    assert rules._extract(PAGE, {"mode": "xpath", "container": '//*[@id="content"]/text()'}) == \
        "第1段\n第2段"


def test_搜索字段相对条目求值():
    got = rules._parse_search(PAGE, {"mode": "xpath", "container": '//*[@class="list"]/li',
                                     "fields": {"title": "//h3/a/text()",
                                                "author": "//span/text()",
                                                "url": "//a/@href"}}, "https://a.com/")
    assert [(g["title"], g["author"], g["url"]) for g in got] == \
        [("一", "甲", "https://a.com/b/1"), ("二", "乙", "https://a.com/b/2")], got


def test_漏了点号会在整页取到第一条():
    """把「相对条目求值」这件事**直接钉在** `_xpath_nodes` 上（这是最贵的那个坑）。

    真源里搜索字段写的是 `//dd[1]/h3[1]/a[1]/text()` 这种「看着像绝对路径」的形式 ——
    不补那个 `.`，十条搜索结果会**全部指向同一本书**，而且一个错都不报。
    """
    node = rules._xpath_nodes(PAGE, '//*[@class="list"]/li')[1]      # 第二条结果
    assert rules._xpath_nodes(node, "//h3/a/text()")[0] == "一"       # 文档级 ⇒ 取到第一条（错）
    assert rules._xpath_nodes(node, "//h3/a/text()", rel=True)[0] == "二"


def test_目录容器已经取到a():
    got = rules._extract_links(PAGE, {"mode": "xpath",
                                      "container": '//*[@class="chapterlist"]/dd/a'},
                               "https://a.com/")
    assert got == [("第一章", "https://a.com/c/1"), ("第二章", "https://a.com/c/2")], got


def test_目录容器直接取属性也认():
    """`//*[@class="chapterlist"]/dd/a/@href`（结果全是字符串，没有属性可读）⇒ 字符串就是地址。"""
    got = rules._extract_links(PAGE, {"mode": "xpath",
                                      "container": '//*[@class="chapterlist"]/dd/a/@href'},
                               "https://a.com/")
    assert [u for _, u in got] == ["https://a.com/c/1", "https://a.com/c/2"], got


def test_资源清单也吃懒加载兜底():
    """漫画 / 音频的地址清单走同一套兜底：`url_attr` → `data-src` → `data-original` → `href`。"""
    got = rules._extract_pages(PAGE, {"mode": "xpath", "container": '//div[@class="imgs"]/img'},
                               "https://a.com/")
    assert got == ["https://a.com/i/1.jpg", "https://a.com/i/2.jpg"], got


def test_xpath能过审计也能过校验():
    rule = _rule()
    assert rules.validate_rule(rule) == []
    assert rules.audit_native_rule(rule) == []


# ---------------- 红线：写坏了只许空值 + 人话 ----------------

@pytest.mark.parametrize("bad", ["//li[", "//*[@id=", "//a[not(", "", None, 3, "   "])
def test_xpath写坏了不抛异常(bad):
    """搜索 / 目录的调用点**没有 try 保护** —— XPath 编不过时抛出去就是整次搜索 500。"""
    assert rules._extract(PAGE, {"mode": "xpath", "container": bad}) == ""
    assert rules._parse_search(PAGE, {"mode": "xpath", "container": bad,
                                      "fields": {"url": "//a/@href"}}, "https://a.com/") == []
    assert rules._extract_links(PAGE, {"mode": "xpath", "container": bad}, "https://a.com/") == []
    assert rules._extract_pages(PAGE, {"mode": "xpath", "container": bad}, "https://a.com/") == []


def test_编不过的xpath会被点名():
    rule = _rule(container="//li[")
    bad = rules.audit_native_rule(rule)
    assert [b["construct"] for b in bad] == ["xpath_syntax"], bad
    assert "改写成能跑的 XPath" in bad[0]["instead"]


def test_在css通道写xpath会被点名():
    """XPath 有了自己的通道之后，这一条只剩一个意思：「你在 **CSS** 通道里写了 XPath」。"""
    rule = _rule()
    rule["search"] = {"url": "https://a.com/s?q={title}", "mode": "css",
                      "container": '//*[@class="list"]/li', "fields": {"url": "a::attr(href)"}}
    bad = rules.audit_native_rule(rule)
    assert [b["construct"] for b in bad] == ["xpath"], bad
    assert "mode" in bad[0]["instead"] or "xpath" in bad[0]["instead"]


def test_在xpath通道写选择器会被点名():
    """镜像的那一半（实测 27 条）：容器是 XPath、字段却写着阅读的选择器方言。

    阅读是**按每个值**判通道的（`tag.a.0@href` 走它自己的方言解析），本项目按通道逐项判
    ⇒ 这一项真的取不到值。报 `Invalid expression` 用户看不懂，得直接说「这一项是选择器写法」。
    """
    rule = _rule(fields={"url": "tag.a.0@href", "title": "class.title.0@text"})
    bad = rules.audit_native_rule(rule)
    assert {b["construct"] for b in bad} == {"selector_in_xpath"}, bad
    assert all("选择器写法" in b["why"] for b in bad)


def test_xpath通道也要有地址字段():
    """结构性缺口与 CSS 通道同一口径：没有 url 字段 ⇒ 搜什么都回 0 条。"""
    rule = _rule(fields={"title": "//h3/a/text()"})
    bad = rules.audit_native_rule(rule)
    assert [b["construct"] for b in bad] == ["no_url_field"], bad


def test_校验要求xpath容器():
    for key in ("search", "toc"):
        rule = _rule()
        if key == "search":
            rule["search"] = {"url": "https://a.com/s?q={title}", "mode": "xpath"}
        else:
            rule["book"] = {"mode": "toc", "toc": {"mode": "xpath"},
                            "content": {"mode": "css", "container": "#c", "text": True}}
        assert any("xpath" in e and "container" in e for e in rules.validate_rule(rule)), key


# ---------------- 降级如实（lxml 缺失）----------------

def test_lxml缺失时如实降级(monkeypatch):
    """缺 lxml ⇒ 引擎取空值（不抛异常）+ 审计**当场说清**，绝不冒充可用。"""
    monkeypatch.setattr(rules, "lxml_available", lambda: False)
    assert rules._extract(PAGE, {"mode": "xpath", "container": '//*[@id="content"]'}) == ""
    assert rules._parse_search(PAGE, _rule()["search"], "https://a.com/") == []
    bad = rules.audit_native_rule(_rule())
    # 每一项都要说（容器 + 两个字段）——只报一项会让用户改完一处又撞一处
    assert {b["construct"] for b in bad} == {"missing_dep"} and len(bad) >= 3, bad
    assert all("lxml" in b["why"] for b in bad)


# ---------------- 2.x 真样本整链（夹具里的 XPath 源）----------------

@pytest.fixture(scope="module")
def entries2() -> list:
    return json.loads(FIXTURE2.read_text(encoding="utf-8"))


def _by_name(entries: list, name: str) -> dict:
    for e in entries:
        if str(e.get("bookSourceName") or "").strip() == name:
            return e
    raise AssertionError(f"夹具里没有 {name}")


def test_2x的xpath源现在转得出规则(entries2):
    """`妙笔阁`：搜索列表 / 搜索字段 / 目录 / 正文**四处全是 XPath**（真实 2.x 条目，一字未改）。"""
    got = formats.map_entry(_by_name(entries2, "妙笔阁"))
    assert got["supported"] == "yes", got["unsupported_fields"]
    rule = got["converted_rule"]
    assert rules.validate_rule(rule) == [] and rules.audit_native_rule(rule) == []
    assert rule["search"]["mode"] == "xpath"
    assert rule["search"]["container"] == "//body[1]/div[2]/div[1]/div[2]/dl"
    assert rule["search"]["fields"]["url"] == "//dt[1]/a[1]/@href"
    assert rule["book"]["toc"]["mode"] == "xpath"
    assert rule["book"]["content"]["mode"] == "xpath"


def test_2x的xpath源字段真的取到值(entries2):
    """纸面「能转」不算数：拿一段与站点同形的 HTML 跑一遍，标题 / 地址要真的出来。"""
    rule = formats.map_entry(_by_name(entries2, "妙笔阁"))["converted_rule"]
    # 与容器 `//body[1]/div[2]/div[1]/div[2]/dl` 同形的页面
    html = ("<html><body><div>x</div><div><div><div>a</div><div><dl>"
            "<dt><a href='/book/1'>封面</a></dt>"
            "<dd><h3><a>剑来</a></h3></dd><dd><a>烽火戏诸侯</a><a>甲</a></dd>"
            "</dl></div></div></div></div></body></html>")
    got = rules._parse_search(html, rule["search"], "https://www.imiaobige.com/")
    assert got and got[0]["url"] == "https://www.imiaobige.com/book/1", got
    # 字段是**相对那条 `<dl>`** 取的：`//dd[2]/a[2]/text()` 取的是第二个 `dd` 里的第二个 `<a>`
    assert got[0]["title"] == "剑来" and got[0]["author"] == "甲", got


def test_2x混合通道的源不再被误判(entries2):
    """`读书迷`：搜索是 XPath、正文却是阅读的选择器方言（`id.BookText@textNodes`）。

    阅读按**每个值**判通道，所以这条源在阅读里是能跑的 ⇒ 本项目也要按通道分别归一
    （搜索 xpath / 正文 css），而不是把整条判死。
    """
    got = formats.map_entry(_by_name(entries2, "读书迷"))
    assert got["supported"] in ("yes", "partial"), got["unsupported_fields"]
    rule = got["converted_rule"]
    assert rule["search"]["mode"] == "xpath"
    assert rule["book"]["toc"]["mode"] == "xpath"
    assert rule["book"]["content"]["mode"] == "css"
    assert rule["book"]["content"]["container"] == "#BookText"
    assert rules.audit_native_rule(rule) == []
