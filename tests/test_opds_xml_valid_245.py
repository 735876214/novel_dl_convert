"""OPDS feed 必须是**良构 XML**（第 245 期）。

## 缺陷

`ET.tostring` **不校验字符合法性** —— 它只转义 `&` / `<` / `>`，
**原样吐出控制字符**。而 XML 1.0 的合法字符集是
``#x9 | #xA | #xD | [#x20-#xD7FF] | [#xE000-#xFFFD] | [#x10000-#x10FFFF]``，
其它控制字符（``\\x0b`` 垂直制表符、``\\x08`` 退格…）**一律非法**。

**触发条件**：书名 / 作者 / 系列名里含这些字符 ——
⚠️ **POSIX 文件名允许**（只禁 ``/`` 与 ``\\0``）⇒ NAS 上的书名完全可能带；
Windows 不允许，所以**本机测不出来**。

**后果**：生成的 feed **不是良构 XML** ⇒ 客户端（KOReader / OPDS 客户端 / Komga）
**整份解析失败、一本书都看不到**；而本项目自己的界面一切正常 ⇒ 极难定位。

## 这里钉三件事

1. 清洗后的 feed 必须能被 `ET.fromstring` 解析（**良构**）；
2. 合法字符（中文 / `&` / 换行）**原样保留**（不许误伤）；
3. 清洗只发生在**一个地方**（`opds.tostring`）—— 端到端走真实端点验证。
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

from novelforge.core import library, opds


#: 会被 XML 1.0 判非法的字符（POSIX 文件名允许它们）。
#: ⚠️ 不含 `\x00` —— 连 POSIX 文件名都不允许它（造不出这样的书名）。
ILLEGAL = "\x0b\x08\x07\x0c"


def _assert_wellformed(xml: str) -> None:
    ET.fromstring(xml)          # 解析失败会抛 ParseError


def test_含控制字符的书名不会让_feed_变成非法_xml():
    """书名带垂直制表符 / 退格 ⇒ feed 仍必须良构。"""
    feed = ET.Element("feed")
    el = ET.SubElement(feed, "title")
    el.text = "书名" + ILLEGAL + "结尾"
    out = opds.tostring(feed)
    _assert_wellformed(out)
    assert ILLEGAL not in out, "非法字符没被剔掉"


def test_属性里的非法字符也要剔():
    feed = ET.Element("feed")
    el = ET.SubElement(feed, "link")
    el.set("href", "http://x/?a=1" + ILLEGAL + "&b=2")
    out = opds.tostring(feed)
    _assert_wellformed(out)
    assert ILLEGAL not in out


def test_合法字符不被误伤():
    """中文、标点、`&`、换行、制表符**都要留着**。"""
    feed = ET.Element("feed")
    el = ET.SubElement(feed, "title")
    el.text = "三体 & 刘慈欣\t第二行\n第三行"
    out = opds.tostring(feed)
    _assert_wellformed(out)
    root = ET.fromstring(out)
    assert root.find("title").text == "三体 & 刘慈欣\t第二行\n第三行", root.find("title").text


def test_真实_feed_构造路径_带控制字符的书名仍是良构():
    """走**真实的 feed 构造路径**（`acquisition_feed` → `book_entry`）。

    ⚠️ 为什么不经 HTTP 端点：Windows **连文件名都不允许**这些控制字符
    （`OSError: [Errno 22]`）⇒ 本机**造不出**这样的书名 ⇒ 端到端那半段
    只能在 POSIX 上测得到。这里直接喂一条含控制字符的书目条目 ——
    走的仍是生产代码路径（`acquisition_feed` → `book_entry` → `tostring`）。
    """
    books = [{
        "id": "b1",
        "name": "带控制字符" + ILLEGAL + "的书.epub",
        "title": "带控制字符" + ILLEGAL + "的书",
        "author": "作者" + ILLEGAL,
        "mtime": 1700000000.0,
        "format": "EPUB",
    }]
    xml = opds.acquisition_feed("http://nas:8992", "全部书籍", "all", books)
    _assert_wellformed(xml)
    assert ILLEGAL not in xml, "非法字符漏进了 feed"
    # 书名本身要还在（只是控制字符被剔掉）
    assert "带控制字符的书" in xml


def test_端到端_opds_feed_良构(client, auth_headers, isolated):
    """走真实端点：客户端拿到的 feed 必须能解析（OPDS 走 **HTTP Basic**）。"""
    import base64

    from novelforge import config

    config.save_overrides({"opds": {"enabled": True}})
    token = base64.b64encode(b"admin:test1234").decode("ascii")
    r = client.get("/opds/all", headers={"Authorization": f"Basic {token}"})
    assert r.status_code == 200, r.text
    _assert_wellformed(r.text)
