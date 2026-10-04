"""第 94 期 · 阶段 2a：**取值 spec 的引擎能力**（唯一实现 `novelforge/sources/selspec.py`）。

## 这一版修的是什么

转换诚实闸（`rules.audit_native_rule`）在阶段 1 拦下了四类构造：阅读索引（`tr!0` / `.odd.0`）、
阅读选择器语法（`class.` / `@text` / `@css:`）、候选与拼接（`|` / `||` / `&&`）、`##正则##替换`。
拦下来是对的（当年它们真的会让 `<a>` 搜一次就抛异常），但**拦住不等于支持** ——
实测 22 条真实样本里成片是这四类写法。

阶段 2a 把它们**补进引擎**：`selspec` 一个模块负责「解析 + 执行」，`rules.py` 的每个取值点
都从它拿值，`legado.py` 只负责把解析结果写回成 spec 文本。于是闸门里那四条**摘掉**
（继续拦就是误杀），本文件就是「补上的那些用例」：

* :func:`test_闸门摘掉的四条现在真的会跑` —— 审计说能跑；
* :func:`test_四条构造真的取出值来` —— **执行期真的取到值**（不是只过审计的纸面能力）；
* :func:`test_索引是列表位置_不是nth_of_type` —— 索引语义按实测口径（取匹配列表第 n 个）；
* :func:`test_写坏的选择器走空值不抛异常` —— **红线**：搜索 / 目录的调用点没有 try 保护。

⚠️ 这一版**没有**吃掉的东西（继续如实拦着）：`children[0]`（实测真源里的写法，
不是合法 CSS，语义不明 ⇒ 不猜）、XPath、`@js:`、JSONPath 子集之外的语法、选项字典。
"""
import pytest

from novelforge.sources import rules, selspec

SEARCH_HTML = """
<html><body>
<div class="book-item"><a href="/b/1">一</a><span class="author">作者：甲</span></div>
<div class="book-item"><a href="/b/2">二</a><span class="author">作者：乙</span></div>
</body></html>
"""


def _rule(container=".book", fields=None, url="https://a.com/s?q={title}", **extra) -> dict:
    """一份**最小可跑**的 native 规则（与 `test_convert_honesty.py` 同一个形状）。"""
    search = {"url": url, "mode": "css", "container": container,
              "fields": fields if fields is not None else {"title": ".t", "url": "a::attr(href)"}}
    search.update(extra.pop("search", {}))
    rule = {"name": "测试源", "domains": ["a.com"], "search": search,
            "book": {"mode": "single", "content": {"mode": "css", "container": "#c", "text": True}}}
    rule.update(extra)
    return rule


# ---------------- 闸门摘掉的四条：现在**必须**判「能跑」 ----------------

@pytest.mark.parametrize("mutate, note", [
    (lambda r: r["search"].update({"container": "#author tbody tr!0"}), "索引 `!0`"),
    (lambda r: r["search"].update({"container": "#author tbody tr!-1"}), "负索引 `!-1`"),
    # ⚠️ 索引写在**一段的末尾**（`@` 分段），`ul!0:1:-1 li` 那种空格写法不是阅读的语法
    #    （实测真样本里没有），引擎会给人话错误 —— 见 `test_写完索引后面还接空格要给人话`
    (lambda r: r["search"].update({"container": "ul!0:1:-1@li"}), "多段索引 `!0:1:-1`"),
    (lambda r: r["search"]["fields"].update({"author": ".odd.0"}), "2.x 的 `.0` 索引"),
    (lambda r: r["search"]["fields"].update({"author": ".author text##作者："}), "`##正则##替换`"),
    (lambda r: r["search"]["fields"].update({"author": ".a##作者：##"}), "`##正则##替换`（替换成空）"),
    (lambda r: r["search"].update({"container": "class.book-item"}), "阅读前缀 `class.`"),
    (lambda r: r["search"].update({"container": "id.nr"}), "阅读前缀 `id.`"),
    (lambda r: r["search"].update({"container": "@css:.item"}), "`@css:` 前缀"),
    (lambda r: r["search"]["fields"].update({"author": ".a@text"}), "`@text` 取值"),
    (lambda r: r["search"].update({"container": ".a tag.li"}), "`tag.` 前缀"),
    (lambda r: r["search"].update({"container": ".a|.b"}), "候选（单竖线，2.x）"),
    (lambda r: r["search"].update({"container": ".a||.b"}), "候选（双竖线，3.x）"),
    (lambda r: r["search"].update({"container": ".a && .b"}), "拼接 `&&`"),
    (lambda r: r["search"]["fields"].update({"cover": "img@src"}), "裸属性名 `src`"),
    (lambda r: r["search"]["fields"].update({"title": "class.title.0@tag.a.0@text"}), "整条阅读写法"),
])
def test_闸门摘掉的四条现在真的会跑(mutate, note):
    """摘掉一条构造**必须**同时补一个「它现在跑得动」的用例，否则闸门会从「诚实」滑向「误杀」。"""
    rule = _rule()
    mutate(rule)
    bad = rules.audit_native_rule(rule)
    assert bad == [], f"{note} 还被拦着（阶段 2a 已补进引擎）：{bad}"


