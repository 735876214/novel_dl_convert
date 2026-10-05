"""第 71 期：跨源搜索的**并发、逐源状态、分页**契约（全程零网络）。

对着 `DownloadManager.search()` 直接测 —— 它现在是唯一产出「命中 + 逐源状态」的地方，
`/api/search` 只把它转成 JSON（`tests/test_sources_gate.py` 管闸门那一层）。

四条不变量（每一条都对应一个第 71 期修掉的真实缺陷）：

1. **逐源状态如实回报**：一个源挂了/超时，不影响别的源出结果，且失败原因是**异常原文** ——
   界面上的「部分书源检索失败」只有这一个信息来源（第 71 期之前这些原因只进日志，
   后端压根不返回，前端那条横幅永远是空的）；
2. **并发**：第 71 期之前是 `for` 里逐个 `await`，而界面写着「正在并发检索各书源」；
   现在每源还有独立超时，慢站不再拖垮整轮；
3. **命中带 `source`**：第 71 期之前只写 `_source`，前端读 `source` ⇒ 来源徽章空白、
   点「预览」必然 502「未知书源: undefined」；
4. **分页不重复**：不支持分页的源取第 2 页必须返回空 —— 拿第一页冒充「下一页」会让
   界面的「加载更多」把同一批结果再显示一遍。
"""
import asyncio
import time

import pytest

from novelforge import config
from novelforge.sources import DownloadManager, REGISTRY, source_of
from novelforge.sources import manager as source_manager
from novelforge.sources.base import SourceAdapter
from novelforge.sources.rules import make_rule_class


class _Stub(SourceAdapter):
    """桩基类：两个抽象方法都实现，子类按需覆写。"""

    async def search(self, client, title):  # pragma: no cover
        raise NotImplementedError

    async def fetch_book(self, client, item):  # pragma: no cover
        raise AssertionError("搜索用例不该取书")


@pytest.fixture
def registry(monkeypatch):
    """摘掉**全部真源**（内置 gutenberg 会真的联网），返回一个装桩助手。

    `monkeypatch.delitem/setitem` 会在用例结束后逐项还原 —— 全局书源表不留痕。
    """
    for name in list(REGISTRY):
        monkeypatch.delitem(REGISTRY, name)

    def _install(name: str, cls: type) -> str:
        monkeypatch.setitem(REGISTRY, name, cls)
        return name

    return _install


def _plain(name: str, *, public: bool = True, items=(), delay: float = 0.0, error=None) -> type:
    """只实现 `search()` 的源 —— 走基类 `search_page` 兜底（第 2 页必须是空）。"""

    async def search(self, client, title):  # noqa: ANN001
        if delay:
            await asyncio.sleep(delay)
        if error is not None:
            raise error
        return [dict(it) for it in items]

    return type(f"Stub_{name}", (_Stub,), {
        "name": name, "display_name": f"{name} 展示名", "public": public, "search": search,
    })


def _paged(name: str, pages, *, public: bool = True) -> type:
    """支持分页的源：每页给不同命中，最后一页报 `has_more=False`。"""

    async def search_page(self, client, title, page=1):  # noqa: ANN001
        rows = pages[page - 1] if 1 <= page <= len(pages) else []
        return {"items": [dict(it) for it in rows], "has_more": page < len(pages)}

    async def search(self, client, title):  # noqa: ANN001
        return (await self.search_page(client, title, 1))["items"]

    return type(f"StubPaged_{name}", (_Stub,), {
        "name": name, "display_name": f"{name} 展示名", "public": public,
        "search": search, "search_page": search_page,
    })


def _mgr(*, enabled: bool = True) -> DownloadManager:
    return DownloadManager({"download": {"enabled": enabled}})


def _rows(res: dict) -> dict:
    return {s["name"]: s for s in res["sources"]}


# ---------------------------------------------------------------------------
# ① 命中打标与逐源状态
# ---------------------------------------------------------------------------

