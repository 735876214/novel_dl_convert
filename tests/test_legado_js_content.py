"""第 86 期：**Legado 的 JS 正文能真跑**（导入的源不许静默产出空正文）。

第 1 步里 `legado.convert` 已经把「正文由 JS 算出」的源转成
``book.content = {"mode": "js", "script": …}``，但那条通道当时是 TODO —— `rules._extract`
只认 css / regex / json，会静默落进 css 分支返回空串。症状最难查：**导入成功、下载成功、
书里一个字都没有**。

这一份钉住两端：① 移植脚本读的是**全局 `result`**（Legado 的写法），而本项目手写片段用
`__args[0]` —— 两种读法都必须能用；② `mode=js` 的正文**真的**从 Node 通道取到内容。
"""
import asyncio

import pytest

from novelforge.core import network
from novelforge.sources import legado, rules

_NEED_NODE = pytest.mark.skipif(not network.node_state()["available"],
                               reason="本机没有 Node（部署前提见 /api/sources/capabilities）")


class _StubClient:
    def __init__(self, pages: dict):
        self.pages = pages

    async def get_text(self, url: str) -> str:
        return self.pages[url]


@_NEED_NODE
def test_移植脚本读result_手写脚本读args_两种都能用():
    """两边约定不同，少给一个就会表现成「脚本跑通了但什么都没取到」。"""
    assert asyncio.run(network.run_decrypt("return result.replace('X', '');", "正X文")) == "正文"
    assert asyncio.run(network.run_decrypt("return __args[0].replace('X', '');", "正X文")) == "正文"
    assert asyncio.run(network.run_decrypt("return result;", "一样")) == "一样"


@_NEED_NODE
def test_js正文模式真的取到内容():
    """`mode=js` 的正文：走 Node 通道，而不是被 css 分支静默吞成空串。"""
    src = rules.make_rule_class({
        "name": "js正文源", "domains": ["d.com"],
        "book": {"mode": "toc", "toc": {"mode": "css", "container": "a"},
                 "content": {"mode": "js", "script": "return result.split('|')[1];"}},
    })()
    pages = {"https://d.com/b": '<a href="/c1">一</a>',
             "https://d.com/c1": '标题|正文一'}
    chaps = asyncio.run(src.fetch_book_chapters(_StubClient(pages), {"url": "https://d.com/b"}))
    assert [c["body"] for c in chaps] == ["正文一"], \
        "mode=js 必须真的取到内容（空串是这条通道坏掉的静默症状）"


def test_导入转换出的js正文形状与执行侧对得上():
    """**两端联调**：`legado.convert` 产出的形状，必须正是执行侧认的形状。

    这是最容易脱节的地方 —— 一边写 `{"mode": "js", "script": …}`，另一边只认 css。
    """
    ent = {"bookSourceName": "带JS正文的源", "bookSourceUrl": "https://js-demo.com",
           "bookSourceGroup": "测试", "enabled": True,
           "searchUrl": "https://js-demo.com/search?q={{key}}",
           "ruleSearch": {"bookList": "class.item", "name": "class.t@text",
                          "bookUrl": "class.t@href"},
           "ruleBookInfo": {"tocUrl": "class.t@href"},
           "ruleToc": {"chapterList": "id.list@tag.a", "chapterName": "text",
                       "chapterUrl": "href"},
           "ruleContent": {"content": "@js:return result.split('|')[1];"}}
    an = legado.analyze(ent)
    assert an["supported"] in ("yes", "partial"), an["unsupported_fields"]
    rule = an["converted_rule"]
    spec = (rule.get("book") or {}).get("content") or {}
    assert spec.get("mode") == "js" and "return" in spec.get("script", "")
    assert spec["script"] == legado.js_port(ent["ruleContent"]["content"])["script"]

    # 形状对上了 ⇒ 同一个脚本喂给执行侧，真的出内容
    if network.node_state()["available"]:
        src = rules.make_rule_class({**rule, "name": "js形状联调"})()
        got = asyncio.run(src._content("标题|正文一", spec))
        assert got == "正文一"


def test_含android桥的js正文判不可执行():
    """真的跑不了的（`java.*`）仍要如实判 `no`，不许因为「有了 JS 通道」就放行。"""
    an = legado.analyze({"bookSourceName": "桥源", "bookSourceUrl": "https://bridge-demo.com",
                         "searchUrl": "https://bridge-demo.com/search?q={{key}}",
                         "ruleSearch": {"bookList": "class.item", "name": "class.t@text",
                                        "bookUrl": "class.t@href"},
                         "ruleToc": {"chapterList": "id.list@tag.a", "chapterName": "text",
                                     "chapterUrl": "href"},
                         "ruleContent": {"content": "@js:return java.ajax(result);"}})
    assert an["supported"] == "no"
    assert any("java." in u["field"] or "java.ajax" in str(u) for u in an["unsupported_fields"])