def test_四条构造真的取出值来():
    """**执行期**验收（不只是「审计说能跑」）——纸面能力与真能力是两回事。"""
    # 索引：容器取「第 2 个」⇒ 只搜到第二个条目
    got = rules._parse_search(SEARCH_HTML, {"mode": "css", "container": ".book-item!1",
                                            "fields": {"url": "a::attr(href)"}},
                              "https://a.com/")
    assert [g["url"] for g in got] == ["https://a.com/b/2"], got

    # 阅读写法：`class.` / `tag.` 前缀 + `@text` / `@href`
    got = rules._parse_search(SEARCH_HTML, {"mode": "css", "container": "class.book-item",
                                            "fields": {"title": "tag.a.0@text",
                                                       "url": "tag.a.0@href"}},
                              "https://a.com/")
    assert [(g["title"], g["url"]) for g in got] == [("一", "https://a.com/b/1"),
                                                     ("二", "https://a.com/b/2")], got

    # `##正则##替换`：取到值之后替换（`作者：` 要去掉）
    soup = rules._soup(SEARCH_HTML)
    assert rules._field_value(soup, ".book-item.0@.author@text##作者：") == "甲"
    # 只写 `##正则`（没有替换段）= 删掉命中
    assert rules._field_value(soup, ".book-item.0@.author@text##作者：") == "甲"

    # 候选 `||`：取第一个非空的（第一路取不到 ⇒ 落到第二路）
    assert rules._field_value(soup, ".nope@text||.author@text") == "作者：甲"
    # 拼接 `&&`：两段接起来
    assert rules._field_value(soup, ".author@text && .author@text") == "作者：甲作者：甲"
    # `@css:`：后面整段就是标准 CSS（含逗号候选写法）
    assert rules._field_value(soup, "@css:.author @text") == "作者：甲"


def test_正则替换只有一处实现():
    """`##正则##替换` 与 `ruleContent.replaceRegex` 共用 `selspec.replace_text` —— 语义一致。"""
    assert selspec.replace_text("第12章 起风了", r"第(\d+)章", r"$1.") == ("12. 起风了", "")
    assert selspec.replace_text("abc", "(", "")[1]                    # 编不过 ⇒ 如实报错
    text, err = selspec.replace_text("abc", "b", "X")
    assert (text, err) == ("aXc", "")


def test_索引是列表位置_不是nth_of_type():
    """索引的语义是「**匹配列表**里的第 n 个」，不是 CSS 的 `:nth-of-type(n+1)`。

    `.odd.0` 跨多个父节点时两者结果不同（`nth-of-type` 会每个父节点各取一个）——
    所以按结果列表取，不做「差不多等价」的翻译。
    """
    soup = rules._soup("<div><p class='odd'>甲</p></div><div><p class='odd'>乙</p></div>")
    assert rules._field_value(soup, ".odd.0") == "甲"
    assert rules._field_value(soup, ".odd!1") == "乙"
    assert rules._field_value(soup, ".odd!-1") == "乙"
    # 越界的那一段**跳过**（不是取不到就整条作废）
    assert rules._field_value(soup, ".odd!0:9") == "甲"


