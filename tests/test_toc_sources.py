"""第 85 期批次 B：官方书城「目录来源」注册表 + 只取目录 + 覆盖层（**全程零网络**）。

三条口径各钉一遍：

1. **注册表不许说谎**：`status` 三档如实、与 `rule` 自洽（`unsupported` 就必须没有规则）、
   没验证过的必须带 `verified: False`；内置规则还要真能过 `validate_toc_rule`
   （结构合法 = 用户拿到手能直接改，而不是一段看着像的假 JSON）。
2. **只取目录**：取一次目录**只请求搜索页与书页两个地址**，绝不请求任何一章的正文 ——
   这是本模块存在的理由，也是最容易被后续改动悄悄破坏的一条（多一个 `fetch_content` 就够了）。
3. **覆盖层只改名与补卷名**：本地 `index` / 顺序 / 条数一条不动，未映射的不改名，
   本地已有卷名不被书城覆盖。
"""
import asyncio
from urllib.parse import quote

import pytest

from novelforge.core import reading_list
from novelforge.sources import rules, toc_sources


# ---------------- 注册表 ----------------

def test_注册表三档如实且与规则自洽():
    ids = [s["id"] for s in toc_sources.SOURCES]
    assert len(ids) == len(set(ids)) and ids, "注册表不能有重复 id"
    for ent in toc_sources.SOURCES:
        assert ent["status"] in (toc_sources.AVAILABLE, toc_sources.NEEDS_CREDENTIALS,
                                 toc_sources.UNSUPPORTED), ent
        assert isinstance(ent.get("verified"), bool), f"{ent['id']} 必须显式声明是否验证过"
        if ent["status"] == toc_sources.UNSUPPORTED:
            assert not ent.get("rule"), f"{ent['id']} 标了 unsupported 就不该带规则"
            assert ent.get("note"), f"{ent['id']} 至少要说清为什么没支持"
        else:
            assert ent.get("rule"), f"{ent['id']} 声称可用却没有规则"


def test_未验证的来源必须标出来():
    """本机对外网络受限 ⇒ 内置规则写得出但验不了。**拿不准就说不准**。"""
    for ent in toc_sources.SOURCES:
        if ent.get("rule") and ent["status"] != toc_sources.AVAILABLE:
            assert ent["verified"] is False, f"{ent['id']} 不该声称已验证"
            assert "验证" in (ent.get("note") or ""), \
                f"{ent['id']} 的说明里要写明「未在本机验证」，别让用户以为是测过的"


def test_内置规则都过只取目录的校验():
    checked = 0
    for ent in toc_sources.SOURCES:
        if not ent.get("rule"):
            continue
        checked += 1
        assert toc_sources.validate_toc_rule(ent["rule"]) == [], ent["id"]
    assert checked >= 2, "至少要有两条内置规则，否则这个注册表只是个空壳"


def test_只取目录不要求_book_content():
    """`rules.validate_rule` 对 `mode=toc` 要求 `book.content`（那是**下载**路径的要求）。

    取目录不读正文，要求它只会逼人写一段永远不用的假规则 —— 所以这里钉住「放宽的那一条
    正是它」，而不是「校验整体失效」。
    """
    rule = toc_sources.by_id("fanqie")["rule"]
    errs = rules.validate_rule(rule)
    assert any("book.content" in e for e in errs), "前提变了：校验器已经不再要求 content"
    assert toc_sources.validate_toc_rule(rule) == []


# ---------------- 解析与匹配（纯函数）----------------

_TOC_HTML = """
<html><body>
<a href="/reader/1">第一章 科学边界</a>
<a href="/reader/2">第二章 台球</a>
</body></html>
"""


def test_解析平铺目录_正则与_css_都行():
    reg = toc_sources.by_id("fanqie")["rule"]["book"]["toc"]
    got = toc_sources.parse_toc(_TOC_HTML, reg, "https://fanqienovel.com/page/1")
    assert [e["title"] for e in got] == ["第一章 科学边界", "第二章 台球"]
    assert [e["depth"] for e in got] == [None, None], "平铺目录的 depth 就是 None"

    css = {"mode": "css", "container": "a", "url_attr": "href"}
    got2 = toc_sources.parse_toc(_TOC_HTML, css, "https://x.com/p")
    assert [e["title"] for e in got2] == ["第一章 科学边界", "第二章 台球"]


def test_两级目录给出卷层级():
    html = """
    <div class="vol"><h2>第一卷 三体世界</h2>
      <a href="/reader/1">第一章</a><a href="/reader/2">第二章</a></div>
    <div class="vol"><h2>第二卷 黑暗森林</h2>
      <a href="/reader/3">第三章</a></div>
    """
    got = toc_sources.parse_toc(
        html, {"section_container": ".vol", "container": "a", "section_title": "h2"}, "https://x.com/p")
    assert [(e["title"], e["depth"]) for e in got] == [
        ("第一卷 三体世界", 1), ("第一章", 2), ("第二章", 2),
        ("第二卷 黑暗森林", 1), ("第三章", 2),
    ]


