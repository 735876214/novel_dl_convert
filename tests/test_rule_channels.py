"""第 86 期：取值通道（css / regex / **json**）与书源变量 `{var:<key>}`。

两个承诺：

1. **JSONPath 子集真的能用**（酷我 `$.data.content`、番茄 `$.data.content`），且
   **取不到就如实返回空**，不抛异常 —— 站点回 HTML 错误页是家常便饭，不能因此打断整本抓取；
2. **缺变量绝不出网**：带着 `{var:密钥}` 去请求，站点会回空页，报错离原因十万八千里。
"""
import asyncio
import json

import pytest

from novelforge.sources import rules


# ---------------- JSONPath 子集 ----------------

def test_jsonpath子集():
    data = {"data": {"content": "正文",
                     "list": [{"title": "一", "url": "a"}, {"title": "二", "url": "b"}],
                     "nested": {"deep": {"content": "深"}}}}
    assert rules.json_path(data, "$.data.content") == "正文"
    assert rules.json_path(data, "$") is data
    assert rules.json_path(data, "") is data
    assert rules.json_path(data, "$.data.list[0].title") == "一"
    assert rules.json_path(data, "$.data.list[1].url") == "b"
    assert rules.json_path(data, "$.data.list[*].url") == ["a", "b"]
    # 取不到一律 None（调用方据此当「这次没取到」），不抛
    assert rules.json_path(data, "$.data.missing") is None
    assert rules.json_path(data, "$.data.list[9]") is None
    assert rules.json_path(data, "$.content.data") is None
    assert rules.json_path(None, "$.a") is None
    assert rules.json_path(data, "..content") == ["正文", "深"]     # 递归下降


def test_json模式取正文与目录():
    body = json.dumps({"data": {
        "content": "第一章 正文",
        "chapters": [{"title": "第一章", "url": "/c/1"}, {"title": "第二章", "url": "/c/2"}]}},
        ensure_ascii=False)
    assert rules._extract(body, {"mode": "json", "path": "$.data.content"}) == "第一章 正文"
    # 数组 / 对象压成空串：正文位置塞一个 JSON 数组进书里就是乱码
    assert rules._extract(body, {"mode": "json", "path": "$.data.chapters"}) == ""

    links = rules._extract_links(body, {"mode": "json", "path": "$.data.chapters"},
                                "https://x.com/book/1")
    assert links == [("第一章", "https://x.com/c/1"), ("第二章", "https://x.com/c/2")]

    # 站点回了 HTML 错误页：如实返回空，绝不抛
    assert rules._extract("<html>404</html>", {"mode": "json", "path": "$.a"}) == ""
    assert rules._extract_links("<html>", {"mode": "json", "path": "$.a"}, "https://x.com") == []


def test_json模式搜索():
    body = json.dumps({"data": {"list": [{"n": "三体", "a": "刘慈欣", "u": "/b/1"}]}},
                      ensure_ascii=False)
    sp = {"mode": "json", "path": "$.data.list",
          "fields": {"title": "$.n", "author": "$.a", "url": "$.u"}}
    assert rules._parse_search(body, sp, "https://x.com") == [
        {"title": "三体", "author": "刘慈欣", "url": "https://x.com/b/1"}]
    # 结果数组为空 / 不是数组时返回空表
    assert rules._parse_search('{"data": {"list": []}}', sp, "https://x.com") == []
    assert rules._parse_search('{"data": {}}', sp, "https://x.com") == []


def test_校验器认json模式():
    base = {"name": "j", "domains": ["x.com"],
            "search": {"url": "https://x.com", "mode": "json"},
            "book": {"mode": "toc", "toc": {"mode": "json"},
                     "content": {"mode": "css", "container": "#c"}}}
    errs = rules.validate_rule(base)
    assert any("search 为 json 模式时 path 必填" in e for e in errs)
    assert any("book.toc 为 json 模式时 path 必填" in e for e in errs)

    ok = json.loads(json.dumps(base))
    ok["search"]["path"] = "$.data.list"
    ok["book"]["toc"]["path"] = "$.data.chapters"
    assert rules.validate_rule(ok) == [], "补上 path 后必须通过"


# ---------------- 书源变量 ----------------