# ---------------- 红线：写坏了只许给空值 + 人话，绝不许抛异常 ----------------

@pytest.mark.parametrize("bad", [
    "@@bad",              # 空的 `@` 段
    ".a@@",               # 结尾多一个 `@`
    "[unclosed",          # CSS 括号不配对（soupsieve 会抛）
    "children[0] a",      # 实测真源写法，不是合法 CSS
    "//div[@id='x']",     # XPath（通道对不上）
    "$.data.list",        # JSON 路径（通道对不上）
    "id.content@html#<js>result",   # `<js>` 贴在单 `#` 后面（跑脚本，不是替换）
])
def test_写坏的选择器走空值不抛异常(bad):
    """**红线**：搜索与目录的调用点没有 try 保护 —— 当年一条「判可用」的规则会让整次搜索 500。"""
    sp = {"mode": "css", "container": bad, "fields": {"url": "a::attr(href)"}}
    assert rules._parse_search(SEARCH_HTML, sp, "https://a.com/") == []
    assert rules._extract_links(SEARCH_HTML, {"container": bad}, "https://a.com/") == []
    assert rules._field_value(rules._soup(SEARCH_HTML), bad) == ""
    # 正文路径（历史上有 try，现在同样走空值）
    assert rules._extract(SEARCH_HTML, {"mode": "css", "container": bad}) == ""
    # 而且**人话原因**要拿得到（界面「查看原因」直接用这句）
    assert selspec.spec_error(selspec.parse_spec(bad))


def test_坏替换正则只是不替换_不炸取值():
    """`##` 的正则编不过：那一段当没写（并留 `note` 给闸门报），**取值本身照常**。

    取值是「没洗过的原文」而不是空 —— 空会把「替换写坏了」伪装成「这一项没有值」。
    """
    plan = selspec.parse_spec(".author##(未闭合")
    assert plan.note and not plan.error
    assert selspec.value(rules._soup(SEARCH_HTML), plan) == "作者：甲"
    bad = rules.audit_native_rule(_rule(fields={"title": ".author##(未闭合",
                                                "url": "a::attr(href)"}))
    assert {b["construct"] for b in bad} == {"replace_regex"}, bad


def test_索引后面还接空格要给人话():
    """`tr!0 li`（索引后面还接空格）**不是阅读的语法**（实测真样本里索引都在一段的末尾）。

    不给人话的话，用户只会看到「不是合法 CSS 选择器」—— 看不出「该用 `@` 分段」。
    """
    err = selspec.spec_error(selspec.parse_spec("#author tbody tr!0 li"))
    assert "索引" in err and "@" in err, err
    # 而按语法写的那条照样跑（同一件事，只差一个分隔符）
    assert selspec.spec_error(selspec.parse_spec("#author tbody tr!0@li")) == ""


def test_坏输入不许把取值带崩():
    """脏输入（None / 非字符串 / 空）一律当空值 —— 取值点没有 try 保护也无所谓。"""
    soup = rules._soup(SEARCH_HTML)
    for junk in (None, "", ".", "./", "  ", 3, object()):
        assert isinstance(rules._field_value(soup, junk), str)


# ---------------- 阶段 2c：2.x 的单个 `#` + `@children` 的渲染往返 ----------------