def test_匹配打分与阈值():
    book = {"title": "三体", "author": "刘慈欣"}
    cands = [
        {"title": "三体", "author": "刘慈欣", "url": "u1"},          # 书名 + 作者 = 1.0
        {"title": "三体（全集）", "author": "刘慈欣", "url": "u2"},  # 包含 + 作者 = 0.7
        {"title": "流浪地球", "author": "刘慈欣", "url": "u3"},      # 无关
    ]
    hit, score = toc_sources.best_match(book, cands)
    assert hit["url"] == "u1" and score == pytest.approx(1.0)

    only_contains = [{"title": "三体（全集）", "author": "", "url": "u2"}]
    hit, score = toc_sources.best_match(book, only_contains)
    assert hit is None and score == pytest.approx(0.5), "0.5 低于阈值 ⇒ 如实说没匹配到，不猜"


def test_标题归一吃掉全角与标点():
    assert toc_sources.norm_title("三体（全集）·") == toc_sources.norm_title("三体(全集)")


# ---------------- 只取目录（桩 client，零网络）----------------

class _FakeClient:
    """只认准备好的那几个地址 —— 出现别的地址就是**多请求了**，直接炸出来。"""

    def __init__(self, pages: dict):
        self.pages = pages
        self.seen: list = []

    async def get_text(self, url):
        self.seen.append(url)
        assert url in self.pages, f"不该请求 {url}"
        return self.pages[url]

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _FakeManager:
    def __init__(self, pages: dict):
        self.client = _FakeClient(pages)

    def _client(self, source):        # noqa: ARG002 —— 与 DownloadManager 同名同形
        return self.client


def _pages_for_fanqie(book_html: str) -> dict:
    search = "https://fanqienovel.com/search?query=" + quote("三体")
    return {
        search: '<a href="/page/123">三体</a>',
        "https://fanqienovel.com/page/123": book_html,
    }


def test_取目录只请求搜索页与书页_不碰任何正文():
    """**本模块的核心纪律**：目录与正文是两个不同的动作。"""
    mgr = _FakeManager(_pages_for_fanqie(_TOC_HTML))
    res = asyncio.run(toc_sources.fetch_toc(mgr, "fanqie", book={"title": "三体", "author": "刘慈欣"}))
    assert res["ok"] is True, res
    assert [e["title"] for e in res["entries"]] == ["第一章 科学边界", "第二章 台球"]
    assert res["store_ref"] == "https://fanqienovel.com/page/123"
    assert mgr.client.seen == [
        "https://fanqienovel.com/search?query=" + quote("三体"),
        "https://fanqienovel.com/page/123",
    ], "一次取目录只该动这两个地址"


def test_取目录_手动指定书页则跳过匹配():
    pages = {"https://fanqienovel.com/page/999": _TOC_HTML}
    mgr = _FakeManager(pages)
    res = asyncio.run(toc_sources.fetch_toc(
        mgr, "fanqie", book={"title": "三体"}, url="https://fanqienovel.com/page/999"))
    assert res["ok"] is True and res["manual"] is True and res["confidence"] == 1.0
    assert mgr.client.seen == ["https://fanqienovel.com/page/999"], "手动指定不该再搜一次"


def test_取目录_没匹配到如实报并附分数():
    pages = _pages_for_fanqie(_TOC_HTML)
    pages["https://fanqienovel.com/search?query=" + quote("不存在的书")] = \
        '<a href="/page/1">完全无关</a>'
    mgr = _FakeManager(pages)
    res = asyncio.run(toc_sources.fetch_toc(mgr, "fanqie", book={"title": "不存在的书"}))
    assert res["ok"] is False and res["entries"] == []
    assert "阈值" in res["note"] and "最高置信度" in res["note"], res["note"]


def test_取目录_页面里没解析出章节时说清是规则过期():
    mgr = _FakeManager(_pages_for_fanqie("<html>没有目录</html>"))
    res = asyncio.run(toc_sources.fetch_toc(mgr, "fanqie", book={"title": "三体"}))
    assert res["ok"] is False
    assert "规则" in res["note"], "要把「规则大概过期了」说出来，而不是只说失败"


def test_未实现的来源不装成功():
    res = asyncio.run(toc_sources.fetch_toc(_FakeManager({}), "weread", book={"title": "三体"}))
    assert res["ok"] is False
    assert "没有内置规则" in res["note"] and "微信读书" in res["note"]


def test_未知来源如实报():
    res = asyncio.run(toc_sources.fetch_toc(_FakeManager({}), "no-such", book={"title": "x"}))
    assert res["ok"] is False and "未知的目录来源" in res["note"]