def test_变量渲染与缺失():
    txt, missing = rules.render_vars("https://x.com/s?k={var:密钥}&m={var:模式}", {"密钥": "K"})
    assert "k=K" in txt and "{var:模式}" in txt, "缺失的**保留原文**，不静默留空"
    assert missing == ["模式"]

    rule = {"name": "r", "search": {"url": "https://x.com?k={var:密钥}"},
            "book": {"mode": "single", "content": {"mode": "css", "container": "#{var:模式}"}}}
    out, miss = rules.render_rule_vars(rule, {"密钥": "K", "模式": "c"})
    assert out["search"]["url"].endswith("k=K") and out["book"]["content"]["container"] == "#c"
    assert miss == []
    assert rule["search"]["url"].endswith("{var:密钥}"), "渲染不改入参"
    assert rules.var_keys(rule) == ["密钥", "模式"]


def test_缺变量时出网前如实报错(isolated):                                  # noqa: ARG001
    cls = rules.make_rule_class({
        "name": "需要密钥的源", "domains": ["x.com"],
        "search": {"url": "https://x.com?k={var:密钥}", "mode": "css", "container": ".i",
                   "fields": {"title": ".t", "url": "a::attr(href)"}},
        "book": {"mode": "single", "content": {"mode": "css", "container": "#c"}}})
    src = cls()
    assert src.missing_vars == ["密钥"]
    # client 传 None 也不会被用到 —— 检查发生在**出网之前**
    with pytest.raises(ValueError, match="缺少书源变量"):
        asyncio.run(src.search_page(None, "三体", 1))


def test_变量齐了就能正常渲染(isolated):                                    # noqa: ARG001
    from novelforge.core import db
    cls = rules.make_rule_class({
        "name": "有密钥的源", "domains": ["x.com"],
        "search": {"url": "https://x.com?k={var:密钥}", "mode": "css", "container": ".i",
                   "fields": {"title": ".t", "url": "a::attr(href)"}},
        "book": {"mode": "single", "content": {"mode": "css", "container": "#c"}}})
    db.source_vars_set("有密钥的源", "密钥", "ABC")
    src = cls()
    assert src.missing_vars == [] and src._RULE["search"]["url"].endswith("k=ABC")


# ---------------- 正文压纯文本：行内标签不断段（第 93 期）----------------
# 真机验证逮到的缺陷：`node.get_text("\n")` 会在**每个标签边界**插换行，
# `<b>` / `<em>` / `<a>` / `<span>` 这类行内标签于是把一句话剁成好几段。
# 这条链是 css 模式（绝大多数规则）取正文的唯一入口，下载 / 追更 / 预览 / 在线读全走它。

def test_按css规则取正文时行内标签不断段():
    html = ('<html><body><div id="c">\n'
            '  <p>甲<b>乙</b>丙</p>\n'
            '  <div>丁<a href="/x">戊</a>己<br>庚</div>\n'
            '  <script>steal()</script><style>p{color:red}</style>\n'
            '</div></body></html>')
    out = rules._extract_css(html, {"container": "#c"})
    assert out == "甲乙丙\n丁戊己\n庚", repr(out)
    assert "steal" not in out and "color" not in out, "script / style 要连内容一起丢"


def test_块级标签才算分段与空行折叠():
    html = '<div id="c"><p>一</p>\n\n\n<p>   </p><p>二</p></div>'
    assert rules._extract_css(html, {"container": "#c"}) == "一\n二"


def test_纯文本正文不过解析器():
    """规则的正文提取本来就给纯文本时，正文里合法的 `<` 是内容而不是标记。"""
    assert rules.html_to_text("他笑了 <3 然后走了") == "他笑了 <3 然后走了"


def test_解析器缺席时兜底同样不断行内标签():
    """bs4 炸了（或没装）也不能把行内标签当换行 —— 兜底也要读得下去。"""
    import builtins

    real = builtins.__import__

    def boom(name, *a, **kw):
        if name == "bs4":
            raise ImportError("模拟没有 bs4")
        return real(name, *a, **kw)

    builtins.__import__ = boom
    try:
        out = rules.html_to_text("<p>甲<b>乙</b>丙</p><p>丁</p>")
    finally:
        builtins.__import__ = real
    assert out == "甲乙丙\n丁", repr(out)