def test_命中带来源字段_失败源如实回报原因(registry):
    registry("ok-src", _plain("ok-src", items=[{"title": "三体", "author": "刘慈欣", "url": "u1"}]))
    registry("boom-src", _plain("boom-src", error=RuntimeError("连接失败：域名不在白名单内")))

    res = asyncio.run(_mgr().search("三体"))

    assert [it["title"] for it in res["items"]] == ["三体"], "一个源挂了不影响别的源出结果"
    it = res["items"][0]
    # 两个键：`source` 是前端与下载路径读的（第 97 期删掉了冗余的历史键 `_source` 写入），
    # `source_name` 是展示名。
    assert (it["source"], it["source_name"]) == ("ok-src", "ok-src 展示名")

    rows = _rows(res)
    assert rows["ok-src"]["ok"] is True and rows["ok-src"]["count"] == 1
    assert rows["boom-src"]["ok"] is False and rows["boom-src"]["count"] == 0
    assert "白名单" in rows["boom-src"]["error"], "失败原因必须是异常原文（界面唯一的信息来源）"
    assert rows["boom-src"]["skipped"] is False, "失败 ≠ 被闸门跳过，两者不能混"


def test_搜索是真并发而不是逐个等待(registry):
    """3 个各睡 0.3s 的源：串行 ≥0.9s，并发 ≈0.3s。阈值 0.7s 留足机器抖动的余量。"""
    for name in ("a-src", "b-src", "c-src"):
        registry(name, _plain(name, delay=0.3))

    t0 = time.monotonic()
    asyncio.run(_mgr().search("三体"))

    assert time.monotonic() - t0 < 0.7, "各源是串行 await 的（界面却写着「正在并发检索」）"


def test_单源超时只影响该源(registry, monkeypatch):
    """慢源（规则源的 `get_text` 原本连 timeout 都没传）不再拖住整轮搜索。"""
    monkeypatch.setattr(source_manager, "SEARCH_TIMEOUT", 0.05)
    registry("slow-src", _plain("slow-src", delay=1.0))
    registry("fast-src", _plain("fast-src", items=[{"title": "快", "author": "", "url": "u"}]))

    res = asyncio.run(_mgr().search("x"))

    rows = _rows(res)
    assert rows["fast-src"]["ok"] is True
    assert "超时" in rows["slow-src"]["error"], rows["slow-src"]
    assert [it["title"] for it in res["items"]] == ["快"]


def test_闸门关闭时每个源都被跳过并如实列出原因(registry):
    """跳过的源**不贡献命中但必须出现在 `sources` 里** —— 否则用户只看到「结果变少了」。"""
    registry("paid-src", _plain("paid-src", public=False,
                                items=[{"title": "付费书", "author": "某人", "url": "u"}]))
    registry("free-src", _plain("free-src", items=[{"title": "免费书", "author": "某人", "url": "u2"}]))

    res = asyncio.run(_mgr(enabled=False).search("x"))

    rows = _rows(res)
    assert set(rows) == {"paid-src", "free-src"}
    assert all(r["skipped"] is True for r in rows.values()), rows
    assert "下载功能未开启" in rows["paid-src"]["reason"], rows["paid-src"]
    assert res["items"] == [], "被闸门跳过的源不该贡献任何命中"


def test_非公版源在下载开启时照常命中(registry):
    """第 93 期删掉「仅放行公版源」后：`public=False` 只是标注，**不再被跳过**。

    留这条挡住「哪天有人顺手把 public 过滤加回 gate_reason」—— `test_sources_gate.py`
    里那条是从 HTTP 入口测同一件事，这里从 `search()` 直接测。
    """
    registry("paid-src", _plain("paid-src", public=False,
                                items=[{"title": "付费书", "author": "某人", "url": "u"}]))

    res = asyncio.run(_mgr().search("x"))

    rows = _rows(res)
    assert rows["paid-src"]["skipped"] is False and rows["paid-src"]["reason"] == "", rows["paid-src"]
    assert [it["title"] for it in res["items"]] == ["付费书"]