def test_单井号是2x的替换分隔符():
    r"""单个 `#` 与 `##` **同义** —— 实测 2.x 里两者成对出现（206 条只卡在这里）。

    证据（`202003.txt`）：同一条目既有 `.mlist@html##^\s*##<br>` 也有 `.brief_text@html#^#<br>`，
    还有 `tag.p.0@text#.*? \| (.*?) \| 已?(.+?)中?[\s]*(\d[^|]+).*#$1,$2,$3` 这种**两侧都写一个**。
    """
    plan = selspec.parse_spec(".brief_text@html#^#<br>")
    assert not plan.error and not selspec.spec_error(plan)
    assert plan.mode == "html" and [st.css for st in plan.steps] == [".brief_text"]
    assert len(plan.replace) == 1
    soup = rules._soup("<div class='brief_text'>^正文</div>")
    assert selspec.value(soup, selspec.parse_spec(r".brief_text@text#\^#<br>")) == "<br>正文"
    # 只写一段 ⇒ 删掉命中（与 `##` 一个口径）
    assert selspec.value(soup, selspec.parse_spec("div@text#正文")) == "^"
    # 三段写法：`选择器#正则#替换`，`$1` 照旧转 `\g<1>`
    assert selspec.value(soup, selspec.parse_spec(r"div@text#\^(.*)$#$1")) == "正文"
    # 与 `##` 的结果必须**一字不差**（同一份实现，不是第二套）
    for a, b in ((".brief_text@html#^#<br>", ".brief_text@html##^##<br>"),
                 ("div@text#正文", "div@text##正文"),
                 (".a@text#x#y", ".a@text##x##y")):
        pa, pb = selspec.parse_spec(a), selspec.parse_spec(b)
        assert selspec.render(pa) == selspec.render(pb), (a, b)
        assert selspec.value(soup, pa) == selspec.value(soup, pb), (a, b)


def test_单井号不会误切id选择器():
    """`.a#b@html` / `.a #b` / `#main p` 里的 `#` 是 **id 选择器** —— 切错了会静默改坏取值。"""
    for css, mode in ((".a#b@html", "html"), (".a#b", "text"), (".a #b", "text"),
                      ("#main p", "text"), ("html#main", "text")):
        plan = selspec.parse_spec(css)
        assert not plan.replace, (css, plan)
        assert plan.mode == mode, (css, plan)
    assert not selspec.spec_error(selspec.parse_spec(".a #b"))       # 编译得过就是纯 CSS
    # 而前缀解析不出来的（`@css:` 残段）也不切 —— 宁可不动
    assert not selspec.parse_spec("@css:#list").replace
    # `<js>` 贴在 `#` 后面是在跑脚本，不是替换
    assert "js" in selspec.spec_error(selspec.parse_spec("id.content@html#<js>result"))


def test_children步渲染往返一致():
    """`@children` 步渲染时不能再带一个 `@` —— 否则拼出 `.pt-read-text@@children`（实测 35 条被误判死）。"""
    for raw in ("class.cover@children", ".pt-read-text@children", ".mySearch!0@children",
                "@children", "class.cover@children@tag.a"):
        plan = selspec.parse_spec(raw)
        assert not plan.error, (raw, plan.error)
        text = selspec.render(plan)
        assert "@@" not in text, (raw, text)
        again = selspec.parse_spec(text)
        assert not again.error, (raw, text, again.error)
        assert not selspec.spec_error(again), (raw, text)
        assert [(st.css, st.index, st.kind) for st in again.steps] == \
               [(st.css, st.index, st.kind) for st in plan.steps], (raw, text)


def test_children步真的取子元素():
    """渲染往返只是纸面 —— 子元素要真的取到（`.cover@children` 取的是**子元素**不是后代）。

    容器走 `select()`（要列表），字段走 `value()`（只要第一个）—— 两处语义本来就不一样。
    """
    soup = rules._soup("<ul class='cover'><li>甲</li><li>乙</li></ul>")
    for raw in ("class.cover@children", ".cover!0@children", "ul.cover@children"):
        nodes = selspec.select(soup, selspec.parse_spec(raw))
        assert [n.name for n in nodes] == ["li", "li"], raw
        assert [n.get_text() for n in nodes] == ["甲", "乙"], raw
    assert selspec.value(soup, selspec.parse_spec("class.cover@children")) == "甲"
