"""第 86 期：Node 解密通道**接进内容链路**（真机跑 Node；本机没有 Node 时相应用例 skip）。

三件事：① 包装层让 `return` 合法（否则片段会撞 `SyntaxError: Illegal return statement`，
看起来像「规则写错了」，其实是调用方式错了）；② 片段没交出字符串时**如实报错**，
不许把 `undefined` 当明文写进书里；③ 规则里的 `decrypt_js` **真的在取正文时被用上**
（只测 `run_decrypt` 能跑，测不出「接线接上了没有」）。
"""
import asyncio

import pytest

from novelforge.core import network
from novelforge.sources import rules

_NEED_NODE = pytest.mark.skipif(not network.node_state()["available"],
                               reason="本机没有 Node（部署前提见 /api/sources/capabilities）")


class _StubClient:
    """桩客户端：按 URL 回页面（**不出网**）。"""

    def __init__(self, pages: dict):
        self.pages = pages

    async def get_text(self, url: str) -> str:
        return self.pages[url]


def _rule(**book) -> dict:
    return {"name": "需要解密的源", "domains": ["d.com"],
            "book": {"mode": "toc", "toc": {"mode": "css", "container": "a"},
                     "content": {"mode": "css", "container": "#c"}},
            **book}


# ---------------- 通道本身（真机 Node）----------------

@_NEED_NODE
def test_包装让片段里的return合法():
    assert asyncio.run(network.run_decrypt("return __args[0].toUpperCase();", "abc")) == "ABC"
    # 中文要能原样回（第 86 期刚修过子进程编码：不指定 UTF-8 时中文会崩在读线程里）
    assert asyncio.run(network.run_decrypt('return __args[0] + "（已解密）";', "密文")) == "密文（已解密）"


@_NEED_NODE
def test_片段漏return时如实报错():
    with pytest.raises(RuntimeError, match="没有返回字符串"):
        asyncio.run(network.run_decrypt("var x = 1;", "abc"))
    with pytest.raises(RuntimeError, match="没有返回字符串"):
        asyncio.run(network.run_decrypt("return {a: 1};", "abc"))


# ---------------- 接线（规则 → 取正文）----------------

def test_没配解密片段就原样返回():
    src = rules.make_rule_class(_rule())()
    assert src.decryption_js() is None
    assert asyncio.run(src._decrypt("原文")) == "原文", "没配就别碰 Node（本机没 Node 也能过）"
    assert asyncio.run(src._decrypt("")) == ""


@_NEED_NODE
def test_规则里的片段真的用在取正文上():
    """**这一条才是接线测试**：走 `_fetch_toc` → 每章正文都必须过解密。"""
    src = rules.make_rule_class(_rule(decrypt_js="return __args[0].replace('X', '');"))()
    pages = {"https://d.com/b": '<a href="/c1">一</a><a href="/c2">二</a>',
             "https://d.com/c1": '<div id="c">正X文一</div>',
             "https://d.com/c2": '<div id="c">正X文二</div>'}
    chaps = asyncio.run(src.fetch_book_chapters(_StubClient(pages), {"url": "https://d.com/b"}))
    assert [c["title"] for c in chaps] == ["一", "二"]
    assert [c["body"] for c in chaps] == ["正文一", "正文二"], "每章正文都要过解密片段"