# ---------------------------------------------------------------------------
# ② 分页
# ---------------------------------------------------------------------------

def test_不支持分页的源取第二页返回空_不会重复第一页(registry):
    registry("plain-src", _plain("plain-src", items=[{"title": "T", "author": "A", "url": "u"}]))
    mgr = _mgr()

    first = asyncio.run(mgr.search("x", 1))
    second = asyncio.run(mgr.search("x", 2))

    assert len(first["items"]) == 1
    assert second["items"] == [], \
        "取第二页必须为空：否则界面「加载更多」会把第一页原样再显示一遍"
    assert _rows(second)["plain-src"]["has_more"] is False


def test_支持分页的源第二页取到新内容并报has_more(registry):
    registry("paged-src", _paged("paged-src", [
        [{"title": "T1", "author": "A", "url": "u1"}],
        [{"title": "T2", "author": "A", "url": "u2"}],
    ]))
    mgr = _mgr()

    p1 = asyncio.run(mgr.search("x", 1))
    p2 = asyncio.run(mgr.search("x", 2))

    assert [i["title"] for i in p1["items"]] == ["T1"]
    assert _rows(p1)["paged-src"]["has_more"] is True
    assert [i["title"] for i in p2["items"]] == ["T2"]
    assert _rows(p2)["paged-src"]["has_more"] is False, "最后一页要说没有了"


class _RecordingClient:
    """只记 URL 的桩 client：本文件不存在任何真网络调用。"""

    html = '<a href="/b/1">三体</a>'

    def __init__(self):
        self.urls: list[str] = []

    async def get_text(self, url: str) -> str:
        self.urls.append(url)
        return self.html


def _rule_src(url_tpl: str, name: str = "rule-src") -> type:
    return make_rule_class({
        "name": name,
        "display_name": "规则源",
        "domains": ["e.com"],
        "public": True,
        "search": {
            "url": url_tpl,
            "mode": "regex",
            "pattern": '<a href="(?P<url>[^"]+)">(?P<title>[^<]+)</a>',
        },
        "book": {"mode": "single", "content": {"mode": "css", "container": "#c", "text": True}},
        "chapter": {"mode": "auto"},
    })


def test_规则源第一页URL与加分页能力之前逐字节一致():
    """`{title}` 仍是唯一的必须占位；没写 `{page}` 的规则，`search()` 与从前是同一个请求。"""
    client = _RecordingClient()

    asyncio.run(_rule_src("https://e.com/s?q={title}")().search(client, "三体"))

    assert client.urls == ["https://e.com/s?q=%E4%B8%89%E4%BD%93"], client.urls


def test_规则源没写page占位时第二页不发请求():
    """不知道还有没有下一页就如实说没有 —— 猜成「还有」会挂一个点了没反应的按钮。"""
    client = _RecordingClient()
    src = _rule_src("https://e.com/s?q={title}")()

    first = asyncio.run(src.search_page(client, "三体", 1))
    # url 已按搜索页补成绝对地址（见下方 `_absolutize` 的两条用例）；这里只关心「只搜了一次」
    assert first["items"][0]["url"] == "https://e.com/b/1"
    assert first["has_more"] is False

    before = list(client.urls)
    second = asyncio.run(src.search_page(client, "三体", 2))

    assert second == {"items": [], "has_more": False}
    assert client.urls == before, "不支持分页的规则不该为第二页白跑一次请求"


def test_规则源写了page占位才真取下一页():
    client = _RecordingClient()
    src = _rule_src("https://e.com/s?q={title}&page={page}")()

    asyncio.run(src.search_page(client, "三体", 1))
    assert client.urls[-1] == "https://e.com/s?q=%E4%B8%89%E4%BD%93&page=1"

    out = asyncio.run(src.search_page(client, "三体", 2))

    assert client.urls[-1] == "https://e.com/s?q=%E4%B8%89%E4%BD%93&page=2"
    assert out["items"], "第二页要真的返回内容"
    assert out["has_more"] is True, "模板支持分页且本页有结果 ⇒ 可能还有下一页"