# ---------------- 覆盖层 ----------------

def _local_flat() -> list:
    """本地：一本平铺的书（标题全是兜底名 —— 正是「目录不清楚」的典型）。"""
    return reading_list.build_reading_list([
        {"title": "第 1 章", "index": 0},
        {"title": "第 2 章", "index": 1},
        {"title": "第 3 章", "index": 2},
    ])


def _store_flat() -> list:
    return [{"title": "楔子", "depth": None},
            {"title": "第一卷", "depth": None},
            {"title": "第一章 科学边界", "depth": None},
            {"title": "第二章 台球", "depth": None},
            {"title": "第三章 射手", "depth": None}]


def test_覆盖层只改名与补卷名_结构与_index_不动():
    local = _local_flat()
    got = reading_list.apply_toc_override(local, _store_flat(), {1: 0, 2: 1, 3: 2})
    flat = [c for g in got for c in g["chapters"]]
    assert [c["index"] for c in flat] == [0, 1, 2], "index 是进度/批注的坐标，不许动"
    assert [c["title"] for c in flat] == ["第一卷", "第一章 科学边界", "第二章 台球"]
    assert got[0]["volume"] == "第一卷", "本地是无名段 ⇒ 用书城那份补上卷名"
    assert "kind" not in got[0], "补到真卷名之后就不该再留着「匿名前后段」的壳"
    assert len(local[0]["chapters"]) == 3 and local[0]["chapters"][0]["title"] == "第 1 章", \
        "必须返回新对象 —— 原地改会让同时持有旧引用的两处看到不同的书"


def test_覆盖层_未映射的条目一条不丢也不改名():
    got = reading_list.apply_toc_override(_local_flat(), _store_flat(), {2: 1})
    flat = [c for g in got for c in g["chapters"]]
    assert len(flat) == 3, "拿不到真值的条目不许被丢掉"
    assert [c["title"] for c in flat] == ["第 1 章", "第一章 科学边界", "第 3 章"]
    assert got[0]["volume"] == "", "只映射到 1/3，比例不够 ⇒ 不许硬安一个卷名"


def test_覆盖层_本地已有卷名不被书城覆盖():
    """EPUB 自带的 nav 层级通常比书城准（书城卷名常带副标题）。"""
    local = reading_list.build_reading_list([
        {"title": "第一卷", "index": 0, "depth": 1},
        {"title": "第一章", "index": 1, "depth": 2},
    ])
    assert local[0]["volume"] == "第一卷"
    # 映射形状是「书城序号 → 本地 index」：书城第 1 条（第四章）↔ 本地 index 1（第一章）
    got = reading_list.apply_toc_override(
        local, [{"title": "第二卷", "depth": None},
                {"title": "第四章 面壁者", "depth": None}], {1: 1})
    assert got[0]["volume"] == "第一卷"
    assert got[0]["chapters"][0]["title"] == "第四章 面壁者", "标题仍应取书城那份"


def test_覆盖层_没有映射或没有目录时原样返回():
    local = _local_flat()
    assert reading_list.apply_toc_override(local, _store_flat(), {}) == local
    assert reading_list.apply_toc_override(local, [], {1: 0}) == local
    assert reading_list.apply_toc_override([], _store_flat(), {1: 0}) == []


# ---------------- 对齐（书城目录 ↔ 本地章节）----------------

def _flat_one(chapters) -> list:
    return [c for g in chapters for c in g["chapters"]]


def test_对齐_本地全是兜底名且条数一致时按顺序配上():
    """**最需要取目录的那类书**：本地全是兜底名（两边标题不可能相等），但条数一致 ⇒ 顺序一一对应。"""
    local = _flat_one(_local_flat())
    assert reading_list.build_pairs(_store_flat()[2:], local) == [(0, 0), (1, 1), (2, 2)]


def test_对齐_条数不一致就一条都不配():
    """书城比本地多出卷名页 / 楔子页时不猜 —— 跳错一格就是**全书章名整体错位**。"""
    local = _flat_one(_local_flat())
    assert reading_list.build_pairs(_store_flat(), local) == []


def test_对齐_标题相等优先于顺序():
    local = _flat_one(reading_list.build_reading_list([
        {"title": "第二章 台球", "index": 0},
        {"title": "第一章 科学边界", "index": 1},
    ]))
    pairs = reading_list.build_pairs([
        {"title": "第一章 科学边界", "depth": None},
        {"title": "第二章 台球", "depth": None},
    ], local)
    assert pairs == [(0, 1), (1, 0)], "名字对得上就按名字配，不受本地顺序干扰"


def test_对齐_空输入():
    assert reading_list.build_pairs([], []) == []
    assert reading_list.build_pairs(_store_flat(), []) == []