def test_规则源把搜索命中的相对地址补成绝对地址():
    """真实站点几乎都用相对链接（`/book/1`），而取书与预览都拿 `item["url"]` 直接请求。

    不补的话会以「Request URL is missing an 'http://' or 'https://' protocol.」失败 ——
    那句报错离真正的原因（规则抓到的是相对地址）很远。章节目录（`_extract_links`）一直就在
    做 urljoin，搜索结果这条路是第 71 期冒烟才发现的漏网（`tests/` 与真机都复现）。
    """
    client = _RecordingClient()          # html = '<a href="/b/1">三体</a>'
    src = _rule_src("https://e.com/s?q={title}")()

    out = asyncio.run(src.search_page(client, "三体", 1))

    assert out["items"][0]["url"] == "https://e.com/b/1"


def test_规则源不改变本来就绝对的地址():
    """补全是**幂等**的：既有规则里写绝对地址的一律原样保留（写规则的人不必改）。"""

    class _AbsClient:
        html = '<a href="https://cdn.example.com/b/1">三体</a>'

        async def get_text(self, url: str) -> str:
            return self.html

    src = _rule_src("https://e.com/s?q={title}")()

    out = asyncio.run(src.search_page(_AbsClient(), "三体", 1))

    assert out["items"][0]["url"] == "https://cdn.example.com/b/1"


# ---------------------------------------------------------------------------
# ③ 源名读法 与 /api/search 的响应形状
# ---------------------------------------------------------------------------

def test_源名读法两个键都认():
    """`source`（新）与 `_source`（历史）都认，且新键优先 —— 否则旧 sidecar 会失效。"""
    assert source_of({"source": "a"}) == "a"
    assert source_of({"_source": "b"}) == "b"
    assert source_of({"source": "a", "_source": "b"}) == "a"
    assert source_of({}) == ""
    assert source_of(None) == ""


def test_搜索接口返回逐源状态与分页标记(client, auth_headers, isolated, monkeypatch, tmp_path, registry):  # noqa: ARG001
    """HTTP 层的形状：`sources` 在、空的 `errors` 已下线、命中带 `source`。"""
    registry("stub-src", _plain("stub-src",
                                items=[{"title": "三体", "author": "刘慈欣", "url": "https://e.com/1"}]))
    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "settings.json")
    config.save_overrides({"download": {"enabled": True}})

    r = client.post("/api/search", headers=auth_headers, json={"title": "三体"})

    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) >= {"count", "results", "sources", "has_more", "page"}
    assert "errors" not in body, "空的 errors 已移除：真实信息现在在 sources 里"
    assert body["page"] == 1 and body["has_more"] is False
    assert [s["name"] for s in body["sources"]] == ["stub-src"]
    assert body["results"][0]["source"] == "stub-src", "前端读的就是这个键（预览/徽章都用它）"


def test_搜索接口第二页沿用逐源分页(client, auth_headers, isolated, monkeypatch, tmp_path, registry):  # noqa: ARG001
    registry("paged-src", _paged("paged-src", [
        [{"title": "T1", "author": "A", "url": "u1"}],
        [{"title": "T2", "author": "A", "url": "u2"}],
    ]))
    monkeypatch.setattr(config, "SETTINGS_FILE", tmp_path / "settings.json")
    config.save_overrides({"download": {"enabled": True}})

    p1 = client.post("/api/search", headers=auth_headers, json={"title": "x"}).json()
    p2 = client.post("/api/search", headers=auth_headers, json={"title": "x", "page": 2}).json()

    assert p1["has_more"] is True and [it["title"] for it in p1["results"]] == ["T1"]
    assert p2["page"] == 2 and p2["has_more"] is False
    assert [it["title"] for it in p2["results"]] == ["T2"]
